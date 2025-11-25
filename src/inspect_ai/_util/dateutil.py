import datetime
from logging import getLogger
from pathlib import Path
from typing import Literal


def iso_now(
    timespec: Literal[
        "auto", "hours", "minutes", "seconds", "milliseconds", "microseconds"
    ] = "seconds",
) -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec=timespec)


logger = getLogger(__name__)


def is_file_older_than(
    path: str | Path, delta: datetime.timedelta, *, default: bool
) -> bool:
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
        path_mtime = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)
        cutoff_time = datetime.datetime.now(datetime.timezone.utc) - delta
        return path_mtime < cutoff_time
    # OSError is expected in cases where the file doesn't exist or
    # for some reason isn't accessible (e.g. due to permissions)
    except OSError:
        return default
