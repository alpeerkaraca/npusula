"""Unit tests verifying strict Pydantic v2 validation behavior."""
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from backend.schemas import (
    AdvisorRequest,
    CandidateSlot,
    MediaTypeEnum,
    PostRecord,
    ProfileDecisionRequest,
    TopicWeight,
)


def test_post_record_valid():
    post = PostRecord(
        post_id="post_123",
        user_id="user_456",
        published_at_utc=datetime.now(timezone.utc),
        title="Testing EnPusula MVP",
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
            title="Testing EnPusula MVP",
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
            title="Testing EnPusula MVP",
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
        user_id="demo_user_01",
        idea="Bugün yapay zeka ile ilgili bir gönderi paylaşıyoruz",
        media_type=MediaTypeEnum.VIDEO,
    )
    assert req.user_id == "demo_user_01"
    assert req.media_type == MediaTypeEnum.VIDEO

    # Reject string coercion for enum or invalid length
    with pytest.raises(ValidationError):
        AdvisorRequest(
            user_id="demo_user_01",
            idea="",  # Empty string rejected by min_length=1
        )
