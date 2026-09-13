"""Local-time resolution and 3-hour window bucketing.

Every time value that reaches the model, the artifacts or the API goes through
this module. The rules it implements (plan §1.2 and §4.1):

* A post's local time is derived from its own UTC timestamp plus the source
  timezone offset. Without an offset there is no conversion, and the row is
  explicitly labelled ``utc_fallback`` — never silently presented as local.
* Window recommendation happens on 3-hour **local** buckets, so a bucket is a
  property of the user's clock, not of the server's.
* ``time_basis == "local"`` may only be used when a real offset was applied.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone, tzinfo
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BUCKET_HOURS = 3
BUCKETS_PER_DAY = 24 // BUCKET_HOURS  # 8

BASIS_SOURCE_OFFSET = "source_offset"
BASIS_UTC_FALLBACK = "utc_fallback"
BASIS_USER_TIMEZONE = "user_timezone"
BASIS_USER_OFFSET = "user_offset"

POST_TIMEZONE_BASES = (BASIS_SOURCE_OFFSET, BASIS_UTC_FALLBACK)
USER_TIMEZONE_BASES = (BASIS_USER_TIMEZONE, BASIS_USER_OFFSET, BASIS_UTC_FALLBACK)

TR_WEEKDAYS = [
    "Pazartesi",
    "Salı",
    "Çarşamba",
    "Perşembe",
    "Cuma",
    "Cumartesi",
    "Pazar",
]

_OFFSET_RE = re.compile(r"^(?P<sign>[+-])(?P<hours>\d{1,2}):?(?P<minutes>\d{2})$")


@dataclass(frozen=True)
class PostLocalTime:
    """Local-time resolution result for one post."""

    utc_dt: datetime
    local_dt: datetime
    local_hour: int
    local_weekday: int  # 0 = Monday, 6 = Sunday
    utc_offset: timedelta
    basis: str  # BASIS_SOURCE_OFFSET | BASIS_UTC_FALLBACK

    @property
    def locale_label(self) -> str:
        """Legacy-compatible ``time_basis`` label (only "local" when converted)."""
        return "local" if self.basis == BASIS_SOURCE_OFFSET else "utc_fallback"


@dataclass(frozen=True)
class UserTimeZone:
    """Resolved timezone used to build inference-time windows."""

    tz: tzinfo
    basis: str  # BASIS_USER_TIMEZONE | BASIS_USER_OFFSET | BASIS_UTC_FALLBACK
    label: str  # IANA name or "+03:00" or "UTC"

    @property
    def is_fallback(self) -> bool:
        return self.basis == BASIS_UTC_FALLBACK


def parse_utc_offset(value: object) -> timedelta | None:
    """Parses a source timezone offset into a timedelta.

    Accepts ``"+03:00"`` / ``"-0300"`` strings and, tolerantly, small numbers
    interpreted as **hours** (``3`` / ``-3.5``). Anything else — including
    ``None`` and out-of-range values — returns ``None`` so the caller falls
    back to UTC explicitly instead of inventing an offset.
    """
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value if abs(value) <= timedelta(hours=14) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        match = _OFFSET_RE.match(text)
        if match is None:
            return None
        hours = int(match.group("hours"))
        minutes = int(match.group("minutes"))
        if hours > 14 or minutes > 59:
            return None
        delta = timedelta(hours=hours, minutes=minutes)
        return -delta if match.group("sign") == "-" else delta
    if isinstance(value, (int, float)):
        hours = float(value)
        if abs(hours) > 14:
            return None
        return timedelta(hours=hours)
    return None


def resolve_post_local_time(
    published_at_utc: datetime | str,
    timezone_offset: object = None,
) -> PostLocalTime:
    """Resolves the local time of a post from its UTC timestamp and source offset.

    Missing/unparseable offsets yield ``local == UTC`` with
    ``basis="utc_fallback"``: the value is still usable for training (it is the
    best available estimate) but it must be labelled as a fallback everywhere.
    """
    utc_dt = _as_utc_datetime(published_at_utc)
    offset = parse_utc_offset(timezone_offset)
    if offset is None:
        return PostLocalTime(
            utc_dt=utc_dt,
            local_dt=utc_dt,
            local_hour=utc_dt.hour,
            local_weekday=utc_dt.weekday(),
            utc_offset=timedelta(0),
            basis=BASIS_UTC_FALLBACK,
        )
    local_dt = utc_dt + offset
    return PostLocalTime(
        utc_dt=utc_dt,
        local_dt=local_dt,
        local_hour=local_dt.hour,
        local_weekday=local_dt.weekday(),
        utc_offset=offset,
        basis=BASIS_SOURCE_OFFSET,
    )


def resolve_user_timezone(
    timezone_name: str | None = None,
    utc_offset_minutes: int | None = None,
) -> UserTimeZone:
    """Resolves the caller's timezone: IANA name first, then fixed offset, then UTC.

    An explicit offset wins over nothing, but an IANA name wins over an offset
    because it carries DST rules for the recommended dates.
    """
    if timezone_name:
        try:
            return UserTimeZone(tz=ZoneInfo(timezone_name), basis=BASIS_USER_TIMEZONE, label=timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    if utc_offset_minutes is not None:
        minutes = int(utc_offset_minutes)
        if abs(minutes) <= 14 * 60:
            offset = timedelta(minutes=minutes)
            sign = "+" if minutes >= 0 else "-"
            absolute = abs(minutes)
            label = f"{sign}{absolute // 60:02d}:{absolute % 60:02d}"
            return UserTimeZone(tz=timezone(offset), basis=BASIS_USER_OFFSET, label=label)
    return UserTimeZone(tz=timezone.utc, basis=BASIS_UTC_FALLBACK, label="UTC")


def bucket_of_hour(hour: int) -> int:
    """Maps a local hour (0-23) to its 3-hour bucket index (0-7)."""
    if hour < 0 or hour > 23:
        raise ValueError(f"hour out of range: {hour}")
    return hour // BUCKET_HOURS


def bucket_bounds(bucket: int) -> tuple[int, int]:
    """Returns the ``[start, end)`` local hours of a bucket."""
    if bucket < 0 or bucket >= BUCKETS_PER_DAY:
        raise ValueError(f"bucket out of range: {bucket}")
    return bucket * BUCKET_HOURS, (bucket + 1) * BUCKET_HOURS


def format_bucket_range(bucket: int) -> str:
    """Human-readable Turkish range label, e.g. ``18.00–21.00``."""
    start, end = bucket_bounds(bucket)
    return f"{start:02d}.00–{end:02d}.00"


def weekday_name_tr(weekday: int) -> str:
    """Turkish weekday name for a 0=Monday index."""
    return TR_WEEKDAYS[weekday % 7]


def _as_utc_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError(f"unsupported timestamp type: {type(value)!r}")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def local_date_at_hour(local_date, hour: int, tz: tzinfo) -> datetime:
    """Builds a tz-aware local datetime for a date/hour pair."""
    return datetime.combine(local_date, dt_time(hour=hour, minute=0, second=0), tzinfo=tz)
