import sys
from datetime import date, datetime, time, timedelta, timezone
from logging import getLogger
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BeforeValidator


def iso_now(
    timespec: Literal[
        "auto", "hours", "minutes", "seconds", "milliseconds", "microseconds"
    ] = "seconds",
) -> "UtcDatetimeStr":
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec=timespec)


logger = getLogger(__name__)


def _normalize_iso_z_suffix(input: str) -> str:
    """Normalize Z suffix in ISO format strings for Python 3.10 compatibility.

    Python 3.10's fromisoformat() doesn't support Z suffix for UTC.
    Python 3.11+ handles Z natively.

    Args:
        input: ISO format string (may end with Z or z)

    Returns:
        ISO format string with Z/z replaced by +00:00 (if Python < 3.11)
    """
    return (
        input
        if sys.version_info >= (3, 11) or not input.endswith(("Z", "z"))
        else input[:-1] + "+00:00"
    )


def is_file_older_than(path: str | Path, delta: timedelta, *, default: bool) -> bool:
    """Check if a file's modification time is older than a given time delta.

    Args:
        path: Path to the file to check
        delta: Time delta to compare against
        default: Value to return if file doesn't exist or isn't accessible

    Returns:
        True if file was last modified before (now - delta), False otherwise.
    """
    try:
        path = Path(path)
        mtime = path.lstat().st_mtime
        path_mtime = datetime.fromtimestamp(mtime, tz=timezone.utc)
        cutoff_time = datetime.now(timezone.utc) - delta
        return path_mtime < cutoff_time
    # OSError is expected in cases where the file doesn't exist or
    # for some reason isn't accessible (e.g. due to permissions)
    except OSError:
        return default


def datetime_now_utc() -> "UtcDatetime":
    """Return current datetime in UTC with timezone info."""
    # This function may seem silly, but it's useful as a parameterless factory in
    # scenarios like `Field(default_factory=datetime_now_utc)`
    return datetime.now(timezone.utc)


def datetime_from_iso_format_safe(
    input: str, fallback_tz: timezone = timezone.utc
) -> "UtcDatetime":
    """Parse ISO format datetime string, applying fallback timezone if none specified.

    Args:
        input: ISO format datetime string (e.g., '2025-04-17T12:00:00' or '2025-04-17T12:00:00Z')
        fallback_tz: Timezone to apply if input lacks timezone info (default: UTC)

    Returns:
        Timezone-aware datetime object. If input has timezone, uses it; otherwise
        applies fallback_tz.
    """
    return datetime_safe(
        datetime.fromisoformat(_normalize_iso_z_suffix(input)), fallback_tz
    )


def datetime_safe(dt: datetime, fallback_tz: timezone = timezone.utc) -> "UtcDatetime":
    """Ensure datetime has timezone info, applying fallback if naive.

    Args:
        dt: Datetime object (may or may not have timezone)
        fallback_tz: Timezone to apply if dt lacks timezone info (default: UTC)

    Returns:
        Timezone-aware datetime. If dt has timezone, returns as-is; otherwise
        applies fallback_tz.
    """
    return dt if dt.tzinfo else dt.replace(tzinfo=fallback_tz)


def datetime_to_iso_format_safe(
    dt: datetime, fallback_tz: timezone = timezone.utc
) -> str:
    """Convert datetime to ISO format string, applying fallback timezone if naive.

    Args:
        dt: Datetime object (may or may not have timezone)
        fallback_tz: Timezone to apply if dt lacks timezone info (default: UTC)

    Returns:
        ISO format string of timezone-aware datetime.
    """
    return datetime_safe(dt, fallback_tz).isoformat()


def _before_validate_utc_datetime(v: Any) -> Any:
    """Pre-validation coercion for UtcDatetime.

    - Strings: Parse with UTC fallback (legacy logs)
    - Aware datetimes: Convert to UTC
    - Naive datetimes: Coerce to UTC (treats as UTC per design)
    - Numeric: Pass through to AwareDatetime (handles int/float timestamps)
    """
    if isinstance(v, str):
        return datetime_from_iso_format_safe(v).astimezone(timezone.utc)
    if isinstance(v, datetime):
        # Design requirement: "transforms naive data to UTC rather than rejecting it"
        return datetime_safe(v, timezone.utc).astimezone(timezone.utc)
    # Pass through numeric timestamps for AwareDatetime to handle
    return v


def _before_validate_utc_date(v: Any) -> Any:
    """Pre-validation coercion for UtcDate."""
    if isinstance(v, str):
        return date.fromisoformat(_normalize_iso_z_suffix(v))
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    # Pass through - let Pydantic handle invalid input
    return v


def _before_validate_utc_time(v: Any) -> Any:
    """Pre-validation coercion for UtcTime."""
    if isinstance(v, str):
        return time.fromisoformat(_normalize_iso_z_suffix(v))
    if isinstance(v, datetime):
        return v.timetz() if v.tzinfo else v.time()
    if isinstance(v, time):
        return v
    # Pass through - let Pydantic handle invalid input
    return v


def _before_validate_utc_datetime_str(v: Any) -> str:
    """Parse and normalize ISO datetime string to UTC.

    For legacy string temporal fields that cannot be converted to UtcDatetime
    without breaking API compatibility. Accepts ISO 8601 strings, normalizes
    to UTC, returns as ISO string.

    Args:
        v: ISO 8601 datetime string

    Returns:
        UTC-normalized ISO 8601 string

    Raises:
        ValueError: If v is not a string or not a valid ISO datetime
    """
    if not isinstance(v, str):
        raise ValueError(f"Expected str, got {type(v)}")
    return (
        datetime_from_iso_format_safe(v, fallback_tz=timezone.utc)
        .astimezone(timezone.utc)
        .isoformat()
    )


UtcDatetime = Annotated[AwareDatetime, BeforeValidator(_before_validate_utc_datetime)]
UtcDate = Annotated[date, BeforeValidator(_before_validate_utc_date)]
UtcTime = Annotated[time, BeforeValidator(_before_validate_utc_time)]
UtcDatetimeStr = Annotated[str, BeforeValidator(_before_validate_utc_datetime_str)]
