"""Deleting a merged log's shards directory.

The caller must be the only process operating on the log and its shards
directory: no worker still writing, no other merge or deletion. Nothing is
guaranteed otherwise. An interrupted deletion leaves objects behind; running
it again, or deleting the directory by hand, finishes it.
"""

import re
import shutil
from contextlib import suppress
from functools import partial
from typing import Any

import anyio

from inspect_ai._util._async import current_async_backend
from inspect_ai._util.asyncfiles import (
    AsyncFilesystem,
    s3_bucket_and_key,
)
from inspect_ai._util.file import local_path
from inspect_ai._util.log_layout import eval_shards_dir

from ._errors import ShardSetError
from ._publish import check_supported_location, is_local

# fsspec expands these in paths it deletes, also inside a recursive delete
_GLOB_CHARS = re.compile(r"[*?[]")


async def remove_shards_dir(
    log: str, *, include_log: bool = False, fs: AsyncFilesystem | None = None
) -> None:
    """Delete the shards directory of the merged log `log`.

    Everything under ``<name>.shards/`` is deleted: shard attempts, sample
    buffers, checkpoint directories, S3 folder markers and any other object.
    On S3 the objects are listed and deleted with the `AsyncFilesystem`
    client (s3fs is not supported under a configured Trio backend), then
    checked by a fresh listing. A missing directory is not an error.

    Args:
        log: The merged log ``<dir>/<name>.eval``.
        include_log: Delete the merged log too, before the shards.
        fs: Filesystem to use (a new one when omitted).

    Raises:
        ValueError: `log` is not a local path, ``file://`` URI or ``s3://``
            URL (see :func:`check_supported_location`), or is an S3 URL that
            holds glob characters (see :func:`check_deletable`); nothing is
            deleted.
        ShardSetError: S3 reported an object it did not delete, or objects
            remain under the shards directory after the delete returned.
    """
    check_supported_location(log)
    check_deletable(log)
    if fs is None:
        async with AsyncFilesystem() as owned:
            await remove_shards_dir(log, include_log=include_log, fs=owned)
        return

    if is_local(log):
        log = local_path(log)
    shards_dir = eval_shards_dir(log)
    if include_log:
        with suppress(FileNotFoundError):
            await fs.delete_file(log)
    if is_local(shards_dir):
        await anyio.to_thread.run_sync(_remove_local_dir, shards_dir)
        return
    bucket, prefix = s3_bucket_and_key(shards_dir)
    # boto3, not fsspec, so a worker thread is safe
    await anyio.to_thread.run_sync(
        _remove_s3_prefix, fs.s3_client(), bucket, prefix.rstrip("/") + "/"
    )
    # a bulk delete can return normally while objects remain
    remnant = await _remnant(fs, shards_dir)
    if remnant is not None:
        raise ShardSetError(
            f"Deleting {shards_dir} left objects behind (for example "
            f"{remnant}). Delete them, or merge again with delete_shards."
        )


def check_deletable(log: str) -> None:
    """Refuse to delete the shards of a remote `log` whose URL holds glob characters.

    fsspec expands `*`, `?` and `[` in the paths it deletes, so deleting
    `run?.shards` would also delete `run1.shards`. Local paths are deleted by
    their exact path and are not refused.

    Raises:
        ValueError: `log` is remote and holds `*`, `?` or `[`.
    """
    if not is_local(log) and _GLOB_CHARS.search(log):
        raise ValueError(
            f"Cannot delete the shards of {log}: its location holds a glob "
            "character (*, ? or [), which the storage backend would expand to "
            "other paths. Delete the shards directory by hand."
        )


async def _remnant(fs: AsyncFilesystem, shards_dir: str) -> str | None:
    """An object still under the S3 `shards_dir`, from a fresh listing.

    One list-objects call for the prefix, limited to one key and unfiltered,
    so a folder marker (a key ending in `/`) counts: the `AsyncFilesystem`
    listings skip markers.
    """
    bucket, prefix = s3_bucket_and_key(shards_dir)
    list_first = dict(Bucket=bucket, Prefix=prefix.rstrip("/") + "/", MaxKeys=1)
    if current_async_backend() == "asyncio":
        client = await fs.s3_client_async()
        response = await client.list_objects_v2(**list_first)
    else:
        response = await anyio.to_thread.run_sync(
            partial(fs.s3_client().list_objects_v2, **list_first)
        )
    keys = [obj["Key"] for obj in response.get("Contents", [])]
    return f"s3://{bucket}/{keys[0]}" if keys else None


def _remove_s3_prefix(s3: Any, bucket: str, prefix: str) -> None:
    """Delete every key under `prefix`, folder markers (keys ending in `/`) included.

    Each listed page (at most 1000 keys, the `DeleteObjects` limit) is
    deleted before the next is listed.
    """
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys = [obj["Key"] for obj in page.get("Contents", [])]
        if keys:
            _delete_s3_keys(s3, bucket, keys)


def _delete_s3_keys(s3: Any, bucket: str, keys: list[str]) -> None:
    """Delete `keys` with one `DeleteObjects` call, raising on a per-object error."""
    response = s3.delete_objects(
        Bucket=bucket,
        Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
    )
    errors = response.get("Errors", [])
    if errors:
        first = errors[0]
        raise ShardSetError(
            f"Deleting s3://{bucket}/{first['Key']} failed ({first.get('Code')}: "
            f"{first.get('Message')}); {len(errors)} objects were not deleted. "
            "Delete them, or merge again with delete_shards."
        )


def _remove_local_dir(path: str) -> None:
    with suppress(FileNotFoundError):
        shutil.rmtree(path)
