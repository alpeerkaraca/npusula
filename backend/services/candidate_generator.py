"""Candidate time slot generation and selection logic."""
from datetime import datetime, time, timedelta, timezone
import math
from typing import Any

from backend.schemas.recommendation import CandidateSlot


SLOT_HOURS = [9, 12, 18, 21]


def build_candidate_slots(start_time: datetime | None = None, days_ahead: int = 7) -> list[datetime]:
    """Generates 28 candidate timestamps: next 7 days at 09:00, 12:00, 18:00, 21:00 UTC."""
    if start_time is None:
        start_time = datetime.now(timezone.utc)
    elif start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    candidates: list[datetime] = []
    base_date = start_time.date()

    for day_offset in range(days_ahead):
        target_date = base_date + timedelta(days=day_offset)
        for hour in SLOT_HOURS:
            slot_dt = datetime.combine(target_date, time(hour=hour, minute=0, second=0, tzinfo=timezone.utc))
            # Include slots that are in the future or current horizon
            if slot_dt >= start_time - timedelta(minutes=30):
                candidates.append(slot_dt)

    # If some past slots were skipped, pad to ensure sufficient candidate coverage
    while len(candidates) < days_ahead * len(SLOT_HOURS):
        last_date = candidates[-1].date() if candidates else base_date
        next_date = last_date + timedelta(days=1)
        for hour in SLOT_HOURS:
            candidates.append(datetime.combine(next_date, time(hour=hour, tzinfo=timezone.utc)))
            if len(candidates) >= days_ahead * len(SLOT_HOURS):
                break

    return candidates[: days_ahead * len(SLOT_HOURS)]


def extract_time_features(dt: datetime) -> dict[str, float]:
    """Extracts cyclic and calendar time features for machine learning models."""
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


def select_top_non_overlapping_slots(
    scored_candidates: list[tuple[datetime, float]],
    top_k: int = 3,
    min_gap_hours: float = 3.0,
) -> list[CandidateSlot]:
    """Selects top-k slots sorted by predicted popularity that are separated by at least min_gap_hours."""
    ranked = sorted(scored_candidates, key=lambda item: item[1], reverse=True)
    selected: list[tuple[datetime, float]] = []

    min_gap_seconds = min_gap_hours * 3600.0

    for dt, score in ranked:
        if all(abs((dt - prev_dt).total_seconds()) >= min_gap_seconds for prev_dt, _ in selected):
            selected.append((dt, score))
        if len(selected) == top_k:
            break

    # If not enough non-overlapping slots found, pad with highest available
    if len(selected) < top_k:
        for dt, score in ranked:
            if not any(dt == s[0] for s in selected):
                selected.append((dt, score))
            if len(selected) == top_k:
                break

    results: list[CandidateSlot] = []
    labels = ["Çok güçlü", "Güçlü", "Orta"]

    for idx, (dt, score) in enumerate(selected):
        label = labels[idx] if idx < len(labels) else "İyi"
        results.append(
            CandidateSlot(
                datetime_utc=dt,
                hour=dt.hour,
                weekday=dt.weekday(),
                predicted_popularity=round(score, 3),
                label=label,
            )
        )

    return results
