"""Schemas for uploaded-media (photo/video) analysis."""
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from backend.schemas.base import StrictSchema


class MediaKindEnum(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"


# Union with Literal mirrors `MediaType` in schemas/post.py: under strict mode a
# bare string is not coerced into the enum, so the literal arm is what lets the
# pipeline pass plain "photo"/"video" values around.
MediaKind = MediaKindEnum | Literal["photo", "video"]


class MediaAnalysis(StrictSchema):
    """Outcome of analysing one uploaded file.

    `topic` and `canonical_category` are `None` when the model's softmax falls
    below the calibrated floors: reporting "uncertain" is deliberate, because a
    silent argmax fallback is the exact failure HIKAYE.md (section 9) records.
    """

    media_kind: MediaKind
    filename: StrictStr
    content_type: StrictStr
    size_bytes: StrictInt
    frames_analyzed: StrictInt = Field(ge=0)
    duration_seconds: StrictFloat | None = None
    width: StrictInt = Field(ge=0)
    height: StrictInt = Field(ge=0)

    topic: StrictStr | None = None
    topic_confidence: StrictFloat = 0.0
    canonical_category: StrictStr | None = None
    category_confidence: StrictFloat = 0.0
    category_margin: StrictFloat = 0.0
    suggested_tags: list[StrictStr] = Field(default_factory=list)
    uncertain: StrictBool = True

    model_name: StrictStr
    embedding_dim: StrictInt = Field(gt=0)


class MediaAnalysisResponse(MediaAnalysis):
    """Stored analysis, addressable by `media_id` from the advisor request."""

    media_id: StrictStr
    created_at_utc: datetime
