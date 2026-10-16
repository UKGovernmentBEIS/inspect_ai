"""Deleting a merged log's shards.

The caller must be the only process operating on the log and its shards
directory: no worker still writing, no other merge or deletion. Nothing is
guaranteed otherwise. An interrupted deletion leaves objects behind and
reports them; running it again, or deleting the directory by hand, finishes
it.
"""

import functools
import os
import re
from contextlib import suppress
from typing import NamedTuple

import anyio

from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import AsyncFilesystem, is_s3_filename
from inspect_ai._util.file import FileInfo, local_path
from inspect_ai._util.log_layout import eval_shards_dir

from ._errors import ShardSetError
from ._publish import is_local
from ._walk import attempt_sort_key

_MAX_CONCURRENT_DELETES = 16
_BUFFER_DIR = ".buffer"
_CHECKPOINTS_SUFFIX = ".checkpoints"


class _Objects(NamedTuple):
    """The objects under a shards directory, by kind."""

    superseded: list[str]
    """Shard attempts other than each shard's current one, and buffer objects."""

    current: list[str]
    """Each shard's current attempt."""

    other: list[str]
    """Everything that is not a shard file or in a checkpoint directory."""


async def remove_shards_dir(
    log: str, *, include_log: bool = False, fs: AsyncFilesystem | None = None
) -> None:
    """Delete the shard files of the merged log `log`.

    The shard files are the ``.eval`` files directly in a ``<k>/`` shard
    directory and the objects under its ``.buffer/``. Checkpoint directories
    (``<k>/<shard>.checkpoints/``) are left in place, so the shards directory
    may remain holding only them. Superseded attempts and buffers are deleted
    before any shard's current attempt, so an interrupted deletion leaves
    every shard either unchanged or without an attempt.

    Args:
        log: The merged log ``<dir>/<name>.eval``.
        include_log: Delete the merged log too, before the shards.
        fs: Filesystem to use (a new one when omitted).

    Raises:
        ShardSetError: The shards directory holds another object (scan
            results, a file directly in it or in a directory whose name
            starts with ``.``, any file that is not a shard file), and
            nothing was deleted; or objects are left after the deletion
            (a failed delete, a file written meanwhile), each named.
    """
    if fs is None:
        async with AsyncFilesystem() as owned:
            await remove_shards_dir(log, include_log=include_log, fs=owned)
        return

    shards_dir = eval_shards_dir(log)
    objects = await _list_objects(fs, shards_dir)
    if objects.other:
        raise ShardSetError(
            f"{shards_dir} holds objects that are not shard files, so its shards "
            f"were not deleted: {', '.join(objects.other)}. Move or remove them, "
            "then try again."
        )
    if include_log:
        with suppress(FileNotFoundError):
            await fs.delete_file(log)
    failure = await _delete_all(fs, objects.superseded)
    if failure is None:
        failure = await _delete_all(fs, objects.current)

    left = await _list_objects(fs, shards_dir)
    if is_local(shards_dir):
        await anyio.to_thread.run_sync(_remove_empty_dirs, local_path(shards_dir))
    remaining = left.superseded + left.current + left.other
    if remaining:
        raise ShardSetError(
            f"Deleting the shards in {shards_dir} did not finish; these remain: "
            f"{', '.join(remaining)}. Run the deletion again, or delete "
            f"{shards_dir} by hand."
        ) from failure


async def _delete_all(fs: AsyncFilesystem, paths: list[str]) -> Exception | None:
    """Delete `paths`, returning the first failure (every delete is attempted)."""
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_DELETES)

    async def delete(path: str) -> Exception | None:
        async with limiter:
            try:
                await fs.delete_file(path)
            except FileNotFoundError:
                pass
            except Exception as ex:
                return ex
        return None

    failures = await tg_collect([functools.partial(delete, p) for p in paths])
    return next((f for f in failures if f is not None), None)


async def _list_objects(fs: AsyncFilesystem, shards_dir: str) -> _Objects:
    files: list[FileInfo] = []
    if not is_local(shards_dir) or os.path.isdir(local_path(shards_dir)):
        # local listings come back as file:// URIs; keep a plain path plain
        plain = "://" not in shards_dir
        files = [
            info.model_copy(update={"name": local_path(info.name)}) if plain else info
            async for info in fs.iter_files(shards_dir, recursive=True, detail=True)
        ]
    attempts: dict[str, list[FileInfo]] = {}
    superseded: list[str] = []
    other: list[str] = []
    for info in files:
        parts = _relative_parts(shards_dir, info.name)
        if len(parts) < 2 or parts[0].startswith("."):
            other.append(info.name)
        elif len(parts) == 2:
            if parts[1].endswith(".eval"):
                attempts.setdefault(parts[0], []).append(info)
            else:
                other.append(info.name)
        elif parts[1] == _BUFFER_DIR:
            superseded.append(info.name)
        elif not parts[1].endswith(_CHECKPOINTS_SUFFIX):
            other.append(info.name)
    current: list[str] = []
    for shard_attempts in attempts.values():
        shard_attempts.sort(key=attempt_sort_key)
        superseded.extend(a.name for a in shard_attempts[:-1])
        current.append(shard_attempts[-1].name)
    return _Objects(sorted(superseded), sorted(current), sorted(other))


def _relative_parts(base: str, path: str) -> list[str]:
    if is_s3_filename(base):
        prefix = base.rstrip("/") + "/"
        relative = path[len(prefix) :] if path.startswith(prefix) else path
    else:
        relative = os.path.relpath(
            os.path.abspath(local_path(path)), os.path.abspath(local_path(base))
        )
    return [part for part in re.split(r"[/\\]", relative) if part]


def _remove_empty_dirs(shards_dir: str) -> None:
    """Remove empty directories under `shards_dir`, and it when empty.

    Checkpoint directories and everything in them are left alone.
    """
    if not os.path.isdir(shards_dir):
        return
    for dirpath, _, _ in os.walk(shards_dir, topdown=False):
        parts = _relative_parts(shards_dir, dirpath)
        if len(parts) >= 2 and parts[1].endswith(_CHECKPOINTS_SUFFIX):
            continue
        with suppress(OSError):
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
