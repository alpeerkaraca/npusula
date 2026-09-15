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


class DeclaredTopicsRequest(StrictSchema):
    """Interest topics the setup wizard sends, already mapped to the vocabulary.

    The client maps its own interest ids onto `ProfileService`'s canonical topic
    names (see the interest map in the frontend's backendAdapter). At least one
    topic is required rather than two: several client ids collapse onto the same
    topic, so a valid two-interest selection can dedupe down to one.
    """

    topics: list[StrictStr] = Field(..., min_length=1, max_length=5)

    @field_validator("topics")
    @classmethod
    def topics_must_be_canonical(cls, v: list[str]) -> list[str]:
        # Imported lazily: the schema layer must not depend on the service layer
        # at module import time.
        from backend.services.profile import TOPIC_SEEDS

        unknown = [topic for topic in v if topic not in TOPIC_SEEDS]
        if unknown:
            raise ValueError(
                f"Unknown topics {unknown}; expected a subset of {list(TOPIC_SEEDS)}"
            )
        return v


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
