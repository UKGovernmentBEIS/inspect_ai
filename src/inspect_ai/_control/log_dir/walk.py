"""The delimited walk of a log directory.

One listing per directory visited, never descending into ``.buffer/`` (sample
buffer segments; its presence is recorded on the logs beside it) or ``*.checkpoints/`` (sandbox checkpoint companions), whose
object counts grow with run age. A recursive listing would page through every
one of those keys. A ``<name>.shards/`` companion is listed by the shared
shard-set walk (:func:`~inspect_ai.log._shards._walk.list_shard_set`), so this
mode and the merge agree on which files are shard attempts. See "Walking the
directory" in ``design/ctl/log-dir-mode.md``.
"""

from __future__ import annotations

import functools
from typing import NamedTuple

import anyio

from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import EVAL_LOG_FORMAT
from inspect_ai._util.file import FileInfo, local_path
from inspect_ai._util.log_layout import _SHARDS_SUFFIX, log_basename
from inspect_ai.log._file import is_log_file
from inspect_ai.log._shards._walk import (
    AttemptSortKey,
    ShardDir,
    StrayFile,
    attempt_sort_key,
    list_shard_set,
)

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

    buffer_dir: str | None = None
    """The ``.buffer`` directory beside the log, when its directory's listing
    has one (shared sample buffers live under ``.buffer/<stem>/``)."""

    shard: str | None = None
    """The shard directory name ``<k>`` of a shard attempt."""


class ShardFiles(NamedTuple):
    """One ``<name>.shards/<k>/`` directory's attempts."""

    name: str
    """The directory name, ``<k>``."""

    attempts: list[LogFile]
    """Its ``.eval`` files in attempt order; the last is current."""


class ShardSetFiles(NamedTuple):
    """A ``<name>.shards/`` companion with at least one shard attempt."""

    location: str
    """The companion directory."""

    path: str
    """The companion's path relative to the root, with ``/`` separators."""

    shards: list[ShardFiles]
    """The shard directories holding an attempt, in shard order."""

    merged: list[LogFile]
    """The merged logs beside the companion (``<name>.eval`` and
    ``<name>-recovered.eval``) in attempt order; the last is current."""

    stray: list[StrayFile]
    """Logs in the companion that are not shard attempts."""


class LogDirListing(NamedTuple):
    """Result of :func:`walk_log_dir`."""

    eval_files: list[LogFile]
    """The ``.eval`` logs outside shard sets, sorted by location."""

    json_logs: list[str]
    """``.json`` logs, which this mode does not read (the format is deprecated)."""

    shard_sets: list[ShardSetFiles]
    """The shard sets, sorted by location."""

    stray: list[StrayFile]
    """Stray logs in companions that hold no shard attempt."""


