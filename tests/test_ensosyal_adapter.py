"""EnSosyal ingestion adapter: field mapping, KVKK filter and transport rules.

The fixtures are synthetic (tests/fixtures/ensosyal/posts_sample.json); no real
EnSosyal user data appears anywhere in this repository.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import httpx
import pytest

from backend.adapters.ensosyal import (
    EnSosyalAdapterConfig,
    EnSosyalClient,
    EnSosyalTransportNotConfigured,
    EngagementWeights,
    ingest_payloads,
    normalize_media_type,
    normalize_tags,
    pseudonymize_user_id,
    scrub_text,
    to_post_record,
)
from backend.services.canonical_taxonomy import CANONICAL_CATEGORIES
from backend.services.post_contract import (
    DERIVED_PRIOR_COLUMNS,
    ENSOSYAL_SOURCE_ID,
    INGESTED_COLUMNS,
    OUTPUT_COLUMNS,
)
from backend.services.recommendation import RecommendationService

FIXTURE = Path(__file__).parent / "fixtures" / "ensosyal" / "posts_sample.json"
SALT = "test-salt-not-a-secret"


@pytest.fixture(scope="module")
def payloads() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"]


@pytest.fixture
def config() -> EnSosyalAdapterConfig:
    return EnSosyalAdapterConfig(salt=SALT)


def _record(payload: dict, config: EnSosyalAdapterConfig) -> dict:
    row = to_post_record(payload, config=config)
    assert row is not None
    return row


def test_full_payload_maps_onto_the_canonical_row(payloads, config):
    row = _record(payloads[0], config)

    assert row["source"] == ENSOSYAL_SOURCE_ID
    assert row["post_id"] == "ens-1001"
    # Source-derived columns only: the per-user priors are batch-level.
    assert set(row) == set(INGESTED_COLUMNS)
    assert set(DERIVED_PRIOR_COLUMNS).isdisjoint(row)
    # 18:30 UTC with +03:00 is 21:30 local on a Saturday
    assert row["local_hour"] == 21
    assert row["local_weekday"] == 5
    assert row["timezone_basis"] == "source_offset"
    assert row["media_type"] == "photo"
    assert row["category_l1"] == "food_dining"
    assert row["popularity_score"] == pytest.approx(8.3431, abs=1e-4)  # log1p(4200)


def test_timezone_contract_matches_the_smpd_path(payloads, config):
    """A tz-aware timestamp plus an offset must resolve like the SMPD corpus."""
    row = _record(payloads[1], config)

    assert row["published_at_utc"] == datetime(2026, 9, 12, 5, 15, tzinfo=timezone.utc)
    assert row["local_hour"] == 7  # 05:15 UTC + 02:00
    assert row["timezone_basis"] == "source_offset"
    assert row["category_l1"] == "technology"

    # Without an offset the row is still usable, but labelled as a fallback.
    without_offset = _record({k: v for k, v in payloads[1].items() if k != "utc_offset"}, config)
    assert without_offset["timezone_basis"] == "utc_fallback"
    assert without_offset["local_hour"] == 5


def test_tags_are_normalized_and_deduplicated(payloads, config):
    row = _record(payloads[0], config)
    # "kahve" and "#kitap" and "Kahve": lowercased, hash-prefixed, deduplicated.
    assert row["tags"] == ["#kahve", "#kitap"]

    assert normalize_tags("yapayzeka, derinogrenme,python") == ["#yapayzeka", "#derinogrenme", "#python"]
    assert normalize_tags({"kahve": 3, "kitap": 1}) == ["#kahve", "#kitap"]
    assert normalize_tags(None) == []


def test_unknown_media_type_is_not_treated_as_photo(payloads, config):
    row = _record(payloads[2], config)
    assert row["media_type"] == "unknown"
    assert normalize_media_type("story") == "unknown"
    assert normalize_media_type("REEL") == "video"


def test_non_canonical_category_is_left_for_the_classifier(payloads, config):
    """A platform label like 'music' must not be smuggled in as a canonical one."""
    row = _record(payloads[2], config)
    assert row["category_l1"] is None
    assert "music" not in CANONICAL_CATEGORIES


def test_engagement_target_falls_back_and_refuses_empty_rows(payloads, config):
    # No views: log1p of the weighted interactions (44 likes)
    row = _record(payloads[2], config)
    assert row["popularity_score"] == pytest.approx(3.8067, abs=1e-3)

    # Neither views nor interactions: no target, so the payload is not a row.
    assert to_post_record(payloads[3], config=config) is None
    assert EngagementWeights().score(None, {}) is None


def test_user_ids_are_pseudonymised_with_a_stable_salt(payloads, config):
    row_a = _record(payloads[0], config)
    row_a2 = _record(payloads[0], config)
    row_b = _record(payloads[1], config)

    assert row_a["user_id"] == row_a2["user_id"]  # stable across runs
    assert row_a["user_id"] != row_b["user_id"]
    assert row_a["user_id"].startswith("ensy_")
    assert "u-77" not in row_a["user_id"]

    other_salt = EnSosyalAdapterConfig(salt="another-salt")
    assert _record(payloads[0], other_salt)["user_id"] != row_a["user_id"]

    # Opting out keeps the raw id and is an explicit, documented decision.
    raw = _record(payloads[0], EnSosyalAdapterConfig(salt=SALT, pseudonymize_users=False))
    assert raw["user_id"] == "u-77"


def test_missing_salt_refuses_to_pseudonymise(payloads):
    with pytest.raises(EnSosyalTransportNotConfigured, match="PSEUDONYM_SALT"):
        to_post_record(payloads[0], config=EnSosyalAdapterConfig(salt=None))


def test_free_text_is_scrubbed_of_contact_details(payloads, config):
    row = _record(payloads[0], config)
    assert "http" not in row["title"]
    assert "@kahveci" not in row["title"]
    assert row["title"].startswith("Sabah kahve")

    assert scrub_text("yaz bana a@b.com veya +90 555 123 45 67") == "yaz bana veya"
    assert scrub_text("https://x.invalid/a foto") == "foto"


def test_personal_and_location_fields_never_reach_the_row(payloads, config):
    row = _record(payloads[0], config)
    assert row["latitude"] is None and row["longitude"] is None
    assert "profile_text" not in row and "location" not in row

    # With the opt-in flag the coarse coordinates survive; the free text does not,
    # because it is not part of the canonical contract at all.
    permissive = EnSosyalAdapterConfig(salt=SALT, drop_personal_fields=False)
    with_geo = _record({**payloads[0], "latitude": 40.99, "longitude": 29.02}, permissive)
    assert with_geo["latitude"] == pytest.approx(40.99)


def test_batch_ingest_is_contract_checked_and_auditable(payloads, config):
    frame = ingest_payloads(payloads, config=config, ingested_at_utc=datetime.now(timezone.utc))

    assert list(frame.columns) == OUTPUT_COLUMNS
    assert len(frame) == 3  # the payload without any engagement signal is dropped
    assert frame["source"].unique().tolist() == [ENSOSYAL_SOURCE_ID]
    assert frame.attrs["skipped_payloads"] == 1
    assert frame.attrs["dropped_personal_fields"] == {"profile_text": 1, "location": 1}

    # Duplicated ids are deduplicated instead of failing the batch.
    deduped = ingest_payloads(payloads + [payloads[0]], config=config)
    assert len(deduped) == len(frame)

    # The priors are real, chronological and leakage-free: a second post by the
    # same author sees exactly one prior post, the first one does not.
    repeat = {**payloads[0], "post_id": "ens-1001-b", "created_at": "2026-09-13T18:30:00Z", "views": 800}
    two_posts = ingest_payloads([payloads[0], repeat], config=config).sort_values("published_at_utc")
    assert two_posts["user_post_count_prior"].tolist() == [0, 1]
    # The prior mean is the first post's score (rounded to 3 decimals by the
    # shared history helper, hence the tolerance).
    assert two_posts["user_popularity_mean_prior"].iloc[1] == pytest.approx(
        two_posts["popularity_score"].iloc[0], abs=1e-3
    )


def test_ingested_batch_survives_the_feature_pipeline(payloads, config):
    """The adapter's output must be usable by Layer A without special cases."""
    frame = ingest_payloads(payloads, config=config)
    frame = frame.assign(user_post_count_prior=0, user_popularity_mean_prior=0.0)

    service = RecommendationService(
        model_path=Path("artifacts/.training-placeholder.txt"),
        time_lift_path=Path("artifacts/.training-placeholder.json"),
        metrics_path=Path("artifacts/.training-placeholder.metrics.json"),
    )
    X = service._prepare_features(frame)

    assert X.shape[0] == len(frame)
    assert "hour" not in X.columns and "account_baseline" not in X.columns


def test_transport_refuses_to_run_without_authorised_credentials(monkeypatch):
    monkeypatch.delenv("ENSOSYAL_API_TOKEN", raising=False)
    monkeypatch.delenv("ENSOSYAL_API_BASE_URL", raising=False)
    client = EnSosyalClient()

    assert not client.is_configured
    with pytest.raises(EnSosyalTransportNotConfigured, match="not configured"):
        client.fetch_posts()


def test_transport_uses_the_provided_token_and_unwraps_the_envelope():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": [{"id": "ens-1"}]})

    client = EnSosyalClient(
        base_url="https://ensosyal.example/api",
        token="issued-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    posts = client.fetch_posts(since="2026-09-01", limit=10)

    assert posts == [{"id": "ens-1"}]
    assert seen["auth"] == "Bearer issued-token"
    assert "/api/v1/posts" in str(seen["url"])
    assert "limit=10" in str(seen["url"])


def test_pseudonym_helper_is_deterministic_and_salted():
    assert pseudonymize_user_id("u1", "a") == pseudonymize_user_id("u1", "a")
    assert pseudonymize_user_id("u1", "a") != pseudonymize_user_id("u1", "b")
    assert pseudonymize_user_id("u1", "a") != pseudonymize_user_id("u2", "a")
