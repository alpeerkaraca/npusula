"""EnSosyal ingestion adapter — a contract, not a scraper.

Shapes handled
--------------
EnSosyal's feed responses (schema: `nsosyal_features.json.shema`) arrive as::

    {"success": true, "message": "...", "data": {"items": [Post, ...], "total": N}}

What this module is
-------------------
The data controller hands over a payload (API response, export or webhook body)
and this adapter maps it onto the canonical `PostRecord` columns, applying the
KVKK filter on the way in. It is the only place where EnSosyal field names
appear (`FIELD_CANDIDATES`).

What this module deliberately is **not**
----------------------------------------
* No session/cookie reuse, no endpoint defaults, no anti-bot handling:
  `EnSosyalClient` requires credentials the data controller issues.
* No PII retention by default: `user_id` is pseudonymised with a salted hash,
  free text is stripped of HTML/URLs/handles/e-mails/phone numbers, and the
  account object (username, display name, bio, avatar, profile fields), mentions,
  card and location are dropped. The batch reports what arrived and was dropped.
* No engagement guessing: the training target has one documented formula whose
  weights are frozen before training.

Timezone reality (the schema has no timezone field)
---------------------------------------------------
Neither `Post` nor `Account` carries a timezone or UTC offset. The only signal is
the offset embedded in `created_at`:

* ``"2026-09-12T21:30:00+03:00"`` → real local time, ``timezone_basis="source_offset"``
* ``"2026-09-12T18:30:00Z"`` or naive → no local time, ``timezone_basis="utc_fallback"``

Fallback rows still train Layer A, but Layer B (the window layer) must not make
local-time claims for them — the pipeline enforces that. If EnSosyal wants window
recommendations, they must send the user's timezone or an offset; until then every
row is a fallback and the window answer stays "belirsiz".
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
from backend.services.time_features import parse_utc_offset, resolve_post_local_time

PSEUDONYM_SALT_ENV = "ENSOSYAL_PSEUDONYM_SALT"
API_TOKEN_ENV = "ENSOSYAL_API_TOKEN"
API_BASE_URL_ENV = "ENSOSYAL_API_BASE_URL"

# ---------------------------------------------------------------------------
# Field mapping: the single place to touch when EnSosyal's contract changes.
# Paths are dotted ("account.account_id") so nested objects need no special case.
# Several spellings are accepted per concept because the same value travels under
# different names across feed/detail endpoints.
# ---------------------------------------------------------------------------
FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "post_id": ("id", "post_id", "postId", "post_uuid", "uuid"),
    "user_id": ("account.account_id", "account.id", "author_id", "userId", "user_id", "owner_id"),
    "published_at": ("created_at", "published_at", "createdAt", "published_at_utc", "date"),
    "title": ("text", "caption", "content", "title"),
    "tags": ("tags", "hashtags", "tag_list"),
    "media_attachments": ("media_attachments", "media", "attachments"),
    "media_type": ("media_type", "mediaType", "post_type"),
    "visibility": ("visibility",),
    "sensitive": ("sensitive",),
    "spoiler_text": ("spoiler_text",),
    "language": ("language",),
    "timezone_offset": ("timezone_offset", "utc_offset", "gmt_offset", "timezoneOffset"),
    "timezone_name": ("timezone", "time_zone", "timezone_name", "tz"),
    "category": ("category", "canonical_category", "topic", "category_l1"),
    "subcategory": ("subcategory", "category_l2", "sub_category"),
    # Reach first: views_count is post reach. detail_views/profile_views are
    # *page* views, not post distribution, so they are intentionally absent.
    "views": ("views_count", "views", "impressions", "impression_count", "view_count", "reach"),
    "likes": ("favourites_count", "likes_count", "like_count", "likes", "favorites"),
    "comments": ("replies_count", "comments_count", "comment_count", "comments"),
    "shares": ("reblogs_count", "shares_count", "share_count", "shares", "reposts"),
    "quotes": ("quote_count", "quotes_count"),
    "saves": ("bookmarks_count", "save_count", "saves", "bookmarks"),
    "latitude": ("latitude", "lat", "location.latitude"),
    "longitude": ("longitude", "lng", "lon", "location.longitude"),
}

# Personal-data paths counted (and dropped) for the ingest audit. None of them has
# a column in the canonical contract, so the drop is structural — the audit exists
# so the team can show exactly what arrived and what was discarded.
AUDITED_PERSONAL_PATHS = (
    "account.username",
    "account.display_name",
    "account.bio",
    "account.fields",
    "account.avatar",
    "account.header",
    "mentions",
    "card",
    "spoiler_text",
)

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_HANDLE_RE = re.compile(r"(?<!\w)@[\w.]+")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITIES = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
    "&#39;": "'", "&apos;": "'", "&nbsp;": " ",
}
_TIMESTAMP_OFFSET_RE = re.compile(r"(?P<offset>[+-]\d{2}:?\d{2})$")

MEDIA_TYPE_MAP = {
    "image": "photo", "photo": "photo", "picture": "photo", "jpg": "photo", "jpeg": "photo", "png": "photo",
    "video": "video", "gifv": "video", "reel": "video", "clip": "video", "mp4": "video", "mov": "video",
}

DEFAULT_ALLOWED_VISIBILITY = frozenset({"public", "unlisted"})

SKIP_REASONS = (
    "no_id",
    "no_author",
    "no_timestamp",
    "no_engagement",
    "visibility_filtered",
    "sensitive_filtered",
)


class EnSosyalTransportNotConfigured(RuntimeError):
    """Raised when no authorised transport was provided.

    The adapter refuses to invent an endpoint or reuse a browser session: the
    base URL and token must come from the data controller.
    """


class EnSosyalResponseError(RuntimeError):
    """The API answered with ``success: false`` or an envelope we cannot read."""


@dataclass
class EngagementWeights:
    """Weights used to turn raw counters into the training target.

    The target is log-scaled so it is comparable with SMPD's log-view score
    (otherwise a handful of viral posts dominate every metric). Freeze these
    numbers before training: changing them changes the target definition and makes
    two runs incomparable.
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

        The two branches are not mixed on purpose: likes and comments are already a
        consequence of views, so adding them to the view count would count the same
        engagement twice. When neither signal exists the row has no target and the
        caller drops it.
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
    # Distribution policy: the timing model only learns from posts the platform
    # actually distributed. `private`/`direct` posts reach a handful of people and
    # are the most personal, so they are skipped by default and counted.
    allowed_visibility: frozenset[str] = DEFAULT_ALLOWED_VISIBILITY
    # Posts the platform itself flags as sensitive are skipped unless opted in.
    include_sensitive: bool = False

    def resolved_salt(self) -> str:
        salt = self.salt or os.getenv(PSEUDONYM_SALT_ENV, "")
        if not salt:
            raise EnSosyalTransportNotConfigured(
                f"{PSEUDONYM_SALT_ENV} is not set. Pseudonymising user ids needs a project salt: "
                "without one the pseudonyms are not stable across runs, and with a guessable one they "
                "are reversible. Set the env var (or pass config.salt) before ingesting."
            )
        return salt


