"""EnSosyal ingestion adapter — a contract, not a scraper.

What this module is
-------------------
EnSosyal's team hands this project post data (an authorised API response, an
export, or a webhook body). This adapter turns that payload into the canonical
`PostRecord` columns the pipeline expects, and applies the KVKK filter on the
way in. It is the only place where EnSosyal field names appear.

What this module deliberately is **not**
----------------------------------------
* No session/cookie reuse, no undocumented endpoint defaults, no anti-bot
  handling. `EnSosyalClient` requires an explicit base URL and bearer token that
  the data controller issues; without them it raises instead of guessing.
* No PII retention by default: `user_id` is pseudonymised with a salted hash,
  the rows are scrubbed of URLs/handles/e-mails/phone numbers, and profile text,
  location and media files are dropped unless a caller explicitly opts in.
* No engagement guessing: the training target is computed by one documented
  formula whose weights are recorded next to the data.

Legal boundary (see docs/ENSOSYAL_ADAPTATION.md): shipping this code is harmless.
Running it against a system you are not authorised to read is not. The transport
must exist under a data-processing agreement between EnSosyal (veri sorumlusu)
and this project (veri işleyen).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd
import httpx

from backend.services.canonical_taxonomy import CANONICAL_CATEGORIES
from backend.services.post_contract import (
    ENSOSYAL_SOURCE_ID,
    INGESTED_COLUMNS,
    OUTPUT_COLUMNS,
    add_leakage_free_priors,
    assert_column_contract,
    media_file_is_readable,
    optional_float,
    validate_against_schema,
)
from backend.services.time_features import resolve_post_local_time

PSEUDONYM_SALT_ENV = "ENSOSYAL_PSEUDONYM_SALT"
API_TOKEN_ENV = "ENSOSYAL_API_TOKEN"
API_BASE_URL_ENV = "ENSOSYAL_API_BASE_URL"

# ---------------------------------------------------------------------------
# Field mapping: the single place to touch when EnSosyal's contract changes.
# Keys are EnSosyal's field names, values are the canonical concepts. Several
# candidate spellings are accepted per concept because the same value travels as
# `id`/`post_id`, `text`/`caption`, and so on across their endpoints.
# ---------------------------------------------------------------------------
FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "post_id": ("post_id", "id", "postId", "post_uuid", "uuid"),
    "user_id": ("user_id", "userId", "author_id", "authorId", "owner_id", "member_id"),
    "published_at": ("published_at", "publishedAt", "created_at", "createdAt", "date", "timestamp"),
    "published_at_utc": ("published_at_utc", "created_at_utc", "publishedAtUtc"),
    "timezone_offset": ("timezone_offset", "utc_offset", "gmt_offset", "timezoneOffset"),
    "timezone_name": ("timezone", "time_zone", "timezone_name", "tz"),
    "title": ("text", "caption", "title", "content", "description"),
    "tags": ("tags", "hashtags", "tag_list", "topics"),
    "media_type": ("media_type", "mediaType", "type", "post_type", "kind"),
    "media_url": ("media_url", "mediaUrl", "image_url", "photo_url", "media_ref"),
    "category": ("category", "canonical_category", "topic", "category_l1"),
    "subcategory": ("subcategory", "category_l2", "sub_category"),
    "location": ("location", "place", "geo", "location_name"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lng", "lon"),
    "views": ("views", "view_count", "impressions", "impression_count", "reach"),
    "likes": ("likes", "like_count", "likes_count", "favorites"),
    "comments": ("comments", "comment_count", "comments_count"),
    "shares": ("shares", "share_count", "reposts", "reshare_count"),
    "saves": ("saves", "save_count", "bookmarks", "bookmark_count"),
    "engagement_window_hours": ("engagement_window_hours", "measurement_window_hours", "window_hours"),
    "follower_count": ("follower_count", "followers", "followerCount"),
    "is_public": ("is_public", "public", "visibility_public"),
}

# Fields dropped unless `EnSosyalAdapterConfig.keep_personal_fields` is set.
PERSONAL_FIELDS = ("profile_text", "bio", "about", "location", "place", "email", "phone")

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_HANDLE_RE = re.compile(r"(?<!\w)@[\w.]+")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")

MEDIA_TYPE_MAP = {
    "photo": "photo", "image": "photo", "picture": "photo", "jpg": "photo", "jpeg": "photo", "png": "photo",
    "video": "video", "clip": "video", "reel": "video", "mp4": "video", "mov": "video",
}


class EnSosyalTransportNotConfigured(RuntimeError):
    """Raised when no authorised transport was provided.

    The adapter refuses to invent an endpoint or reuse a browser session: the
    base URL and token must come from the data controller.
    """


@dataclass
class EngagementWeights:
    """Weights used to turn raw counters into the training target.

    The target is log-scaled so it is comparable with SMPD's log-view score
    (otherwise a handful of viral posts dominate every metric). Freeze these
    numbers before training: changing them changes the target definition and
    makes two runs incomparable.
    """

    like: float = 1.0
    comment: float = 2.0
    share: float = 3.0
    save: float = 3.0

    def weighted_interactions(self, interactions: dict[str, float]) -> float:
        return sum(
            self.__dict__[name] * interactions.get(name, 0.0)
            for name in ("like", "comment", "share", "save")
        )

    def score(self, views: float | None, interactions: dict[str, float]) -> float | None:
        """log1p of the reach metric; log1p of weighted interactions without views.

        The two branches are not mixed on purpose: likes and comments are
        already a consequence of views, so adding them to the view count would
        count the same engagement twice. When neither signal exists the row has
        no target and the caller drops it.
        """
        if views is not None and views > 0:
            return round(math.log1p(views), 4)
        weighted = self.weighted_interactions(interactions)
        if weighted > 0:
            return round(math.log1p(weighted), 4)
        return None


@dataclass
class EnSosyalAdapterConfig:
    """How strict the adapter is about the data it accepts."""

    pseudonymize_users: bool = True
    scrub_text: bool = True
    drop_personal_fields: bool = True
    media_root: str = "data/raw/ensosyal_media"
    engagement_weights: EngagementWeights = field(default_factory=EngagementWeights)
    salt: str | None = None

    def resolved_salt(self) -> str:
        salt = self.salt or os.getenv(PSEUDONYM_SALT_ENV, "")
        if not salt:
            raise EnSosyalTransportNotConfigured(
                f"{PSEUDONYM_SALT_ENV} is not set. Pseudonymising user ids needs a project salt: "
                "without one the pseudonyms are not stable across runs, and with a guessable one "
                "they are reversible. Set the env var (or pass config.salt) before ingesting."
            )
        return salt


def get_field(payload: dict, concept: str) -> Any:
    """Returns the first present candidate for a canonical concept."""
    for candidate in FIELD_CANDIDATES.get(concept, ()):
        if candidate in payload and payload[candidate] is not None:
            return payload[candidate]
    return None


def pseudonymize_user_id(user_id: Any, salt: str) -> str:
    """Stable, salted pseudonym. The model only needs per-user grouping."""
    digest = hashlib.sha256(f"{salt}:{user_id}".encode("utf-8")).hexdigest()
    return f"ensy_{digest[:24]}"


def scrub_text(value: Any) -> str:
    """Removes URLs, handles, e-mails and phone-like strings from free text.

    This is both a privacy measure (the training corpus must not carry contact
    details) and a feature-quality one: the SMPD titles show how much noise
    handles and links add to the title SVD.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    text = _URL_RE.sub(" ", text)
    text = _EMAIL_RE.sub(" ", text)
    text = _HANDLE_RE.sub(" ", text)
    text = _PHONE_RE.sub(" ", text)
    return " ".join(text.split())