async def walk_log_dir(fs: AsyncFilesystem, root: str) -> LogDirListing:
    """List the logs under ``root``, one delimited listing per directory.

    The first ``<name>.shards/`` directory on each path below ``root`` is a
    shard set: its shards and stray logs come from the shared shard-set walk,
    and the merged log beside it (``<name>.eval`` or
    ``<name>-recovered.eval``) belongs to it rather than being an ordinary
    log. A companion with no shard attempt is not a shard set, and its merged
    log is an ordinary log. Directories in a companion that the shard-set
    walk does not list are walked as ordinary directories, in which a nested
    ``*.shards/`` is an ordinary directory too, so every log below ``root``
    is either a shard path or an ordinary log (see
    :func:`~inspect_ai.log._shards._walk.is_shard_path`).

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
    shard_sets: list[ShardSetFiles] = []
    stray: list[StrayFile] = []

    async def visit(directory: str, is_root: bool, in_companion: bool) -> None:
        try:
            async with limiter:
                listing = await fs.list_dir(directory)
        except FileNotFoundError:
            if is_root:
                raise
            return
        buffer_dir = next((d for d in listing.dirs if basename(d) == _BUFFER_DIR), None)
        files: list[LogFile] = []
        for info in listing.files:
            name = basename(info.name)
            if name.endswith(f".{EVAL_LOG_FORMAT}"):
                files.append(_log_file(info, buffer_dir=buffer_dir))
            elif is_log_file(name, [".json"]):
                json_logs.append(info.name)
        companions = (
            [] if in_companion else [d for d in listing.dirs if _is_companion(d)]
        )
        merged = {
            companion: [
                f for f in files if log_basename(f.name) == _set_name(companion)
            ]
            for companion in companions
        }
        claimed = {f.location for logs in merged.values() for f in logs}
        eval_files.extend(f for f in files if f.location not in claimed)
        subdirs = [d for d in listing.dirs if d not in merged and _descend(basename(d))]
        await tg_collect(
            [functools.partial(visit, d, False, in_companion) for d in subdirs]
            + [functools.partial(visit_companion, c, merged[c]) for c in companions]
        )

    async def visit_companion(companion: str, merged: list[LogFile]) -> None:
        listing = await list_shard_set(fs, companion, limiter=limiter)
        shards = [_shard_files(shard) for shard in listing.shards if shard.attempts]
        if shards:
            shard_sets.append(
                ShardSetFiles(
                    location=companion,
                    path=_relative(root, companion),
                    shards=shards,
                    merged=sorted(merged, key=attempt_order),
                    stray=listing.stray,
                )
            )
        else:
            eval_files.extend(merged)
            stray.extend(listing.stray)
        await tg_collect(
            [
                functools.partial(visit, d, False, True)
                for d in listing.unlisted_dirs
                if _descend(basename(d))
            ]
        )

    await visit(root, True, False)
    eval_files.sort(key=lambda f: f.location)
    json_logs.sort()
    shard_sets.sort(key=lambda s: s.location)
    stray.sort(key=lambda s: s.path)
    return LogDirListing(
        eval_files=eval_files, json_logs=json_logs, shard_sets=shard_sets, stray=stray
    )


def attempt_order(file: LogFile) -> AttemptSortKey:
    """The shared attempt order (see :func:`~inspect_ai.log._shards._walk.attempt_sort_key`)."""
    return attempt_sort_key(
        FileInfo(name=file.location, type="file", size=file.size, mtime=file.mtime)
    )


def basename(location: str) -> str:
    """A listed path's final name, percent-decoded for a ``file://`` URI."""
    return local_path(location).replace("\\", "/").rsplit("/", 1)[-1]


def _descend(name: str) -> bool:
    """Whether the walk lists a subdirectory with this name."""
    return name != _BUFFER_DIR and not name.endswith(_CHECKPOINTS_SUFFIX)


def _is_companion(directory: str) -> bool:
    name = basename(directory)
    return name.endswith(_SHARDS_SUFFIX) and name != _SHARDS_SUFFIX


def _set_name(companion: str) -> str:
    """``<name>`` of a ``<name>.shards`` companion."""
    return basename(companion)[: -len(_SHARDS_SUFFIX)]


def _log_file(
    info: FileInfo, *, buffer_dir: str | None, shard: str | None = None
) -> LogFile:
    return LogFile(
        location=info.name,
        name=basename(info.name),
        size=info.size,
        mtime=info.mtime / 1000 if info.mtime is not None else None,
        etag=info.etag,
        buffer_dir=buffer_dir,
        shard=shard,
    )


def _shard_files(shard: ShardDir) -> ShardFiles:
    buffer_dir = f"{shard.dir}/{_BUFFER_DIR}" if shard.has_buffer else None
    return ShardFiles(
        name=shard.name,
        attempts=[
            _log_file(info, buffer_dir=buffer_dir, shard=shard.name)
            for info in shard.attempts
        ],
    )


def _relative(root: str, location: str) -> str:
    """``location``'s path below ``root``, with ``/`` separators."""
    root = root.replace("\\", "/").rstrip("/")
    location = location.replace("\\", "/")
    if location.startswith(f"{root}/"):
        return location[len(root) + 1 :]
    return location
