"""The delimited walk of a log directory.

One listing per directory visited, never descending into ``.buffer/`` (sample
buffer segments) or ``*.checkpoints/`` (sandbox checkpoint companions), whose
object counts grow with run age. A recursive listing would page through every
one of those keys. See "Walking the directory" in
``design/ctl/log-dir-mode.md``.
"""

from __future__ import annotations

import functools
from typing import NamedTuple

import anyio

from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import EVAL_LOG_FORMAT
from inspect_ai._util.file import local_path
from inspect_ai.log._file import is_log_file

# Listings in flight at once, the CLI's fan-out cap.
_MAX_CONCURRENT_LISTINGS = 32

_BUFFER_DIR = ".buffer"
_CHECKPOINTS_SUFFIX = ".checkpoints"


class LogFile(NamedTuple):
    """One ``.eval`` file found by the walk."""

    location: str
    """Path or URL, in the form the root was given in."""

    name: str
    """The file's basename."""

    size: int

    mtime: float | None
    """Listing modification time, in seconds."""

    etag: str | None
    """Listing ETag (S3 only)."""


class LogDirListing(NamedTuple):
    """Result of :func:`walk_log_dir`."""

    eval_files: list[LogFile]
    """The ``.eval`` logs, sorted by location."""

    json_logs: list[str]
    """``.json`` logs, which this mode does not read (the format is deprecated)."""


async def walk_log_dir(fs: AsyncFilesystem, root: str) -> LogDirListing:
    """List the logs under ``root``, one delimited listing per directory.

    Raises ``FileNotFoundError`` when a local ``root`` does not exist. A
    subdirectory that disappears during the walk is skipped: its logs are gone,
    not unreadable. A ``file://`` root is walked as its local path, so every
    location the walk returns is directly readable (reserved characters in
    names need no URI encoding).
    """
    root = local_path(root)
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_LISTINGS)
    eval_files: list[LogFile] = []
    json_logs: list[str] = []

    async def visit(directory: str, is_root: bool) -> None:
        try:
            async with limiter:
                listing = await fs.list_dir(directory)
        except FileNotFoundError:
            if is_root:
                raise
            return
        for info in listing.files:
            name = basename(info.name)
            if name.endswith(f".{EVAL_LOG_FORMAT}"):
                eval_files.append(
                    LogFile(
                        location=info.name,
                        name=name,
                        size=info.size,
                        mtime=info.mtime / 1000 if info.mtime is not None else None,
                        etag=info.etag,
                    )
                )
            elif is_log_file(name, [".json"]):
                json_logs.append(info.name)
        subdirs = [d for d in listing.dirs if _descend(basename(d))]
        await tg_collect([functools.partial(visit, d, False) for d in subdirs])

    await visit(root, True)
    eval_files.sort(key=lambda f: f.location)
    json_logs.sort()
    return LogDirListing(eval_files=eval_files, json_logs=json_logs)


def basename(location: str) -> str:
    """A listed path's final name, percent-decoded for a ``file://`` URI."""
    return local_path(location).replace("\\", "/").rsplit("/", 1)[-1]


def _descend(name: str) -> bool:
    """Whether the walk lists a subdirectory with this name."""
    return name != _BUFFER_DIR and not name.endswith(_CHECKPOINTS_SUFFIX)
