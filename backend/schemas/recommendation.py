"""Recommendation and advisor schemas adhering to strict Pydantic rules."""
from datetime import datetime

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from backend.schemas.base import StrictSchema
from backend.schemas.post import MediaType, MediaTypeEnum


class CandidateSlot(StrictSchema):
    """Scored time slot candidate."""

    datetime_utc: datetime
    hour: StrictInt
    weekday: StrictInt
    predicted_popularity: StrictFloat
    relative_potential: StrictFloat = Field(default=0.0, description="Relative potential vs median candidate")
    confidence_level: StrictStr = Field(default="Orta", description="Düşük, Orta, or Yüksek")
    label: StrictStr = Field(description="'Çok güçlü', 'Güçlü' or 'Orta'")


class QuickRecommendationResponse(StrictSchema):
    """Immediate top-3 time recommendation based on active profile."""

    user_id: StrictStr
    active_topic: StrictStr
    slots: list[CandidateSlot]
    cold_start: StrictBool
    explanation: StrictStr


class AdvisorRequest(StrictSchema):
    """Request payload for the interactive Advisor module."""

    user_id: StrictStr
    idea: StrictStr = Field(..., min_length=1, max_length=500)
    media_type: MediaType = Field(default=MediaTypeEnum.PHOTO)
    horizon: StrictStr = Field(default="next_7_days")

    model_config = {
        **StrictSchema.model_config,
        "json_schema_extra": {
            "example": {
                "user_id": "demo_user_01",
                "idea": "Yapay zeka modelleri ve mobil cihazlarda yerel LLM optimizasyonu",
                "media_type": "video",
                "horizon": "next_7_days",
            }
        },
    }


class SimilarPost(StrictSchema):
    """Similar high-performing post returned from vector retrieval."""

    post_id: StrictStr
    title: StrictStr
    hour: StrictInt
    weekday: StrictInt
    popularity_score: StrictFloat
    similarity: StrictFloat
    tags: list[StrictStr]


class AdvisorResponse(StrictSchema):
    """Complete advisor response with time slots, tags, explanation, and similar posts."""

    request_id: StrictStr
    topic: StrictStr
    primary_category: StrictStr = Field(default="")
    recommendations: list[CandidateSlot]
    accepted_tags: list[StrictStr] = Field(default_factory=list)
    rejected_tags: list[StrictStr] = Field(default_factory=list)
    suggested_tags: list[StrictStr]
    explanation: StrictStr
    similar_posts: list[SimilarPost]
    history_depth: StrictStr = Field(default="cold_start")
    confidence_level: StrictStr = Field(default="Orta")
    model_version: StrictStr
    data_source: StrictStr
    service_mode: StrictStr = Field(default="quick", description="'quick' or 'deep_advisor'")


class FeatureImportanceEntry(StrictSchema):
    """Feature importance ranking entry."""

    feature: StrictStr
    importance: StrictFloat


class ModelMetricsResponse(StrictSchema):
    """Reported test metrics and feature importance."""

    baseline_mae: StrictFloat
    baseline_spearman: StrictFloat
    model_mae: StrictFloat
    model_spearman: StrictFloat
    feature_importance: list[FeatureImportanceEntry]
