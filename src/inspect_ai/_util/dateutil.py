from datetime import datetime, timedelta, timezone
from logging import getLogger
from pathlib import Path
from typing import Literal


def iso_now(
    timespec: Literal[
        "auto", "hours", "minutes", "seconds", "milliseconds", "microseconds"
    ] = "seconds",
) -> str:
    return datetime.now().astimezone().isoformat(timespec=timespec)


logger = getLogger(__name__)


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


def datetime_now_utc() -> datetime:
    """Return current datetime in UTC with timezone info."""
    # This function may seem silly, but it's useful as a parameterless factory in
    # scenarios like `Field(default_factory=datetime_now_utc)`
    return datetime.now(timezone.utc)


def datetime_from_iso_format_safe(
    input: str, fallback_tz: timezone = timezone.utc
) -> datetime:
    """Parse ISO format datetime string, applying fallback timezone if none specified.

    Args:
        input: ISO format datetime string (e.g., '2025-04-17T12:00:00' or '2025-04-17T12:00:00Z')
        fallback_tz: Timezone to apply if input lacks timezone info (default: UTC)

    Returns:
        Timezone-aware datetime object. If input has timezone, uses it; otherwise
        applies fallback_tz.
    """
    return datetime_safe(datetime.fromisoformat(input), fallback_tz)


def datetime_safe(dt: datetime, fallback_tz: timezone = timezone.utc) -> datetime:
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
