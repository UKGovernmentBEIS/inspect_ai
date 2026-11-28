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
from inspect_ai._util.asyncfiles import (
    AsyncFilesystem,
    DirListing,
    is_s3_filename,
    s3_bucket_and_key,
)
from inspect_ai._util.constants import EVAL_LOG_FORMAT
from inspect_ai._util.file import FileInfo, basename, local_path
from inspect_ai._util.log_layout import _RECOVERED_SUFFIX
from inspect_ai.log._file import _timestamp_prefix_re, is_log_file

from ._errors import ShardSetError

# Shard directory listings in flight at once.
_MAX_CONCURRENT_LISTINGS = 32

_BUFFER_DIR = ".buffer"
_EVAL_SUFFIX = f".{EVAL_LOG_FORMAT}"
_NO_TIMESTAMP = datetime.min.replace(tzinfo=timezone.utc)

_ROOT_LOG = "log directly in the shards directory, not in a shard directory"
_NOT_A_SHARD = "directory not named with digits only, which is not a shard directory"
_JSON_LOG = "json log in a shard directory; shards must be eval logs"


def check_s3_location(location: str, error: type[Exception] = ValueError) -> None:
    """Refuse an S3 URL that the S3 helpers would read as another key.

    They take the bucket and key with `urlparse`, which drops a `#` or `?`
    and the text after it, removes tab, CR and LF characters, and strips
    leading slashes from the key: `s3://bucket/logs/run#tag.eval` would
    read, write and delete `logs/run`. Other locations are not checked.

    Raises:
        Exception: `error`, when `location` is such an S3 URL.
    """
    if not is_s3_filename(location):
        return
    bucket, key = s3_bucket_and_key(location)
    if f"s3://{bucket}/{key}" != location:
        raise error(
            f"{location} cannot be used: S3 would read it as s3://{bucket}/{key}. "
            "A '#' or '?' (and the text after it), a tab or line break, or a "
            "leading '/' in the key is lost. Rename it."
        )


class StrayFile(NamedTuple):
    """A log file or directory in a shard set that is not a shard attempt."""

    path: str
    """Path or URL, in the form the shards directory was given in."""

    reason: str
    """Why it is not an attempt."""


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
    """The shard directories, in numeric order."""

    stray: list[StrayFile]
    """Log files that are not attempts and directories that are not shard
    directories, sorted by path."""


class AttemptSortKey(NamedTuple):
    """Sort key for a shard's attempt files (see :func:`attempt_sort_key`)."""

    timestamped: bool
    created: datetime
    recovered: bool
    mtime: float


