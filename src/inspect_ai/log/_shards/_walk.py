"""The shard-set walk: list a ``<name>.shards/`` companion and order its attempts.

A companion holds one directory per shard, ``<name>.shards/<k>/``, each with
the shard's ``.eval`` attempt files. These rules are written once for the merge
and ``inspect ctl --log-dir``, so the two agree on what a shard set holds.
"""

import functools
import os
import re
from datetime import datetime, timezone
from typing import NamedTuple

import anyio

from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import EVAL_LOG_FORMAT
from inspect_ai._util.file import FileInfo, basename, local_path
from inspect_ai._util.log_layout import _RECOVERED_SUFFIX, _SHARDS_SUFFIX
from inspect_ai.log._file import _timestamp_prefix_re, is_log_file

# Shard directory listings in flight at once.
_MAX_CONCURRENT_LISTINGS = 32

_BUFFER_DIR = ".buffer"
_EVAL_SUFFIX = f".{EVAL_LOG_FORMAT}"
_NO_TIMESTAMP = datetime.min.replace(tzinfo=timezone.utc)


class StrayFile(NamedTuple):
    """A log file in a shard set that is not a shard attempt."""

    path: str
    """Path or URL, in the form the shards directory was given in."""

    reason: str
    """Why the file is not an attempt."""


class ShardDir(NamedTuple):
    """One shard's directory, ``<name>.shards/<k>/``."""

    name: str
    """The directory name, ``<k>``."""

    dir: str
    """Path or URL, in the form the shards directory was given in."""

    attempts: list[FileInfo]
    """The ``.eval`` files, in attempt order (see :func:`attempt_sort_key`)."""

    has_buffer: bool
    """Whether the directory has a ``.buffer/`` sample buffer."""

    ancillary: list[str]
    """Paths of every other file and directory, sorted (for example
    ``scans/`` or ``<shard>.checkpoints/``). Not listed further."""

    @property
    def current(self) -> FileInfo | None:
        """The last attempt, or ``None`` when there is none."""
        return self.attempts[-1] if self.attempts else None


class ShardSetListing(NamedTuple):
    """Result of :func:`list_shard_set`."""

    shards: list[ShardDir]
    """The shard directories, sorted by name."""

    stray: list[StrayFile]
    """Log files that are not attempts, sorted by path."""


class AttemptSortKey(NamedTuple):
    """Sort key for a shard's attempt files (see :func:`attempt_sort_key`)."""

    timestamped: bool
    created: datetime
    recovered: bool
    mtime: float


async def list_shard_set(fs: AsyncFilesystem, shards_dir: str) -> ShardSetListing:
    """List a shards directory and each of its shard directories.

    ``shards_dir`` is listed once, then each ``<k>/`` directory, at most 32 at
    a time. In ``<k>/``, ``.eval`` files are attempts, a ``.buffer/``
    directory sets ``has_buffer``, and every other entry is ancillary. A
    directory whose name starts with ``.`` is not a shard. An ``.eval`` file
    directly in ``shards_dir``, and a ``.json`` log in a ``<k>/``, are stray.

    A missing local ``shards_dir`` and an empty S3 prefix both list as empty.
    A ``<k>/`` directory removed during the walk is left out.

    Args:
        fs: Filesystem to list with.
        shards_dir: The ``<name>.shards`` directory: a path, ``file://`` URI
            or ``s3://`` URL. Returned paths keep this form.
    """
    try:
        listing = await fs.list_dir(shards_dir)
    except FileNotFoundError:
        return ShardSetListing(shards=[], stray=[])

    stray = [
        StrayFile(
            path=info.name,
            reason="eval log directly in the shards directory, not in a shard directory",
        )
        for info in listing.files
        if _name(info.name).endswith(_EVAL_SUFFIX)
    ]
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_LISTINGS)

    async def list_shard(shard_dir: str) -> ShardDir | None:
        try:
            async with limiter:
                shard_listing = await fs.list_dir(shard_dir)
        except FileNotFoundError:
            return None
        attempts: list[FileInfo] = []
        ancillary: list[str] = []
        for info in shard_listing.files:
            name = _name(info.name)
            if name.endswith(_EVAL_SUFFIX):
                attempts.append(info)
            elif is_log_file(name, [".json"]):
                stray.append(
                    StrayFile(
                        path=info.name,
                        reason="json log in a shard directory; shards must be eval logs",
                    )
                )
            else:
                ancillary.append(info.name)
        has_buffer = False
        for subdir in shard_listing.dirs:
            if _name(subdir) == _BUFFER_DIR:
                has_buffer = True
            else:
                ancillary.append(subdir)
        attempts.sort(key=attempt_sort_key)
        return ShardDir(
            name=_name(shard_dir),
            dir=shard_dir,
            attempts=attempts,
            has_buffer=has_buffer,
            ancillary=sorted(ancillary),
        )

    shard_dirs = [d for d in listing.dirs if not _name(d).startswith(".")]
    listed = await tg_collect([functools.partial(list_shard, d) for d in shard_dirs])
    shards = sorted((s for s in listed if s is not None), key=lambda s: s.name)
    stray.sort(key=lambda s: s.path)
    return ShardSetListing(shards=shards, stray=stray)


