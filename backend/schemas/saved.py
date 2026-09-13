"""Schemas for the plans and drafts a user saves from the NPusula screens."""
from typing import Literal

from pydantic import StrictStr

from backend.schemas.base import StrictSchema

ContentFormat = Literal["video", "image", "thread"]


class PlanRequest(StrictSchema):
    """A plan attached to one of the recommended sharing windows.

    `slot_id` is the window identifier the client received from
    /api/recommend/*; this service records the intent but owns no slot
    registry, publish permission or scheduler.
    """

    slot_id: StrictStr
    starts_at: StrictStr
    time_zone: StrictStr
    text: StrictStr
    format: ContentFormat


class PlanResponse(StrictSchema):
    id: StrictStr
    slot_id: StrictStr
    starts_at: StrictStr
    # "saved" is what this service actually does; "scheduled" is reserved for a
    # future scheduler and is never returned today.
    status: Literal["saved", "scheduled"]


class DraftRequest(StrictSchema):
    text: StrictStr
    format: ContentFormat


class DraftResponse(StrictSchema):
    id: StrictStr
    text: StrictStr
    format: ContentFormat
