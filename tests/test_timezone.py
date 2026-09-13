"""Local-time contract: UTC -> local conversion, fallback labelling, windows.

Covers plan §1.2 acceptance criteria and the §4.1 bucket geometry.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.services.candidate_generator import build_candidate_slots, build_candidate_windows
from backend.services.time_features import (
    BASIS_SOURCE_OFFSET,
    BASIS_UTC_FALLBACK,
    BASIS_USER_OFFSET,
    BASIS_USER_TIMEZONE,
    bucket_bounds,
    bucket_of_hour,
    format_bucket_range,
    parse_utc_offset,
    resolve_post_local_time,
    resolve_user_timezone,
)


def test_utc_to_local_conversion_with_source_offset():
    """+03:00 source post at UTC 18:00 is local 21:00 — the plan's acceptance case."""
    result = resolve_post_local_time("2016-02-09T18:00:00Z", "+03:00")

    assert result.utc_dt == datetime(2016, 2, 9, 18, 0, tzinfo=timezone.utc)
    assert result.local_dt.hour == 21
    assert result.local_hour == 21
    assert result.basis == BASIS_SOURCE_OFFSET
    assert result.locale_label == "local"


def test_utc_to_local_conversion_crosses_day_boundary():
    """A negative offset must roll the local date back (and the weekday with it)."""
    # Tuesday 2016-02-09 02:00 UTC with -05:00 -> Monday 2016-02-08 21:00 local
    result = resolve_post_local_time("2016-02-09T02:00:00Z", "-05:00")

    assert result.local_dt.day == 8
    assert result.local_hour == 21
    assert result.local_weekday == 0  # Monday


def test_missing_offset_falls_back_to_utc_and_is_labelled():
    for raw_offset in (None, "", "not-an-offset", "+99:00"):
        result = resolve_post_local_time("2016-02-09T18:00:00Z", raw_offset)
        assert result.basis == BASIS_UTC_FALLBACK
        assert result.local_hour == 18
        assert result.locale_label == "utc_fallback"
        assert result.utc_offset == timedelta(0)


def test_zero_offset_still_counts_as_a_real_conversion():
    """+00:00 is a source-provided offset, so it is `source_offset`, not a fallback."""
    result = resolve_post_local_time("2016-02-09T18:00:00Z", "+00:00")
    assert result.basis == BASIS_SOURCE_OFFSET
    assert result.local_hour == 18


def test_parse_utc_offset_variants():
    assert parse_utc_offset("+03:00") == timedelta(hours=3)
    assert parse_utc_offset("-0530") == timedelta(hours=-5, minutes=-30)
    assert parse_utc_offset(3) == timedelta(hours=3)
    assert parse_utc_offset(2.5) == timedelta(hours=2, minutes=30)
    assert parse_utc_offset(None) is None
    assert parse_utc_offset("+20:00") is None  # out of range
    assert parse_utc_offset(True) is None


def test_user_timezone_resolution_prefers_iana_then_offset_then_utc():
    istanbul = resolve_user_timezone(timezone_name="Europe/Istanbul")
    assert istanbul.basis == BASIS_USER_TIMEZONE
    assert not istanbul.is_fallback

    offset = resolve_user_timezone(utc_offset_minutes=180)
    assert offset.basis == BASIS_USER_OFFSET
    assert offset.label == "+03:00"
    assert not offset.is_fallback

    # An IANA name wins over a contradictory offset (DST rules are richer)
    both = resolve_user_timezone(timezone_name="Europe/Istanbul", utc_offset_minutes=-300)
    assert both.basis == BASIS_USER_TIMEZONE

    unknown = resolve_user_timezone()
    assert unknown.basis == BASIS_UTC_FALLBACK
    assert unknown.is_fallback

    bogus = resolve_user_timezone(timezone_name="Not/AZone")
    assert bogus.basis == BASIS_UTC_FALLBACK


def test_bucket_geometry():
    assert bucket_of_hour(0) == 0
    assert bucket_of_hour(2) == 0
    assert bucket_of_hour(3) == 1
    assert bucket_of_hour(18) == 6
    assert bucket_of_hour(23) == 7
    assert bucket_bounds(6) == (18, 21)
    assert format_bucket_range(6) == "18.00–21.00"
    with pytest.raises(ValueError):
        bucket_of_hour(24)


def test_candidate_windows_are_local_and_convert_to_utc():
    istanbul = ZoneInfo("Europe/Istanbul")
    start = datetime(2026, 9, 14, 10, 30, tzinfo=istanbul)  # Monday morning local

    windows = build_candidate_windows(start, days_ahead=7)

    assert len(windows) == 7 * 8  # 7 days x 8 three-hour buckets
    assert all(window.local_start.tzinfo is not None for window in windows)
    # Local wall clock is what the user sees; UTC is the scheduling twin.
    first = windows[0]
    assert first.local_start.hour % 3 == 0
    assert first.local_end - first.local_start == timedelta(hours=3)
    assert first.utc_start == first.local_start.astimezone(timezone.utc)
    # 18:00 local in Istanbul is 15:00 UTC
    evening = next(window for window in windows if window.local_start.hour == 18)
    assert evening.bucket == 6
    assert evening.utc_start.hour == 15
    assert evening.weekday == evening.local_start.weekday()


def test_candidate_slots_cover_every_hour_of_the_horizon():
    """The 7x24 hourly scan still exists (it defines window boundaries)."""
    start = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    slots = build_candidate_slots(start_time=start, days_ahead=7)

    assert len(slots) == 7 * 24
    assert {slot.hour for slot in slots} == set(range(24))
    assert all(slot.minute == 0 and slot.second == 0 for slot in slots)
    # No window may start in the past
    assert min(slots) >= start