def attempt_sort_key(info: FileInfo) -> AttemptSortKey:
    """Sort key that puts a shard's attempt files in attempt order.

    Orders by the ``{created}`` timestamp prefix of the file name, parsed as
    a datetime; then a ``-recovered`` copy after the file it was recovered
    from (recovery keeps the original's name and adds the buffered samples);
    then mtime. Names with no parseable timestamp sort by mtime alone, before
    timestamped ones. Mtime comes last because a running attempt's mtime
    moves on every flush. The timestamp is read as UTC, the zone the recorder
    names files in; any offset after it is ignored, since file names replace
    its ``+`` with ``-``.
    """
    name = _name(info.name)
    mtime = info.mtime or 0.0
    created = _parse_timestamp_prefix(name)
    if created is None:
        return AttemptSortKey(False, _NO_TIMESTAMP, False, mtime)
    stem = name.removesuffix(_EVAL_SUFFIX)
    return AttemptSortKey(True, created, stem.endswith(_RECOVERED_SUFFIX), mtime)


def is_shard_path(root: str, path: str) -> bool:
    """Whether ``path`` is inside a ``<name>.shards/`` directory below ``root``.

    Only the directory components of ``path`` relative to ``root`` count, so
    the logs of a root that is itself a shard directory are not shards of it.
    ``root`` and ``path`` may each be a plain path, ``file://`` URI or remote
    URL; local forms are compared as absolute paths.

    Raises:
        ValueError: If ``path`` is not below ``root``.
    """
    root_parts = _location_parts(root)
    path_parts = _location_parts(path)
    if path_parts[: len(root_parts)] != root_parts:
        raise ValueError(f"{path} is not below {root}")
    directories = path_parts[len(root_parts) : -1]
    return any(
        part.endswith(_SHARDS_SUFFIX) and part != _SHARDS_SUFFIX for part in directories
    )


def _name(location: str) -> str:
    """A listed path's final name, percent-decoded for a ``file://`` URI."""
    return basename(local_path(location))


def _parse_timestamp_prefix(name: str) -> datetime | None:
    match = _timestamp_prefix_re.match(name)
    if match is None:
        return None
    try:
        digits = re.sub("[:-]", "", match.group(0))
        return datetime.strptime(f"{digits}+0000", "%Y%m%dT%H%M%S%z")
    except ValueError:
        return None


def _location_parts(location: str) -> list[str]:
    """The protocol and path components of a location.

    Local locations (plain paths and ``file://`` URIs) share the protocol
    ``""`` and are made absolute, so both forms compare equal.
    """
    if "://" in location and not location.startswith("file://"):
        protocol, rest = location.split("://", 1)
        return [f"{protocol}://", *_split(rest)]
    return ["", *_split(os.path.abspath(local_path(location)))]


def _split(path: str) -> list[str]:
    return [part for part in re.split(r"[/\\]", path) if part]
