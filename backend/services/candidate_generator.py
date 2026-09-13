"""Candidate time slot/window generation and selection logic.

Candidates are enumerated as hours and *presented* as 3-hour local windows
(plan §4.1): the 7×24 = 168 hourly timestamps still exist, but only to give each
bucket a concrete calendar position. Hours never compete against each other in
the product.
"""
from datetime import datetime, timedelta, timezone
import math
from dataclasses import dataclass

from backend.services.time_features import BUCKET_HOURS, bucket_of_hour

# Backwards-compatible export for callers that still need the hourly scan.
SLOT_HOURS = list(range(24))


@dataclass(frozen=True)
class CandidateWindow:
    """A concrete 3-hour window in the user's local calendar."""

    local_start: datetime
    local_end: datetime
    utc_start: datetime
    utc_end: datetime
    weekday: int
    bucket: int


def build_candidate_slots(start_time: datetime | None = None, days_ahead: int = 7) -> list[datetime]:
    """Generates ``days_ahead x 24`` hourly timestamps from ``start_time`` (default UTC).

    Kept as the low-level enumerator: windows and bucket boundaries are derived
    from it so there is exactly one definition of "which hours exist".
    """
    if start_time is None:
        start_time = datetime.now(timezone.utc)
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    # Start at the next full hour so a window never begins in the past.
    first = start_time.replace(minute=0, second=0, microsecond=0)
    if first < start_time:
        first += timedelta(hours=1)

    return [first + timedelta(hours=offset) for offset in range(days_ahead * len(SLOT_HOURS))]


def build_candidate_windows(
    start_local: datetime,
    days_ahead: int = 7,
    bucket_hours: int = BUCKET_HOURS,
) -> list[CandidateWindow]:
    """Builds exactly ``days_ahead x (24 / bucket_hours)`` windows in **local** time.

    The hourly scan is used only to place each bucket on the calendar: the first
    window starts at the next bucket boundary after ``start_local``, so the
    horizon is a whole number of windows instead of partial first/last days.

    The local timestamps are the ones shown to the user ("Salı 18.00–21.00");
    the UTC pair is what a scheduler needs. Both are derived from the same
    tz-aware local datetime, so DST transitions are handled by the timezone.
    """
    if start_local.tzinfo is None:
        raise ValueError("start_local must be timezone-aware")

    windows_per_day = max(1, 24 // bucket_hours)
    target = days_ahead * windows_per_day
    if target <= 0:
        return []

    windows: list[CandidateWindow] = []
    # One extra day of hourly slots guarantees `target` bucket boundaries.
    for slot in build_candidate_slots(start_time=start_local, days_ahead=days_ahead + 1):
        if slot.hour % bucket_hours != 0:
            continue
        local_start = slot.replace(minute=0, second=0, microsecond=0)
        local_end = local_start + timedelta(hours=bucket_hours)
        windows.append(
            CandidateWindow(
                local_start=local_start,
                local_end=local_end,
                utc_start=local_start.astimezone(timezone.utc),
                utc_end=local_end.astimezone(timezone.utc),
                weekday=local_start.weekday(),
                bucket=bucket_of_hour(local_start.hour),
            )
        )
        if len(windows) == target:
            break

    return windows


def extract_time_features(dt: datetime) -> dict[str, float]:
    """Extracts cyclic and calendar time features.

    Retained for reporting and tests only: the base-potential model does **not**
    take time features any more (plan §3.2), so nothing in the model path may
    consume this.
    """
    hour = dt.hour
    weekday = dt.weekday()  # 0 = Monday, 6 = Sunday

    hour_rad = 2 * math.pi * hour / 24.0
    weekday_rad = 2 * math.pi * weekday / 7.0

    return {
        "hour": float(hour),
        "weekday": float(weekday),
        "hour_sin": round(math.sin(hour_rad), 4),
        "hour_cos": round(math.cos(hour_rad), 4),
        "weekday_sin": round(math.sin(weekday_rad), 4),
        "weekday_cos": round(math.cos(weekday_rad), 4),
        "is_weekend": 1.0 if weekday >= 5 else 0.0,
    }
