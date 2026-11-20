"""Deletion of a merged log's ``<name>.shards/`` companion.

The merge owns deletion (see :func:`merge_eval_log_shards` with
``delete_shards=True``): it lists the companion under its lock before the
pass, and deletes what that listing found only once the pass has left a
``success`` merged log. Nothing is deleted by prefix, so no name absent from
the listing is deleted.
"""

import errno
import functools
import os
from collections.abc import Iterable, Sequence
from typing import NamedTuple

import anyio
from botocore.exceptions import BotoCoreError, ClientError

from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import AsyncFilesystem, is_s3_filename

from ._errors import ShardSetError
from ._owned import run_owned
from ._walk import check_s3_location

# Deletes in flight at once.
_MAX_CONCURRENT_DELETES = 32

# Entries named when a confirming listing finds some left.
_MAX_LEFT_SHOWN = 10

_RERUN = (
    "Run the merge again with delete_shards=True (--delete-shards on the "
    "command line) to finish deleting the shards."
)


class Companion(NamedTuple):
    """A listing of a ``<name>.shards/`` companion (see :func:`list_companion`)."""

    files: list[str]
    """Locally every entry that is not a directory (symbolic links
    included); on S3 every object, directory markers included."""

    dirs: list[str]
    """Local directories, the companion included, deepest first. Empty on
    S3."""


async def list_companion(fs: AsyncFilesystem, shards_dir: str) -> Companion:
    """List everything in `shards_dir`, recursively.

    Locally the walk does not follow symbolic links. On S3 every object
    under ``<shards_dir>/`` is listed, directory markers included, and every
    name must pass :func:`check_s3_location`. A missing companion lists as
    empty.

    Raises:
        ShardSetError: A local `shards_dir` is a symbolic link, or an S3 name
            is one that S3 would read as another key.
    """
    if is_s3_filename(shards_dir):
        keys = await fs.list_s3_keys(shards_dir)
        for key in keys:
            check_s3_location(key, ShardSetError)
        return Companion(files=sorted(keys), dirs=[])
    if os.path.islink(shards_dir):
        raise ShardSetError(
            f"{shards_dir} is a symbolic link, which the merge does not delete "
            "through. Merge the log beside the directory it points to, or delete "
            "the shards by hand."
        )
    return await run_owned(functools.partial(_walk_local, shards_dir))


async def delete_companion(
    fs: AsyncFilesystem,
    shards_dir: str,
    listed: Companion,
    current: Iterable[tuple[str, str]],
) -> None:
    """Delete the entries of `listed`, then confirm that `shards_dir` is empty.

    Every entry is deleted by its own name, the shards' current attempts
    after all the others, so an interruption leaves each shard with its
    current attempt or none. A current attempt is a listed file whose last
    two path components are one of the ledger's (shard, log) pairs in
    `current`. Local directories are then removed deepest first, each only
    if empty. An entry already gone counts as deleted.

    Raises:
        ShardSetError: Something is left in `shards_dir`.
        OSError, BotoCoreError, ClientError: A delete failed; the error notes
            that the merge can be run again to finish.
    """
    pairs = set(current)
    first: list[str] = []
    last: list[str] = []
    for name in listed.files:
        (last if tuple(name.rsplit("/", 2)[-2:]) in pairs else first).append(name)
    try:
        await _delete_files(fs, first)
        await _delete_files(fs, last)
        if listed.dirs:
            await run_owned(functools.partial(_remove_dirs, listed.dirs))
        left = await _left(fs, shards_dir)
    except (OSError, BotoCoreError, ClientError) as ex:
        ex.add_note(_RERUN)
        raise
    if left:
        shown = ", ".join(left[:_MAX_LEFT_SHOWN])
        more = (
            f" and {len(left) - _MAX_LEFT_SHOWN} more"
            if len(left) > _MAX_LEFT_SHOWN
            else ""
        )
        raise ShardSetError(
            f"{shards_dir} is not empty after its shards were deleted: it holds "
            f"{shown}{more}, written after the merge listed the shards. {_RERUN}"
        )


async def _delete_files(fs: AsyncFilesystem, files: Sequence[str]) -> None:
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_DELETES)

    async def delete(name: str) -> None:
        async with limiter:
            if is_s3_filename(name):
                await fs.delete_file(name)
            else:
                await run_owned(functools.partial(_unlink, name))

    await tg_collect([functools.partial(delete, name) for name in files])


async def _left(fs: AsyncFilesystem, shards_dir: str) -> list[str]:
    """What a confirming listing finds in `shards_dir`."""
    if is_s3_filename(shards_dir):
        return sorted(await fs.list_s3_keys(shards_dir))
    if os.path.islink(shards_dir):
        return [shards_dir]
    left = await run_owned(functools.partial(_walk_local, shards_dir))
    # the directories that hold a file left are not named
    return left.files or sorted(d for d in left.dirs if d != shards_dir)


def _walk_local(root: str) -> Companion:
    """Walk `root` without following symbolic links; a missing `root` is empty."""
    files: list[str] = []
    dirs: list[str] = []

    def walk(directory: str) -> None:
        try:
            with os.scandir(directory) as scan:
                entries = list(scan)
        except FileNotFoundError:
            return
        for entry in entries:
            path = f"{directory}/{entry.name}"
            if entry.is_dir(follow_symlinks=False):
                walk(path)
            else:
                files.append(path)
        # after its contents, so the list is deepest first
        dirs.append(directory)

    walk(root)
    return Companion(files=sorted(files), dirs=dirs)


def _unlink(path: str) -> None:
    """Remove a file, or a symbolic link as a link; a missing entry counts as deleted."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _remove_dirs(dirs: Sequence[str]) -> None:
    """Remove each directory, in order, if it is empty."""
    for directory in dirs:
        try:
            os.rmdir(directory)
        except FileNotFoundError:
            pass
        except OSError as ex:
            if ex.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                raise
