"""Canonical PostRecord schema adhering to strict Pydantic rules.

The field list is the *contract* of `scripts/02_normalize_smp.py`: the
normalizer validates a sample of its rows against this model and asserts that
the written Parquet has no column this schema does not declare. Keeping the two
in sync is what makes `posts.parquet` self-describing, so change them together.

Timezone contract (plan §1.2):
- ``published_at_utc`` is a real UTC timestamp.
- ``local_datetime``/``local_hour``/``local_weekday`` are the wall-clock values
  derived from the source offset. They are only meaningful together with
  ``timezone_basis``: ``source_offset`` means a real conversion happened,
  ``utc_fallback`` means no offset was available and local == UTC.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from backend.schemas.base import StrictSchema


class MediaTypeEnum(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"
    UNKNOWN = "unknown"


MediaType = MediaTypeEnum | Literal["photo", "video", "unknown"]

TimezoneBasis = Literal["source_offset", "utc_fallback", "user_timezone", "user_offset"]


class PostRecord(StrictSchema):
    """Canonical data standard for SMPD and NSosyal posts."""

    schema_version: StrictStr = "1.0"
    source: StrictStr = Field(default="smpd_real", description="Data source identifier (e.g. smpd_real, nsosyal)")
    post_id: StrictStr = Field(..., description="Unique post identifier")
    user_id: StrictStr = Field(..., description="Author user identifier")
    published_at_utc: datetime = Field(..., description="UTC publication timestamp")
    timezone_offset: StrictStr | None = Field(
        default=None, description="Source timezone offset as written by the origin (e.g. '+03:00')"
    )
    timezone_id: StrictStr | None = Field(
        default=None, description="Source timezone label (provenance only; may be a platform-specific name)"
    )
    local_datetime: datetime | None = Field(
        default=None, description="Local wall-clock timestamp (naive) after applying timezone_offset"
    )
    local_hour: StrictInt | None = Field(default=None, ge=0, le=23, description="Local hour of local_datetime")
    local_weekday: StrictInt | None = Field(
        default=None, ge=0, le=6, description="Local weekday of local_datetime (0 = Monday)"
    )
    timezone_basis: TimezoneBasis = Field(
        default="utc_fallback",
        description="'source_offset' when a real conversion happened, otherwise 'utc_fallback'",
    )
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
    source_user_photo_count: StrictInt | None = Field(
        default=None,
        description="Source-reported lifetime photo count. Stored for provenance; MUST NOT be a model feature.",
    )
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


# Schema fields that the normalizer deliberately does not write: they describe
# media payloads that only exist for corpora shipping the actual files (the SMPD
# Parquet carries no embeddings — see plan §1.3, "CLIP embedding'i eğitime
# varmış gibi eklemeyecek"). The column check allows them to be absent.
OPTIONAL_UNWRITTEN_FIELDS: frozenset[str] = frozenset(
    {
        "image_embedding",
        "text_embedding",
    }
)

# Features that must never be fed to the model even though they are stored for
# provenance. `source_user_photo_count` is a lifetime account statistic the
# source reports *after* the fact; using it would leak account size into the
# content model. tests/test_feature_contract.py enforces the exclusion.
PROVENANCE_ONLY_COLUMNS: frozenset[str] = frozenset(
    {
        "source_user_photo_count",
        "source",
        "schema_version",
        "ingested_at_utc",
        "timezone_id",
    }
)