async def list_shard_set(
    fs: AsyncFilesystem,
    shards_dir: str,
    *,
    limiter: anyio.CapacityLimiter | None = None,
) -> ShardSetListing:
    """List a shards directory and each shard directory directly under it.

    A shard directory, ``<k>/``, is named with ASCII digits only (the shard
    number a launcher assigns). ``shards_dir`` is listed once, then each
    ``<k>/``, at most 32 at a time (or as many as ``limiter`` allows);
    nothing deeper is listed. In a ``<k>/``, ``.eval`` files are attempts, a
    ``.buffer/`` directory sets ``has_buffer``, and every other entry is
    ancillary.

    Stray entries are a log directly in ``shards_dir``, a ``.json`` log in a
    ``<k>/``, and every other directory in ``shards_dir``, which is not
    listed.

    A missing local ``shards_dir`` and an empty S3 prefix both list as empty.
    A ``<k>/`` with nothing in it is left out, so an empty local directory, a
    directory removed during the walk, and an S3 prefix emptied during the
    walk give the same listing.

    ``shards_dir`` and every name a listing returns are checked before
    anything listed is filtered or listed further: with
    :func:`check_s3_location`, so a name S3 would read as another key is
    never dropped as empty or read in place of another, and as a non-empty
    name directly in the directory listed. S3 and other remote backends list
    a key with an empty path component (``run.shards//x.eval``) as the
    directory listed, which would otherwise hide it.

    Args:
        fs: Filesystem to list with.
        shards_dir: The ``<name>.shards`` directory: a path, ``file://`` URI
            or ``s3://`` URL. Returned paths keep this form.
        limiter: Bounds every listing, the first included, so a caller
            walking several companions can keep one cap across them.

    Raises:
        ShardSetError: ``shards_dir`` or a listed name is an S3 URL that S3
            would read as another key, or a listed name is not directly in
            the directory listed.
    """
    if limiter is None:
        limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_LISTINGS)
    check_s3_location(shards_dir, ShardSetError)
    try:
        async with limiter:
            listing = await fs.list_dir(shards_dir, indirect_error=ShardSetError)
    except FileNotFoundError:
        return ShardSetListing(shards=[], stray=[])
    _check_listed(shards_dir, listing)

    stray = [
        StrayFile(path=info.name, reason=_ROOT_LOG)
        for info in listing.files
        if _is_log(_name(info.name))
    ]
    shard_dirs: list[str] = []
    for directory in listing.dirs:
        if _is_number(raw_name(directory)):
            shard_dirs.append(directory)
        else:
            stray.append(StrayFile(path=directory, reason=_NOT_A_SHARD))

    async def list_child(directory: str) -> ShardDir | None:
        try:
            async with limiter:
                child = await fs.list_dir(directory, indirect_error=ShardSetError)
        except FileNotFoundError:
            return None
        _check_listed(directory, child)
        if not child.files and not child.dirs:
            return None
        attempts: list[FileInfo] = []
        ancillary: list[str] = []
        for info in child.files:
            name = _name(info.name)
            if name.endswith(_EVAL_SUFFIX):
                attempts.append(info)
            elif _is_log(name):
                stray.append(StrayFile(path=info.name, reason=_JSON_LOG))
            else:
                ancillary.append(info.name)
        has_buffer = False
        for subdir in child.dirs:
            if _name(subdir) == _BUFFER_DIR:
                has_buffer = True
            else:
                ancillary.append(subdir)
        attempts.sort(key=attempt_sort_key)
        return ShardDir(
            name=_name(directory),
            dir=directory,
            attempts=attempts,
            has_buffer=has_buffer,
            ancillary=sorted(ancillary),
        )

    listed = await tg_collect([functools.partial(list_child, d) for d in shard_dirs])
    shards = sorted((s for s in listed if s is not None), key=_shard_sort_key)
    stray.sort(key=lambda s: s.path)
    return ShardSetListing(shards=shards, stray=stray)


def _check_listed(base: str, listing: DirListing) -> None:
    for location in [*listing.dirs, *(info.name for info in listing.files)]:
        check_s3_location(location, ShardSetError)
        parent, _, name = location.rpartition("/")
        if base.startswith("file://"):
            # a file:// child is built from its local path (see list_dir)
            direct = local_path(parent) == local_path(base.rstrip("/"))
        else:
            direct = parent == base.rstrip("/")
        if not name or not direct:
            raise ShardSetError(
                f"{base} lists {location}, which is not a file or directory "
                "directly in it: S3 lists a key with an empty path component "
                "('//') this way. Rename it."
            )


def raw_name(location: str) -> str:
    """A listed location's last component as the backend named it.

    Unlike :func:`_name`, a backslash is kept rather than read as a
    separator. A ``file://`` URI's name is percent-decoded.
    """
    if location.startswith("file://"):
        return os.path.basename(local_path(location))
    return location.rpartition("/")[2]


def _is_number(name: str) -> bool:
    return name.isascii() and name.isdigit()


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
    return AttemptSortKey(True, created, is_recovered_attempt(info), mtime)


def is_recovered_attempt(info: FileInfo) -> bool:
    """Whether an attempt's file name ends in ``-recovered.eval``, timestamped or not."""
    return _name(info.name).removesuffix(_EVAL_SUFFIX).endswith(_RECOVERED_SUFFIX)


def _shard_sort_key(shard: ShardDir) -> tuple[int, str]:
    """Order shard directories numerically, then by name (``010`` and ``10``)."""
    return (int(shard.name), shard.name)


def _is_log(name: str) -> bool:
    return is_log_file(name, [".json"])


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
