"""Recommendation and advisor schemas adhering to strict Pydantic rules.

The product contract is a **recommended sharing window**, not a best hour:
a window carries its observational lift, the support behind it, the evidence
level and a confidence — never a claim that the hour causes better engagement.
"""
from datetime import datetime
from typing import Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from backend.schemas.base import StrictSchema
from backend.schemas.media import MediaAnalysisResponse
from backend.schemas.post import MediaType, MediaTypeEnum

ConfidenceLevel = Literal["high", "medium", "low"]

EvidenceLevel = Literal[
    "category_weekday_bucket",
    "category_bucket",
    "global_weekday_bucket",
    "global_bucket",
    "neutral",
]

TimezoneBasis = Literal["user_timezone", "user_offset", "utc_fallback"]


class RecommendedWindow(StrictSchema):
    """A 3-hour local sharing window with its observational evidence."""

    window_start_local: datetime = Field(..., description="Window start in the user's local time")
    window_end_local: datetime = Field(..., description="Window end in the user's local time")
    window_start_utc: datetime = Field(..., description="Same instant in UTC (scheduling)")
    window_end_utc: datetime = Field(..., description="Same instant in UTC (scheduling)")
    weekday: StrictStr = Field(..., description="Turkish weekday name, e.g. 'Salı'")
    weekday_index: StrictInt = Field(..., ge=0, le=6, description="0 = Monday")
    bucket: StrictInt = Field(..., ge=0, le=7, description="3-hour local bucket index")
    time_range_local: StrictStr = Field(..., description="Local range label, e.g. '18.00–21.00'")
    base_potential: StrictFloat = Field(..., description="Layer A post potential, independent of timing")
    observational_time_lift: StrictFloat = Field(
        ..., description="Shrunk mean residual lift observed for this category/window"
    )
    relative_potential: StrictFloat = Field(
        default=0.0,
        description=(
            "Observational relative score of this window against the average candidate window "
            "(in popularity-score units). NOT a percentage engagement increase."
        ),
    )
    confidence: ConfidenceLevel = Field(default="low", description="high | medium | low")
    confidence_label: StrictStr = Field(default="Düşük", description="Turkish display label")
    support_post_count: StrictInt = Field(default=0, description="Training posts behind this lift")
    support_user_count: StrictInt = Field(default=0, description="Distinct users behind this lift")
    evidence_level: EvidenceLevel = Field(
        default="neutral", description="Hierarchy level the lift actually came from"
    )
    lift_ci_low: StrictFloat | None = Field(default=None, description="User-clustered bootstrap CI low")
    lift_ci_high: StrictFloat | None = Field(default=None, description="User-clustered bootstrap CI high")
    is_tie_or_broad_window: StrictBool = Field(
        default=True,
        description="True when the evidence does not support a strict ranking",
    )
    timezone_basis: TimezoneBasis = Field(
        default="utc_fallback", description="How the caller's timezone was resolved"
    )


class WindowRecommendation(StrictSchema):
    """Service-level aggregate returned by the recommendation service."""

    base_potential: StrictFloat
    primary_category_code: StrictInt
    confidence: ConfidenceLevel
    confidence_label: StrictStr
    is_tie_or_broad_window: StrictBool
    timezone_basis: TimezoneBasis
    timezone_label: StrictStr
    timezone_fallback: StrictBool
    history_depth: StrictInt
    windows: list[RecommendedWindow]


class QuickRecommendationResponse(StrictSchema):
    """Immediate window recommendation for the user's active topic."""

    user_id: StrictStr
    active_topic: StrictStr
    windows: list[RecommendedWindow]
    cold_start: StrictBool
    confidence: ConfidenceLevel
    confidence_label: StrictStr
    timezone_basis: TimezoneBasis
    explanation: StrictStr


class AdvisorRequest(StrictSchema):
    """Request payload for the interactive Advisor module."""

    user_id: StrictStr
    idea: StrictStr = Field(..., min_length=1, max_length=500)
    media_type: MediaType = Field(default=MediaTypeEnum.PHOTO)
    horizon: StrictStr = Field(default="next_7_days")
    # Optional handle returned by POST /api/media/analyze. Absent, expired or
    # unknown ids simply leave the request on the text-only path.
    media_id: StrictStr | None = Field(default=None)
    # Caller timezone. An IANA name is preferred (it carries DST rules); a fixed
    # offset is accepted. Without either, recommendations fall back to UTC and
    # the response says so explicitly.
    timezone: StrictStr | None = Field(default=None, description="IANA timezone, e.g. 'Europe/Istanbul'")
    utc_offset_minutes: StrictInt | None = Field(
        default=None, ge=-840, le=840, description="Fixed UTC offset in minutes, e.g. 180"
    )

    model_config = {
        **StrictSchema.model_config,
        "json_schema_extra": {
            "example": {
                "user_id": "31253@N15",
                "idea": "Yapay zeka modelleri ve mobil cihazlarda yerel LLM optimizasyonu",
                "media_type": "video",
                "horizon": "next_7_days",
                "media_id": "a1b2c3d4e5f6",
                "timezone": "Europe/Istanbul",
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
    """Complete advisor response with windows, tags, explanation, and similar posts."""

    request_id: StrictStr
    topic: StrictStr
    primary_category: StrictStr = Field(default="")
    primary_category_confidence: StrictFloat = Field(
        default=0.0,
        description=(
            "Deterministic match-density score of the category classifier (or the image analysis "
            "confidence when the image category was adopted). NOT a trained-model probability."
        ),
    )
    primary_category_is_fallback: StrictBool = Field(
        default=True,
        description="True when nothing matched and the category is the classifier's fallback label",
    )
    windows: list[RecommendedWindow]
    accepted_tags: list[StrictStr] = Field(default_factory=list)
    rejected_tags: list[StrictStr] = Field(default_factory=list)
    unknown_tags: list[StrictStr] = Field(default_factory=list)
    suggested_tags: list[StrictStr]
    explanation: StrictStr
    similar_posts: list[SimilarPost]
    history_depth: StrictStr = Field(default="cold_start")
    confidence_level: StrictStr = Field(default="Düşük", description="Turkish display label")
    confidence: ConfidenceLevel = Field(default="low")
    is_tie_or_broad_window: StrictBool = Field(default=True)
    timezone_basis: TimezoneBasis = Field(default="utc_fallback")
    timezone_fallback: StrictBool = Field(default=True)
    model_version: StrictStr
    data_source: StrictStr
    service_mode: StrictStr = Field(default="quick", description="'quick' or 'deep_advisor'")
    # Present only when the request referenced an analysed upload; carries the
    # evidence behind any topic/category that came from the image. Typed as the
    # *Response* model on purpose: declaring the parent would narrow the value
    # and silently drop media_id/created_at_utc during validation.
    media_analysis: MediaAnalysisResponse | None = Field(default=None)


class FeatureImportanceEntry(StrictSchema):
    """Feature importance ranking entry."""

    feature: StrictStr
    importance: StrictFloat


class ModelMetricsResponse(StrictSchema):
    """Reported offline metrics and feature importance.

    `model_mae` / `model_spearman` describe **post popularity** prediction, not
    window quality; window quality lives in the time-lift section of
    `artifacts/final_evaluation.json`.
    """

    baseline_mae: StrictFloat
    baseline_spearman: StrictFloat
    model_mae: StrictFloat
    model_spearman: StrictFloat
    feature_importance: list[FeatureImportanceEntry]
