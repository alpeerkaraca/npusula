"""Selectable accounts for the frontend account picker.

The picker exists so a demo can move between identities that behave
differently: a rich history yields a "Yüksek" window recommendation, an
account with no history exercises the cold-start path. `history_depth` is the
label `history_depth_name` gives `post_count`.
"""
from pydantic import StrictInt, StrictStr

from backend.schemas.base import StrictSchema


class SampleUser(StrictSchema):
    """One selectable account, with the history depth behind its behaviour."""

    user_id: StrictStr
    # Rows for this user in the processed corpus, not `evidence_post_count`:
    # that one is capped at 30 by ProfileService, so it can never express
    # "high_history" and would render most of the picker identically.
    post_count: StrictInt
    history_depth: StrictStr


class SampleUserList(StrictSchema):
    users: list[SampleUser]