# ---------------------------------------------------------------------------
# payload helpers
# ---------------------------------------------------------------------------
def unwrap_envelope(body: Any) -> tuple[list[dict], int | None]:
    """Extracts the post list (and total) from the feed envelope.

    Handles the documented shape ``{"success": bool, "data": {"items": [...],
    "total": N}}`` as well as plain lists and the usual alternative envelopes, so
    a contract change surfaces as a clear error instead of an empty ingest.
    """
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)], None
    if not isinstance(body, dict):
        raise EnSosyalResponseError(f"unexpected response type: {type(body).__name__}")

    if body.get("success") is False:
        raise EnSosyalResponseError(f"EnSosyal reported failure: {body.get('message')!r}")

    data = body.get("data", body)
    if isinstance(data, dict):
        total = data.get("total")
        for key in ("items", "posts", "results", "data"):
            candidate = data.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)], total
        if "id" in data:  # a single post body
            return [data], total
        return [], total
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)], body.get("total")

    for key in ("items", "posts", "results"):
        candidate = body.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)], body.get("total")
    raise EnSosyalResponseError("could not locate a post list in the response envelope")


def _dotted_get(payload: dict, path: str) -> Any:
    node: Any = payload
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def get_field(payload: dict, concept: str) -> Any:
    """Returns the first present candidate for a concept, following dotted paths."""
    for candidate in FIELD_CANDIDATES.get(concept, ()):
        node = _dotted_get(payload, candidate)
        if node is not None and node != "":
            return node
    return None


