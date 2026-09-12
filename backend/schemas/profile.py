"""Profile and drift schemas adhering to strict Pydantic rules."""
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator

from backend.schemas.base import StrictSchema


class TopicWeight(StrictSchema):
    """Normalized topic distribution entry."""

    topic: StrictStr
    weight: StrictFloat

    @field_validator("weight")
    @classmethod
    def validate_weight_bounds(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0001):
            raise ValueError(f"Topic weight must be between 0.0 and 1.0, got {v}")
        return round(v, 4)


class DeclaredProfile(StrictSchema):
    """User-declared interest categories."""

    user_id: StrictStr
    declared_topics: list[StrictStr] = Field(default_factory=list)


class BehavioralProfile(StrictSchema):
    """Empirically derived topic distribution from user past posts."""

    user_id: StrictStr
    behavioral_topics: list[TopicWeight] = Field(default_factory=list)
    top_topic: StrictStr
    top_weight: StrictFloat
    evidence_post_count: StrictInt


class ProfileStatus(StrictSchema):
    """Unified user profile state comparing declared vs behavioral trends."""

    user_id: StrictStr
    declared_topics: list[StrictStr]
    behavioral_topics: list[TopicWeight]
    profile_similarity: StrictFloat
    drift_detected: StrictBool
    evidence_post_count: StrictInt
    question: StrictStr | None = None
    active_recommendation_topics: list[TopicWeight]


class ProfileDecisionRequest(StrictSchema):
    """User decision to accept or decline the suggested profile drift update."""

    accept: StrictBool

    model_config = {
        **StrictSchema.model_config,
        "json_schema_extra": {
            "example": {
                "accept": True,
            }
        },
    }
