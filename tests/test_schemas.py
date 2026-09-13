"""Unit tests verifying strict Pydantic v2 validation behavior."""
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from backend.schemas import (
    AdvisorRequest,
    MediaTypeEnum,
    PostRecord,
    ProfileDecisionRequest,
    RecommendedWindow,
    TopicWeight,
)


def test_post_record_valid():
    post = PostRecord(
        post_id="post_123",
        user_id="user_456",
        published_at_utc=datetime.now(timezone.utc),
        title="Testing NPusula MVP",
        tags=["ai", "ml", "ensocial"],
        media_type=MediaTypeEnum.PHOTO,
        popularity_score=6.25,
    )
    assert post.post_id == "post_123"
    assert post.popularity_score == 6.25
    assert post.media_type == MediaTypeEnum.PHOTO


def test_post_record_rejects_string_for_float():
    """Strict mode MUST reject string coercion for float fields."""
    with pytest.raises(ValidationError) as exc_info:
        PostRecord(
            post_id="post_123",
            user_id="user_456",
            published_at_utc=datetime.now(timezone.utc),
            title="Testing NPusula MVP",
            tags=["ai"],
            popularity_score="6.25",  # String instead of float!
        )
    assert "popularity_score" in str(exc_info.value)


def test_post_record_rejects_extra_fields():
    """Strict mode MUST reject unexpected fields."""
    with pytest.raises(ValidationError) as exc_info:
        PostRecord(
            post_id="post_123",
            user_id="user_456",
            published_at_utc=datetime.now(timezone.utc),
            title="Testing NPusula MVP",
            tags=["ai"],
            unexpected_field="disallowed",
        )
    assert "unexpected_field" in str(exc_info.value)


def test_topic_weight_bounds():
    valid = TopicWeight(topic="Yapay Zeka", weight=0.85)
    assert valid.weight == 0.85

    with pytest.raises(ValidationError):
        TopicWeight(topic="Yapay Zeka", weight=1.5)

    with pytest.raises(ValidationError):
        TopicWeight(topic="Yapay Zeka", weight=-0.2)


def test_advisor_request_strict_validation():
    req = AdvisorRequest(
        user_id="test_user",
        idea="Bugün yapay zeka ile ilgili bir gönderi paylaşıyoruz",
        media_type=MediaTypeEnum.VIDEO,
    )
    assert req.user_id == "test_user"
    assert req.media_type == MediaTypeEnum.VIDEO
    assert req.timezone is None
    assert req.utc_offset_minutes is None

    # Reject string coercion for enum or invalid length
    with pytest.raises(ValidationError):
        AdvisorRequest(
            user_id="test_user",
            idea="",  # Empty string rejected by min_length=1
        )


def test_advisor_request_accepts_a_timezone_or_an_offset():
    by_name = AdvisorRequest(user_id="u", idea="fikir", timezone="Europe/Istanbul")
    assert by_name.timezone == "Europe/Istanbul"

    by_offset = AdvisorRequest(user_id="u", idea="fikir", utc_offset_minutes=180)
    assert by_offset.utc_offset_minutes == 180

    with pytest.raises(ValidationError):
        AdvisorRequest(user_id="u", idea="fikir", utc_offset_minutes=2000)  # beyond ±14h


def test_post_record_carries_the_timezone_contract():
    post = PostRecord(
        post_id="p1",
        user_id="u1",
        published_at_utc=datetime.now(timezone.utc),
        title="Başlık",
        timezone_offset="+03:00",
        timezone_id="Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna",
        local_datetime=datetime(2026, 9, 13, 21, 0),
        local_hour=21,
        local_weekday=6,
        timezone_basis="source_offset",
        source_user_photo_count=1429,
    )
    assert post.timezone_basis == "source_offset"
    assert post.local_hour == 21
    assert post.source_user_photo_count == 1429

    # Unknown basis values are rejected rather than defaulted silently.
    with pytest.raises(ValidationError):
        PostRecord(
            post_id="p1",
            user_id="u1",
            published_at_utc=datetime.now(timezone.utc),
            title="Başlık",
            timezone_basis="guessed",
        )


def test_recommended_window_is_timezone_explicit():
    """The window contract: local times, evidence and no invented rank."""
    now = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)
    window = RecommendedWindow(
        window_start_local=now,
        window_end_local=now,
        window_start_utc=now,
        window_end_utc=now,
        weekday="Salı",
        weekday_index=1,
        bucket=6,
        time_range_local="18.00–21.00",
        base_potential=7.1,
        observational_time_lift=0.12,
        confidence="medium",
        support_post_count=1240,
        evidence_level="category_weekday_bucket",
        is_tie_or_broad_window=False,
        timezone_basis="user_timezone",
    )
    assert window.confidence_label == "Düşük"  # default display label, overridden by the service
    assert window.relative_potential == 0.0
    assert window.evidence_level == "category_weekday_bucket"

    with pytest.raises(ValidationError):
        RecommendedWindow(
            window_start_local=now,
            window_end_local=now,
            window_start_utc=now,
            window_end_utc=now,
            weekday="Salı",
            weekday_index=9,  # out of range
            bucket=6,
            time_range_local="18.00–21.00",
            base_potential=7.1,
            observational_time_lift=0.12,
        )
