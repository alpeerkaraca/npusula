"""Base schema configuration with strict Pydantic rules."""
from pydantic import BaseModel, ConfigDict


class StrictSchema(BaseModel):
    """Base model enforcing strict type checking, no unexpected fields, and trimmed strings."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )
