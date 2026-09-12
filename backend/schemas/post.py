"""Canonical PostRecord schema adhering to strict Pydantic rules."""
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from typing import Annotated, Literal

from backend.schemas.base import StrictSchema


class MediaTypeEnum(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"
    UNKNOWN = "unknown"


MediaType = MediaTypeEnum | Literal["photo", "video", "unknown"]


class PostRecord(StrictSchema):
    """Canonical data standard for SMPD and EnSosyal posts."""

    schema_version: StrictStr = "1.0"
    source: StrictStr = Field(default="smpd_image", description="Data source identifier (e.g. smpd_image, ensosyal)")
    post_id: StrictStr = Field(..., description="Unique post identifier")
    user_id: StrictStr = Field(..., description="Author user identifier")
    published_at_utc: datetime = Field(..., description="UTC publication timestamp")
    timezone: StrictStr | None = Field(default=None, description="Timezone name if provided")
    timezone_inferred: StrictBool = Field(default=True, description="Flag indicating timezone was assumed/inferred")
    title: StrictStr = Field(..., description="Post title or raw text")
    description: StrictStr | None = Field(default=None, description="Optional description/caption")
    tags: list[StrictStr] = Field(default_factory=list, description="Extracted content tags")
    media_type: MediaType = Field(default=MediaTypeEnum.PHOTO, description="Type of media asset")
    media_path: StrictStr | None = Field(default=None, description="Relative or absolute file path to media")
    media_available: StrictBool = Field(default=False, description="Whether media file is verified and readable")
    category_l1: StrictStr | None = Field(default=None, description="Top-level category")
    category_l2: StrictStr | None = Field(default=None, description="Sub-category")
    concept: StrictStr | None = Field(default=None, description="SMP concept label")
    latitude: StrictFloat | None = Field(default=None, description="Geolocation latitude")
    longitude: StrictFloat | None = Field(default=None, description="Geolocation longitude")
    user_followers: StrictInt | None = Field(default=None, description="User followers count if available")
    user_following: StrictInt | None = Field(default=None, description="User following count if available")
    user_post_count_prior: StrictInt = Field(default=0, description="Cumulative count of prior posts by author")
    user_popularity_mean_prior: StrictFloat = Field(
        default=0.0, description="Leakage-free prior mean popularity score"
    )
    popularity_score: StrictFloat | None = Field(
        default=None, description="Target popularity log-view score (null during inference)"
    )
    image_embedding: list[StrictFloat] | None = Field(default=None, description="Normalized CLIP image embedding (512-D)")
    text_embedding: list[StrictFloat] | None = Field(default=None, description="Multilingual CLIP text embedding (512-D)")
    ingested_at_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="Ingestion pipeline timestamp"
    )
