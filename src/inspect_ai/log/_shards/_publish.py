"""Overlap guards and publication of the merged log.

Callers serialise merges of one log; these guards turn a broken contract
into a refused publish. A local merged log is guarded by a lock file beside
it, an S3 one by a conditional upload against the ETag the merge read. Other
backends publish unconditionally and rely on the contract alone.
"""

import os
import shutil
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import BinaryIO

import anyio

from inspect_ai._util.asyncfiles import AsyncFilesystem, is_s3_filename
from inspect_ai._util.atomic_write import atomic_write
from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.file import acquire_exclusive_lock, filesystem, local_path
from inspect_ai._util.log_layout import log_basename

from ._walk import _name

_LOCK_SUFFIX = ".merge.lock"


def is_local(location: str) -> bool:
    return not is_s3_filename(location) and filesystem(location).is_local()


def merge_lock_path(merged: str) -> str:
    """``<dir>/<name>.merge.lock`` for the merged log ``<dir>/<name>.eval``."""
    path = local_path(merged)
    return os.path.join(os.path.dirname(path), f"{log_basename(path)}{_LOCK_SUFFIX}")


@contextmanager
def merge_guard(merged: str) -> Iterator[None]:
    """Hold the merge lock of a local merged log; nothing for other backends.

    Raises:
        WriteConflictError: Another merge holds the lock, or one crashed
            holding it.
    """
    if not is_local(merged):
        yield
        return
    info = {"pid": os.getpid(), "host": socket.gethostname(), "started": iso_now()}
    with acquire_exclusive_lock(merge_lock_path(merged), info):
        yield


async def merged_log_copy(
    fs: AsyncFilesystem, merged: str, etag: str | None, temp_dir: str
) -> str:
    """A local path holding the merged log as the merge read it.

    A local log is read in place (the merge lock keeps other merges out). An
    S3 log is downloaded in ranges pinned to `etag`, so every byte comes from
    the version whose header the merge read. Other backends are copied as
    they are.

    Raises:
        WriteConflictError: The S3 object changed since it was read.
    """
    if is_local(merged):
        return local_path(merged)
    copy = os.path.join(temp_dir, _name(merged))
    if is_s3_filename(merged) and etag is not None:
        await fs.get_file_if_match(merged, copy, etag)
    else:
        await fs.get_file(merged, copy)
    return copy


async def publish(
    fs: AsyncFilesystem,
    merged: str,
    source: BinaryIO,
    *,
    etag: str | None,
    exists: bool,
) -> str | None:
    """Publish `source` as the merged log; returns the new ETag on S3.

    Local: an atomic replace. S3: a conditional upload, ``IfMatch`` the ETag
    the merge read, or ``IfNoneMatch: *`` when there was no merged log.
    Other backends: an unconditional streaming write.

    Raises:
        WriteConflictError: S3 only: another merge published first, or the
            merged log was changed or removed since it was read.
    """
    source.seek(0)
    if is_local(merged):
        await anyio.to_thread.run_sync(_replace_local, local_path(merged), source)
        return None
    if is_s3_filename(merged):
        if exists:
            assert etag is not None, "S3 reads report an ETag"
            return await fs.write_file_conditional(merged, source, if_match=etag)
        return await fs.write_file_conditional(merged, source, if_none_match=True)
    return await fs.write_file_streaming(merged, source)


def _replace_local(path: str, source: BinaryIO) -> None:
    with atomic_write(path) as f:
        shutil.copyfileobj(source, f, length=1024 * 1024)
