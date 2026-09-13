"""EnSosyal ingestion adapter: field mapping, KVKK filter, feed envelope, transport.

The fixtures are synthetic and shaped exactly like the contract EnSosyal shared
(`nsosyal_features.json.shema`); no real EnSosyal user data is in this repository.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

import httpx
import pytest

from backend.adapters.ensosyal import (
    EnSosyalAdapterConfig,
    EnSosyalClient,
    EnSosyalResponseError,
    EnSosyalTransportNotConfigured,
    EngagementWeights,
    declared_offset,
    engagement_counters,
    extract_offset_from_timestamp,
    get_field,
    ingest_payloads,
    normalize_media_type,
    normalize_tags,
    pseudonymize_user_id,
    resolve_media_type,
    scrub_text,
    skip_reason,
    to_post_record,
    unwrap_envelope,
)
from backend.services.canonical_taxonomy import CANONICAL_CATEGORIES
from backend.services.post_contract import (
    DERIVED_PRIOR_COLUMNS,
    ENSOSYAL_SOURCE_ID,
    INGESTED_COLUMNS,
    OUTPUT_COLUMNS,
)
from backend.services.recommendation import RecommendationService

FIXTURES = Path(__file__).parent / "fixtures" / "ensosyal"
FEED_FIXTURE = FIXTURES / "explore_feed_sample.json"
CONTRACT_SCHEMA = Path(__file__).resolve().parents[1] / "nsosyal_features.json.shema"
SALT = "test-salt-not-a-secret"


@pytest.fixture(scope="module")
def feed() -> dict:
    return json.loads(FEED_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def posts(feed) -> list[dict]:
    return feed["data"]["items"]


@pytest.fixture
def config() -> EnSosyalAdapterConfig:
    return EnSosyalAdapterConfig(salt=SALT)


def _record(payload: dict, config: EnSosyalAdapterConfig) -> dict:
    row = to_post_record(payload, config=config)
    assert row is not None, f"payload unexpectedly skipped: {skip_reason(payload, config)}"
    return row


# --- the shared contract -----------------------------------------------------
def test_fixture_matches_the_published_json_schema(posts):
    """The fixture must satisfy EnSosyal's own schema, so the adapter is tested
    against their contract and not against an invented one."""
    try:
        import jsonschema
    except ImportError:
        jsonschema = None

    if jsonschema is not None:
        schema = json.loads(CONTRACT_SCHEMA.read_text(encoding="utf-8"))
        jsonschema.validate(instance=json.loads(FEED_FIXTURE.read_text(encoding="utf-8")), schema=schema)
        return

    # Without jsonschema, assert the structural parts of the contract by hand.
    schema = json.loads(CONTRACT_SCHEMA.read_text(encoding="utf-8"))
    post_required = set(schema["$defs"]["Post"]["required"])
    media_enum = set(
        schema["$defs"]["MediaAttachment"]["properties"]["type"]["enum"]
    )
    visibility_enum = set(schema["$defs"]["Post"]["properties"]["visibility"]["enum"])
    for post in posts:
        missing = post_required - set(post)
        assert not missing, f"fixture post {post['id']} missing required keys: {sorted(missing)}"
        assert post["visibility"] in visibility_enum
        for attachment in post["media_attachments"]:
            assert attachment["type"] in media_enum
        for key in ("reblogs_count", "favourites_count", "replies_count", "views_count"):
            assert isinstance(post[key], int) and post[key] >= 0
        datetime.fromisoformat(post["created_at"].replace("Z", "+00:00"))


# --- envelope ----------------------------------------------------------------
def test_envelope_unwrapping(feed, posts):
    items, total = unwrap_envelope(feed)
    assert [item["id"] for item in items] == [post["id"] for post in posts]
    assert total == 5

    assert unwrap_envelope([{"id": "x"}]) == ([{"id": "x"}], None)
    assert unwrap_envelope({"data": [{"id": "x"}]})[0] == [{"id": "x"}]
    assert unwrap_envelope({"items": [{"id": "x"}], "total": 1}) == ([{"id": "x"}], 1)


def test_envelope_reports_platform_failures():
    with pytest.raises(EnSosyalResponseError, match="failure"):
        unwrap_envelope({"success": False, "message": "rate limited", "data": {}})
    with pytest.raises(EnSosyalResponseError):
        unwrap_envelope("not an envelope")


# --- field mapping -----------------------------------------------------------
def test_first_post_maps_onto_the_canonical_row(posts, config):
    row = _record(posts[0], config)

    assert row["source"] == ENSOSYAL_SOURCE_ID
    assert row["post_id"] == "5550001"
    assert set(row) == set(INGESTED_COLUMNS)
    assert set(DERIVED_PRIOR_COLUMNS).isdisjoint(row)

    # 21:30 +03:00 on 2026-09-12 (a Saturday) stays 21:30 local.
    assert row["local_hour"] == 21
    assert row["local_weekday"] == 5
    assert row["timezone_offset"] == "+03:00"
    assert row["timezone_basis"] == "source_offset"
    assert row["published_at_utc"] == datetime(2026, 9, 12, 18, 30, tzinfo=timezone.utc)

    assert row["title"] == "Sabah kahvesi ve kitap keyfi #kahve #kitap"
    assert row["tags"] == ["#kahve", "#kitap"]
    assert row["media_type"] == "photo"
    assert row["media_path"] == "https://cdn.example.invalid/media/1.jpg"
    assert row["media_available"] is False  # URLs are not fetched
    # Reach target: log1p(views_count), i.e. 15,200 views
    assert row["popularity_score"] == pytest.approx(round(math.log1p(15200), 4))


def test_timestamp_without_offset_is_honestly_a_fallback(posts, config):
    """A `Z` timestamp gives no local time, and the row says so."""
    row = _record(posts[1], config)

    assert row["timezone_basis"] == "utc_fallback"
    assert row["timezone_offset"] is None
    assert row["local_hour"] == 5  # equals UTC: no conversion was invented
    assert row["published_at_utc"] == datetime(2026, 9, 12, 5, 15, tzinfo=timezone.utc)
    # HTML in the text must not reach the title SVD vocabulary
    assert "<p>" not in row["title"]
    assert row["title"] == "Derin öğrenme ile görüntü işleme notları uzun bir yazı"


def test_offset_resolution_prefers_field_then_timestamp():
    assert extract_offset_from_timestamp("2026-09-12T21:30:00+03:00") == "+03:00"
    assert extract_offset_from_timestamp("2026-09-12T21:30:00+0300") == "+03:00"
    assert extract_offset_from_timestamp("2026-09-12T21:30:00-05:00") == "-05:00"
    assert extract_offset_from_timestamp("2026-09-12T18:30:00Z") is None
    assert extract_offset_from_timestamp("2026-09-12T18:30:00") is None

    # An explicit field wins; an IANA name is resolved at the post's own instant.
    assert declared_offset({"timezone_offset": "-02:00"}, "2026-09-12T18:30:00Z") == "-02:00"
    assert declared_offset({"timezone": "Europe/Istanbul"}, "2026-09-12T18:30:00Z") == "+03:00"
    assert declared_offset({}, "2026-09-12T18:30:00Z") is None


def test_media_type_resolution(posts, config):
    assert resolve_media_type(posts[0]) == "photo"  # image attachment
    assert resolve_media_type(posts[1]) == "video"  # video attachment wins
    assert resolve_media_type(posts[4]) == "unknown"  # audio is not a photo
    assert normalize_media_type("gifv") == "video"
    assert normalize_media_type("story") == "unknown"

    assert _record(posts[4], config)["media_type"] == "unknown"


def test_tags_and_text_helpers():
    assert normalize_tags([{"name": "kahve"}, {"name": "Kahve"}, {"tag": "kitap"}]) == ["#kahve", "#kitap"]
    assert normalize_tags("kahve, kitap") == ["#kahve", "#kitap"]
    assert normalize_tags(None) == []

    assert scrub_text("selam a@b.com +90 555 123 45 67") == "selam"
    assert scrub_text("<p>merhaba</p> <a href='x'>dünya</a>") == "merhaba dünya"
    assert scrub_text("&amp; &quot;tırnak&quot;") == '& "tırnak"'


def test_scrubbing_preserves_dates_and_quantities():
    """A news corpus is full of dates and amounts; they are content, not PII.

    The naive "digits with separators" rule deleted every one of these, which
    would silently shred legitimate text before it reaches the title SVD.
    """
    keep = [
        "12.09.2026", "2026-09-13", "1 000 000", "12.500", "2026",
        "Borsa 12.09.2026 tarihinde 1 000 000 puanı geçti",
    ]
    for probe in keep:
        assert scrub_text(probe) == probe, f"legitimate content was scrubbed: {probe!r}"

    # Real phone numbers still go away, in the shapes a Turkish corpus carries.
    strip = [
        "0555 123 45 67",
        "+90 555 123 45 67",
        "0 (555) 123 45 67",
        "ara beni 05321234567",
    ]
    for probe in strip:
        scrubbed = scrub_text(probe)
        assert "555" not in scrubbed and "05321234567" not in scrubbed, f"phone survived: {probe!r}"


def test_media_only_post_keeps_an_empty_title(posts, config):
    row = _record(posts[4], config)
    assert row["title"] == ""
    assert row["tags"] == []


# --- target definition -------------------------------------------------------
def test_views_count_is_the_target_and_page_views_are_ignored(posts, config):
    views, interactions = engagement_counters(posts[0])
    assert views == 15200  # not detail_views_count (2100) or profile_views_count (130)
    assert interactions["share"] == 12 + 3  # reblogs + quotes
    assert interactions["like"] == 340
    assert interactions["comment"] == 28
    assert interactions["save"] == 44

    assert _record(posts[0], config)["popularity_score"] == pytest.approx(round(math.log1p(15200), 4))


def test_target_falls_back_to_weighted_interactions(posts, config):
    """views_count == 0 on the media-only post: the counters carry the target."""
    row = _record(posts[4], config)
    weighted = EngagementWeights().weighted_interactions({"like": 9, "save": 1, "share": 0, "comment": 0})
    assert row["popularity_score"] == pytest.approx(round(math.log1p(weighted), 4))


def test_payload_without_any_engagement_is_skipped(posts, config):
    silent = {**posts[0], "id": "5559999", "views_count": 0, "shares_count": 0, "reblogs_count": 0,
              "favourites_count": 0, "replies_count": 0, "quote_count": 0, "bookmarks_count": 0}
    assert skip_reason(silent, config) == "no_engagement"
    assert to_post_record(silent, config=config) is None


# --- distribution policy -----------------------------------------------------
def test_private_posts_are_filtered_and_counted(posts, config):
    assert skip_reason(posts[2], config) == "visibility_filtered"

    frame = ingest_payloads(posts, config=config)
    assert "5550003" not in frame["post_id"].tolist()
    assert frame.attrs["skipped_by_reason"]["visibility_filtered"] == 1

    # Opting in is possible but explicit.
    permissive = EnSosyalAdapterConfig(salt=SALT, allowed_visibility=frozenset({"public", "unlisted", "private"}))
    assert skip_reason(posts[2], permissive) is None


def test_sensitive_posts_are_filtered_unless_opted_in(posts, config):
    assert skip_reason(posts[3], config) == "sensitive_filtered"

    frame = ingest_payloads(posts, config=config)
    assert "5550004" not in frame["post_id"].tolist()

    permissive = EnSosyalAdapterConfig(salt=SALT, include_sensitive=True)
    assert skip_reason(posts[3], permissive) is None


def test_missing_author_or_timestamp_is_a_contract_bug_not_a_policy_skip(posts, config):
    no_author = {key: value for key, value in posts[0].items() if key != "account"}
    assert skip_reason(no_author, config) == "no_author"

    no_timestamp = {key: value for key, value in posts[0].items() if key != "created_at"}
    assert skip_reason(no_timestamp, config) == "no_timestamp"

    no_id = {key: value for key, value in posts[0].items() if key != "id"}
    assert skip_reason(no_id, config) == "no_id"


# --- KVKK filter -------------------------------------------------------------
def test_user_ids_are_pseudonymised_with_a_stable_salt(posts, config):
    first = _record(posts[0], config)
    again = _record(posts[0], config)
    other = _record(posts[1], config)

    assert first["user_id"] == again["user_id"]
    assert first["user_id"] != other["user_id"]
    assert first["user_id"].startswith("ensy_")
    assert "900001" not in first["user_id"]

    assert _record(posts[0], EnSosyalAdapterConfig(salt="another"))["user_id"] != first["user_id"]
    assert _record(posts[0], EnSosyalAdapterConfig(salt=SALT, pseudonymize_users=False))["user_id"] == "900001"


def test_missing_salt_refuses_to_pseudonymise(posts):
    with pytest.raises(EnSosyalTransportNotConfigured, match="PSEUDONYM_SALT"):
        to_post_record(posts[0], config=EnSosyalAdapterConfig(salt=None))


def test_account_and_post_personal_data_never_reach_the_row(posts, config):
    row = _record(posts[0], config)
    raw = json.dumps(row, ensure_ascii=False, default=str)

    for leaked in ("kahve_kutusu", "Kahve Kutusu", "kahve@example.invalid", "Kadıköy",
                   "kitapkurdu", "cdn.example.invalid/a/900001.jpg", "@kahveci"):
        assert leaked not in raw, f"personal data leaked into the row: {leaked}"


def test_ingest_audit_reports_what_was_dropped(posts, config):
    frame = ingest_payloads(posts, config=config)
    dropped = frame.attrs["dropped_personal_fields"]

    assert dropped["account.username"] == 5
    assert dropped["account.display_name"] == 5
    assert dropped["account.bio"] == 1
    assert dropped["account.fields"] == 1
    assert dropped["mentions"] == 1
    assert dropped["spoiler_text"] == 1


def test_location_is_dropped_unless_explicitly_opted_in(posts, config):
    with_location = {**posts[0], "location": {"latitude": 40.99, "longitude": 29.02}}
    assert _record(with_location, config)["latitude"] is None

    permissive = EnSosyalAdapterConfig(salt=SALT, drop_personal_fields=False)
    row = _record(with_location, permissive)
    assert row["latitude"] == pytest.approx(40.99)
    assert row["longitude"] == pytest.approx(29.02)


# --- batches -----------------------------------------------------------------
def test_batch_is_contract_checked_and_auditable(posts, config):
    frame = ingest_payloads(posts, config=config, ingested_at_utc=datetime.now(timezone.utc))

    assert list(frame.columns) == OUTPUT_COLUMNS
    # 5 items: 1 private + 1 sensitive skipped, the other 3 survive. The frame is
    # re-sorted chronologically per user when the priors are computed.
    assert sorted(frame["post_id"]) == ["5550001", "5550002", "5550005"]
    assert frame["source"].unique().tolist() == [ENSOSYAL_SOURCE_ID]
    assert frame.attrs["skipped_payloads"] == 2
    assert frame.attrs["timezone_basis_counts"] == {"source_offset": 2, "utc_fallback": 1}

    # Duplicated ids are deduplicated instead of failing the batch.
    assert len(ingest_payloads(posts + [posts[0]], config=config)) == len(frame)


def test_priors_are_chronological_and_leakage_free(posts, config):
    """A second post by the same author sees exactly one prior post."""
    later = {**posts[0], "id": "5550006", "created_at": "2026-09-13T21:30:00+03:00", "views_count": 800}
    frame = ingest_payloads([posts[0], later], config=config).sort_values("published_at_utc")

    assert frame["user_post_count_prior"].tolist() == [0, 1]
    assert frame["user_popularity_mean_prior"].iloc[1] == pytest.approx(
        frame["popularity_score"].iloc[0], abs=1e-3
    )


def test_ingested_batch_survives_the_feature_pipeline(posts, config):
    """The adapter's output must be usable by Layer A without special cases."""
    frame = ingest_payloads(posts, config=config)

    service = RecommendationService(
        model_path=Path("artifacts/.training-placeholder.txt"),
        time_lift_path=Path("artifacts/.training-placeholder.json"),
        metrics_path=Path("artifacts/.training-placeholder.metrics.json"),
    )
    X = service._prepare_features(frame)

    assert X.shape[0] == len(frame)
    assert "hour" not in X.columns and "account_baseline" not in X.columns
    assert X["timezone_basis_fallback"].sum() == 1  # the Z-timestamp post


