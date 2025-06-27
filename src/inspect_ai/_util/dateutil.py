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
    try:
        path = Path(path) if isinstance(path, str) else path
        mtime = path.lstat().st_mtime
        path_mtime = datetime.datetime.fromtimestamp(mtime)
        prev_mtime = datetime.datetime.now() - delta
        return path_mtime < prev_mtime
    except OSError:
        return default
    except Exception as e:
        logger.warning(f"Unexpected exception checking file modification time: {e}")
        return default