def normalize_tags(raw_tags: Any) -> list[str]:
    """Accepts a list, a comma/space separated string, or a dict of tag->count."""
    if raw_tags is None:
        return []
    if isinstance(raw_tags, dict):
        items: Iterable[Any] = raw_tags.keys()
    elif isinstance(raw_tags, str):
        items = re.split(r"[,\s]+", raw_tags)
    elif isinstance(raw_tags, (list, tuple, set)):
        items = raw_tags
    else:
        return []
    tags: list[str] = []
    for item in items:
        token = str(item).strip().lower().lstrip("#").replace(" ", "")
        if token:
            tags.append(f"#{token}")
    return list(dict.fromkeys(tags))


def normalize_media_type(raw: Any) -> str:
    """Maps platform media types onto the canonical three; unknown stays unknown."""
    return MEDIA_TYPE_MAP.get(str(raw or "").strip().lower(), "unknown")


def to_post_record(
    payload: dict,
    *,
    config: EnSosyalAdapterConfig,
    ingested_at_utc: datetime | None = None,
) -> dict | None:
    """Maps one EnSosyal payload onto the canonical ingestion row.

    Returns None when the payload cannot be a training row (no id, no author, no
    usable timestamp, or no engagement signal at all): skipping loudly is better
    than inventing a target.

    The returned dict holds the *source-derived* columns
    (`post_contract.INGESTED_COLUMNS`); the two per-user prior columns are added
    by `ingest_payloads`, which sees the whole batch and can compute them
    chronologically.
    """
    ingested_at_utc = ingested_at_utc or datetime.now(timezone.utc)

    post_id = get_field(payload, "post_id")
    user_id = get_field(payload, "user_id")
    if post_id is None or user_id is None:
        return None

    published = get_field(payload, "published_at_utc") or get_field(payload, "published_at")
    if not published:
        return None

    offset = get_field(payload, "timezone_offset")
    local = resolve_post_local_time(published, offset)

    views = optional_float(get_field(payload, "views"))
    interactions = {
        "like": optional_float(get_field(payload, "likes")) or 0.0,
        "comment": optional_float(get_field(payload, "comments")) or 0.0,
        "share": optional_float(get_field(payload, "shares")) or 0.0,
        "save": optional_float(get_field(payload, "saves")) or 0.0,
    }
    popularity = config.engagement_weights.score(views, interactions)
    if popularity is None:
        return None  # no engagement signal at all: no target, no row

    title = get_field(payload, "title") or ""
    if config.scrub_text:
        title = scrub_text(title)
    else:
        title = str(title).strip()

    media_url = get_field(payload, "media_url")
    media_available = (
        media_file_is_readable(str(media_url), media_root=Path(config.media_root)) if media_url else False
    )

    resolved_user = (
        pseudonymize_user_id(user_id, config.resolved_salt())
        if config.pseudonymize_users
        else str(user_id)
    )

    return {
        "schema_version": "1.0",
        "source": ENSOSYAL_SOURCE_ID,
        "post_id": str(post_id),
        "user_id": resolved_user,
        "published_at_utc": local.utc_dt,
        "timezone_offset": (str(offset).strip() or None) if offset is not None else None,
        "timezone_id": (str(get_field(payload, "timezone_name")).strip() or None)
        if get_field(payload, "timezone_name") is not None
        else None,
        "local_datetime": local.local_dt.replace(tzinfo=None),
        "local_hour": local.local_hour,
        "local_weekday": local.local_weekday,
        "timezone_basis": local.basis,
        "title": title,
        "description": None,
        "tags": normalize_tags(get_field(payload, "tags")),
        "media_type": normalize_media_type(get_field(payload, "media_type")),
        "media_path": str(media_url) if media_url else None,
        "media_available": media_available,
        # A canonical category from the source is trusted as-is; anything else
        # is left empty so `classify_post_category` derives it from the title
        # instead of the pipeline treating a foreign label as a keyword match.
        "category_l1": reconcile_category(payload, CANONICAL_CATEGORIES),
        "category_l2": _optional_text(get_field(payload, "subcategory")),
        "concept": None,
        # Location is personal data the model never uses: dropped unless the
        # caller explicitly opts in (and even then only as coarse numbers).
        "latitude": None if config.drop_personal_fields else optional_float(get_field(payload, "latitude")),
        "longitude": None if config.drop_personal_fields else optional_float(get_field(payload, "longitude")),
        "source_user_photo_count": None,
        "popularity_score": popularity,
        "ingested_at_utc": ingested_at_utc,
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def ingest_payloads(
    payloads: Iterable[dict],
    *,
    config: EnSosyalAdapterConfig | None = None,
    ingested_at_utc: datetime | None = None,
    skip_log: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """Converts a batch of payloads into a canonical, contract-checked frame.

    The frame has exactly the pipeline columns and passes the same gates the
    SMPD path uses, so both sources are interchangeable downstream. Duplicate
    post ids are dropped (keeping the first) rather than failing the batch —
    an export that overlaps two windows is normal.
    """
    config = config or EnSosyalAdapterConfig()
    ingested_at_utc = ingested_at_utc or datetime.now(timezone.utc)
    rows: list[dict] = []
    skipped = 0
    dropped_personal: dict[str, int] = {}
    for payload in payloads:
        for key in PERSONAL_FIELDS:
            if key in payload and payload[key] not in (None, "", [], {}):
                dropped_personal[key] = dropped_personal.get(key, 0) + 1
        row = to_post_record(payload, config=config, ingested_at_utc=ingested_at_utc)
        if row is None:
            skipped += 1
            if skip_log is not None:
                skip_log(f"skipped payload without id/author/timestamp: post_id={payload.get('post_id') or payload.get('id')}")
            continue
        rows.append(row)

    frame = pd.DataFrame(rows, columns=INGESTED_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["post_id"], keep="first").reset_index(drop=True)
        frame = add_leakage_free_priors(frame)
    else:
        frame = pd.DataFrame(columns=OUTPUT_COLUMNS)
    assert_column_contract(list(frame.columns))
    if not frame.empty:
        validate_against_schema(frame)
    frame.attrs["skipped_payloads"] = skipped
    # Auditable privacy record: which personal fields arrived and were dropped.
    frame.attrs["dropped_personal_fields"] = dropped_personal
    return frame


class EnSosyalClient:
    """Authorised transport for pulling posts from an EnSosyal-provided endpoint.

    Deliberately minimal: bearer token, one documented path, bounded pages. It
    does not authenticate as a user, hold cookies, or discover endpoints — those
    are the data controller's responsibility under the processing agreement.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        posts_path: str = "/api/v1/posts",
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = (base_url or os.getenv(API_BASE_URL_ENV, "")).rstrip("/")
        self.token = token or os.getenv(API_TOKEN_ENV, "")
        self.posts_path = posts_path
        self.timeout = timeout_seconds
        self._client = client

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def fetch_posts(self, *, since: str | None = None, until: str | None = None, limit: int = 500) -> list[dict]:
        """Pulls one page of posts. Pagination is the caller's loop, on purpose."""
        if not self.is_configured:
            raise EnSosyalTransportNotConfigured(
                f"EnSosyal transport is not configured: set {API_BASE_URL_ENV} and {API_TOKEN_ENV} "
                "(or pass base_url/token) with credentials issued by EnSosyal. This adapter will not "
                "guess an endpoint or reuse a browser session."
            )
        params = {key: value for key, value in {"since": since, "until": until, "limit": limit}.items() if value}
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            response = client.get(f"{self.base_url}{self.posts_path}", params=params, headers=self._headers())
            response.raise_for_status()
            body = response.json()
        finally:
            if owns_client:
                client.close()

        if isinstance(body, dict):
            for key in ("data", "results", "posts", "items"):
                if isinstance(body.get(key), list):
                    return body[key]
            return [body]
        return body if isinstance(body, list) else []


def reconcile_category(payload: dict, canonical_categories: Iterable[str]) -> str | None:
    """Returns the payload category when EnSosyal already speaks the canonical names.

    The pipeline classifies categories from the title when they are absent; this
    helper exists so a source that *does* send canonical categories can be
    trusted instead of re-derived.
    """
    raw = _optional_text(get_field(payload, "category"))
    if raw is None:
        return None
    normalized = raw.strip().lower().replace(" ", "_").replace("-", "_")
    return normalized if normalized in set(canonical_categories) else None


__all__ = [
    "EnSosyalAdapterConfig",
    "EnSosyalClient",
    "EnSosyalTransportNotConfigured",
    "EngagementWeights",
    "FIELD_CANDIDATES",
    "get_field",
    "ingest_payloads",
    "normalize_media_type",
    "normalize_tags",
    "pseudonymize_user_id",
    "reconcile_category",
    "scrub_text",
    "to_post_record",
]