def test_non_canonical_category_is_left_for_the_classifier(posts, config):
    """EnSosyal labels that are not canonical must not be smuggled in."""
    row = _record({**posts[0], "category": "kahve_kultur"}, config)
    assert row["category_l1"] is None
    assert "kahve_kultur" not in CANONICAL_CATEGORIES

    canonical = _record({**posts[0], "category": "food_dining"}, config)
    assert canonical["category_l1"] == "food_dining"


def test_tolerant_spellings_still_map(config):
    """A thinner/differently named payload maps through the candidate table."""
    payload = {
        "id": "alt-1",
        "author_id": "alt-user",
        "caption": "alternatif alan adları",
        "createdAt": "2026-09-12T18:30:00+03:00",
        "hashtags": ["deneme"],
        "media_type": "image",
        "view_count": 100,
        "like_count": 10,
    }
    row = _record(payload, config)

    assert row["post_id"] == "alt-1"
    assert row["title"] == "alternatif alan adları"
    assert row["tags"] == ["#deneme"]
    assert row["media_type"] == "photo"
    # The timestamp already carries +03:00, so 18:30 *is* the local time.
    assert row["local_hour"] == 18
    assert row["timezone_basis"] == "source_offset"
    assert row["popularity_score"] == pytest.approx(round(math.log1p(100), 4))

    assert get_field(payload, "likes") == 10