def has_path(payload: dict, path: str) -> bool:
    """True when a personal-data path is present and non-empty."""
    return _dotted_get(payload, path) not in (None, "", [], {})


def _format_offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    absolute = abs(minutes)
    return f"{sign}{absolute // 60:02d}:{absolute % 60:02d}"


def extract_offset_from_timestamp(value: Any) -> str | None:
    """Returns the UTC offset a timestamp declares inline, if any.

    ``date-time`` values may carry ``Z``, an offset, or nothing. Only an explicit
    offset is a real conversion; ``Z`` and naive values are honestly reported as
    ``utc_fallback`` downstream.
    """
    text = str(value or "").strip()
    match = _TIMESTAMP_OFFSET_RE.search(text)
    if match is None:
        return None
    parsed = parse_utc_offset(match.group("offset"))
    return None if parsed is None else _format_offset(int(parsed.total_seconds() // 60))


def declared_offset(payload: dict, published_at: Any) -> str | None:
    """Resolves the post's UTC offset: explicit field first, timestamp second.

    An IANA name (if a future contract adds one) is resolved at the post's own
    instant, so DST is handled correctly.
    """
    explicit = get_field(payload, "timezone_offset")
    if explicit is not None:
        parsed = parse_utc_offset(explicit)
        if parsed is not None:
            return _format_offset(int(parsed.total_seconds() // 60))

    tz_name = get_field(payload, "timezone_name")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            instant = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=timezone.utc)
            offset = instant.astimezone(ZoneInfo(str(tz_name))).utcoffset()
            if offset is not None:
                return _format_offset(int(offset.total_seconds() // 60))
        except Exception:
            return extract_offset_from_timestamp(published_at)

    return extract_offset_from_timestamp(published_at)


def pseudonymize_user_id(user_id: Any, salt: str) -> str:
    """Stable, salted pseudonym. The model only needs per-user grouping."""
    digest = hashlib.sha256(f"{salt}:{user_id}".encode("utf-8")).hexdigest()
    return f"ensy_{digest[:24]}"


def scrub_text(value: Any) -> str:
    """Removes HTML, URLs, handles, e-mails and phone-like strings from free text.

    This is both a privacy measure (the training corpus must not carry contact
    details) and a feature-quality one: the SMPD titles show how much noise
    handles and links add to the title SVD.
    """
    text = str(value or "")
    if not text:
        return ""
    text = _HTML_TAG_RE.sub(" ", text)
    for entity, replacement in _HTML_ENTITIES.items():
        text = text.replace(entity, replacement)
    text = _URL_RE.sub(" ", text)
    text = _EMAIL_RE.sub(" ", text)
    text = _HANDLE_RE.sub(" ", text)
    text = _PHONE_RE.sub(" ", text)
    return " ".join(text.split())


def normalize_tags(raw_tags: Any) -> list[str]:
    """Accepts ``[{"name": "x", "url": ...}]``, a list of strings, a dict or a string."""
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
        if isinstance(item, dict):
            item = item.get("name") or item.get("tag") or ""
        token = str(item).strip().lower().lstrip("#").replace(" ", "")
        if token:
            tags.append(f"#{token}")
    return list(dict.fromkeys(tags))


def normalize_media_type(raw: Any) -> str:
    """Maps platform media types onto the canonical three; unknown stays unknown."""
    return MEDIA_TYPE_MAP.get(str(raw or "").strip().lower(), "unknown")


def resolve_media_type(payload: dict) -> str:
    """Resolves the media type from the attachments, then from any explicit field.

    A post with any video/gifv attachment is a video post; audio and anything the
    platform marks ``unknown`` stays ``unknown`` rather than becoming a photo.
    """
    attachments = get_field(payload, "media_attachments")
    attachment_types: list[str] = []
    if isinstance(attachments, (list, tuple)):
        for item in attachments:
            if isinstance(item, dict) and item.get("type"):
                attachment_types.append(str(item["type"]).lower())
    if any(kind in {"video", "gifv"} for kind in attachment_types):
        return "video"
    if any(kind == "image" for kind in attachment_types):
        return "photo"
    if attachment_types:  # audio / unknown
        return "unknown"

    explicit = get_field(payload, "media_type")
    return normalize_media_type(explicit) if explicit is not None else "unknown"


def _first_media_url(payload: dict) -> str | None:
    attachments = get_field(payload, "media_attachments")
    if isinstance(attachments, (list, tuple)):
        for item in attachments:
            if isinstance(item, dict):
                for key in ("url", "preview_url", "remote_url"):
                    if item.get(key):
                        return str(item[key])
    return None


def engagement_counters(payload: dict) -> tuple[float | None, dict[str, float]]:
    """Reads the counters this contract exposes, folding quotes into shares."""
    views = optional_float(get_field(payload, "views"))
    interactions = {
        "like": optional_float(get_field(payload, "likes")) or 0.0,
        "comment": optional_float(get_field(payload, "comments")) or 0.0,
        "share": (optional_float(get_field(payload, "shares")) or 0.0)
        + (optional_float(get_field(payload, "quotes")) or 0.0),
        "save": optional_float(get_field(payload, "saves")) or 0.0,
    }
    return views, interactions


def skip_reason(payload: dict, config: EnSosyalAdapterConfig) -> str | None:
    """Why this payload will not become a row (None when it will).

    Separating this from the mapping keeps the ingest report honest: "we skipped
    412 private posts" is a policy decision, while "we skipped 9 rows without an
    author" is a contract bug, and they must not look the same.
    """
    if get_field(payload, "post_id") is None:
        return "no_id"
    if get_field(payload, "user_id") is None:
        return "no_author"
    if not get_field(payload, "published_at"):
        return "no_timestamp"

    visibility = get_field(payload, "visibility")
    if visibility is not None and str(visibility).lower() not in config.allowed_visibility:
        return "visibility_filtered"
    if bool(get_field(payload, "sensitive")) and not config.include_sensitive:
        return "sensitive_filtered"

    views, interactions = engagement_counters(payload)
    if config.engagement_weights.score(views, interactions) is None:
        return "no_engagement"
    return None


def to_post_record(
    payload: dict,
    *,
    config: EnSosyalAdapterConfig,
    ingested_at_utc: datetime | None = None,
) -> dict | None:
    """Maps one EnSosyal payload onto the canonical ingestion row.

    Returns None when the payload cannot be a training row; `skip_reason` says
    which gate rejected it. The returned dict holds the *source-derived* columns
    (`post_contract.INGESTED_COLUMNS`); the two per-user prior columns are added by
    `ingest_payloads`, which sees the whole batch and can compute them
    chronologically.

    Personal data never reaches the row: the account object contributes only
    `account_id`, mentions/card/profile fields have no column, free text is
    scrubbed, and location is dropped unless explicitly opted in.
    """
    ingested_at_utc = ingested_at_utc or datetime.now(timezone.utc)
    if skip_reason(payload, config) is not None:
        return None

    post_id = get_field(payload, "post_id")
    user_id = get_field(payload, "user_id")
    published = get_field(payload, "published_at")
    offset = declared_offset(payload, published)
    local = resolve_post_local_time(published, offset)

    views, interactions = engagement_counters(payload)
    popularity = config.engagement_weights.score(views, interactions)
    if popularity is None:  # defensive: skip_reason already rejects these
        return None

    title = get_field(payload, "title") or ""
    title = scrub_text(title) if config.scrub_text else str(title).strip()

    media_url = _first_media_url(payload)
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
        "timezone_offset": offset,
        "timezone_id": _optional_text(get_field(payload, "timezone_name")),
        "local_datetime": local.local_dt.replace(tzinfo=None),
        "local_hour": local.local_hour,
        "local_weekday": local.local_weekday,
        "timezone_basis": local.basis,
        "title": title,
        "description": None,
        "tags": normalize_tags(get_field(payload, "tags")),
        "media_type": resolve_media_type(payload),
        "media_path": media_url,
        "media_available": media_available,
        # A canonical category from the source is trusted as-is; anything else is
        # left empty so `classify_post_category` derives it from the title instead
        # of the pipeline treating a foreign label as a keyword match.
        "category_l1": reconcile_category(payload, CANONICAL_CATEGORIES),
        "category_l2": _optional_text(get_field(payload, "subcategory")),
        "concept": None,
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


def reconcile_category(payload: dict, canonical_categories: Iterable[str]) -> str | None:
    """Returns the payload category when EnSosyal already speaks the canonical names.

    The pipeline classifies categories from the title when they are absent; this
    helper exists so a source that *does* send canonical categories can be trusted
    instead of re-derived.
    """
    raw = _optional_text(get_field(payload, "category"))
    if raw is None:
        return None
    normalized = raw.strip().lower().replace(" ", "_").replace("-", "_")
    return normalized if normalized in set(canonical_categories) else None


def ingest_payloads(
    payloads: Iterable[dict],
    *,
    config: EnSosyalAdapterConfig | None = None,
    ingested_at_utc: datetime | None = None,
    skip_log: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """Converts a batch of payloads into a canonical, contract-checked frame.

    The frame has exactly the pipeline columns and passes the same gates the SMPD
    path uses, so both sources are interchangeable downstream. Duplicate post ids
    are dropped (keeping the first) rather than failing the batch — an export that
    overlaps two windows is normal.

    `frame.attrs` carries the ingest audit: skipped counts by reason, the timezone
    basis distribution and the personal fields that arrived and were dropped.
    """
    config = config or EnSosyalAdapterConfig()
    ingested_at_utc = ingested_at_utc or datetime.now(timezone.utc)
    rows: list[dict] = []
    skipped_by_reason: dict[str, int] = {}
    dropped_personal: dict[str, int] = {}

    for payload in payloads:
        for path in AUDITED_PERSONAL_PATHS:
            if has_path(payload, path):
                dropped_personal[path] = dropped_personal.get(path, 0) + 1

        reason = skip_reason(payload, config)
        if reason is not None:
            skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
            if skip_log is not None:
                skip_log(f"skipped payload ({reason}): id={get_field(payload, 'post_id')!r}")
            continue

        row = to_post_record(payload, config=config, ingested_at_utc=ingested_at_utc)
        if row is None:
            skipped_by_reason["no_engagement"] = skipped_by_reason.get("no_engagement", 0) + 1
            continue
        rows.append(row)

    if rows:
        frame = pd.DataFrame(rows, columns=INGESTED_COLUMNS)
        frame = frame.drop_duplicates(subset=["post_id"], keep="first").reset_index(drop=True)
        frame = add_leakage_free_priors(frame)
    else:
        frame = pd.DataFrame(columns=OUTPUT_COLUMNS)
    assert_column_contract(list(frame.columns))
    if not frame.empty:
        validate_against_schema(frame)

    frame.attrs["skipped_payloads"] = sum(skipped_by_reason.values())
    frame.attrs["skipped_by_reason"] = skipped_by_reason
    frame.attrs["dropped_personal_fields"] = dropped_personal
    frame.attrs["timezone_basis_counts"] = (
        frame["timezone_basis"].value_counts().to_dict() if not frame.empty else {}
    )
    return frame


class EnSosyalClient:
    """Authorised transport for pulling posts from an EnSosyal-provided endpoint.

    Deliberately minimal: bearer token, one documented path, bounded pages. It does
    not authenticate as a user, hold cookies, or discover endpoints — those are the
    data controller's responsibility under the processing agreement.
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
        self.last_total: int | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def fetch_posts(self, *, since: str | None = None, until: str | None = None, limit: int = 500) -> list[dict]:
        """Pulls one page of posts and unwraps the feed envelope.

        Pagination is the caller's loop, on purpose: the adapter never walks a
        corpus on its own.
        """
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

        posts, self.last_total = unwrap_envelope(body)
        return posts


__all__ = [
    "AUDITED_PERSONAL_PATHS",
    "DEFAULT_ALLOWED_VISIBILITY",
    "EnSosyalAdapterConfig",
    "EnSosyalClient",
    "EnSosyalResponseError",
    "EnSosyalTransportNotConfigured",
    "EngagementWeights",
    "FIELD_CANDIDATES",
    "SKIP_REASONS",
    "declared_offset",
    "engagement_counters",
    "extract_offset_from_timestamp",
    "get_field",
    "has_path",
    "ingest_payloads",
    "normalize_media_type",
    "normalize_tags",
    "pseudonymize_user_id",
    "reconcile_category",
    "resolve_media_type",
    "scrub_text",
    "skip_reason",
    "to_post_record",
    "unwrap_envelope",
]