# --- transport ---------------------------------------------------------------
def test_transport_refuses_to_run_without_authorised_credentials(monkeypatch):
    monkeypatch.delenv("ENSOSYAL_API_TOKEN", raising=False)
    monkeypatch.delenv("ENSOSYAL_API_BASE_URL", raising=False)
    client = EnSosyalClient()

    assert not client.is_configured
    with pytest.raises(EnSosyalTransportNotConfigured, match="not configured"):
        client.fetch_posts()


def test_transport_unwraps_the_feed_envelope(feed):
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=feed)

    client = EnSosyalClient(
        base_url="https://ensosyal.example/api",
        token="issued-token",
        posts_path="/v1/discover/posts",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    items = client.fetch_posts(since="2026-09-01", limit=20)

    assert [item["id"] for item in items] == ["5550001", "5550002", "5550003", "5550004", "5550005"]
    assert client.last_total == 5
    assert seen["auth"] == "Bearer issued-token"
    assert "/v1/discover/posts" in str(seen["url"])
    assert "limit=20" in str(seen["url"])


def test_pseudonym_helper_is_deterministic_and_salted():
    assert pseudonymize_user_id("u1", "a") == pseudonymize_user_id("u1", "a")
    assert pseudonymize_user_id("u1", "a") != pseudonymize_user_id("u1", "b")
    assert pseudonymize_user_id("u1", "a") != pseudonymize_user_id("u2", "a")


def test_declared_offset_survives_a_dst_boundary():
    """An IANA name is resolved at the post's instant, not at import time."""
    winter = declared_offset({"timezone": "Europe/Berlin"}, "2026-01-15T12:00:00Z")
    summer = declared_offset({"timezone": "Europe/Berlin"}, "2026-07-15T12:00:00Z")

    assert winter == "+01:00"
    assert summer == "+02:00"
