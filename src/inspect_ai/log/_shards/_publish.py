"""Overlap guards and publication of the merged log.

Callers serialise merges of one log; these guards turn a broken contract
into a refused publish. A local merged log is guarded by a lock file beside
it, an S3 one by a conditional upload against the ETag the merge read. The
merge supports no other storage (see :func:`check_supported_location`).
"""

import os
import shutil
import socket
import threading
from collections.abc import Callable, Iterator
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


def check_supported_location(location: str) -> None:
    """Refuse a location that is not a local path, ``file://`` URI or ``s3://`` URL.

    The merge supports only these (decision: Ransom, 2026-10-30): other
    fsspec backends differ in how they list, name and version objects. The
    location is checked as text, so nothing is constructed, listed or read
    first. A chained URL (``simplecache::s3://...``, or ``::`` after a
    supported prefix) is refused too.

    Raises:
        ValueError: `location` names another protocol.
    """
    if "::" in location or (
        "://" in location and not location.startswith(("s3://", "file://"))
    ):
        raise ValueError(
            f"{location} cannot be merged: shard merging supports local paths, "
            "file:// URIs and s3:// URLs only."
        )


def is_local(location: str) -> bool:
    return not is_s3_filename(location) and filesystem(location).is_local()


def merge_lock_path(merged: str) -> str:
    """``<dir>/<name>.merge.lock`` for the merged log ``<dir>/<name>.eval``."""
    path = local_path(merged)
    return os.path.join(os.path.dirname(path), f"{log_basename(path)}{_LOCK_SUFFIX}")


@contextmanager
def merge_guard(merged: str) -> Iterator[None]:
    """Hold the merge lock of a local merged log; nothing for S3.

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
    the version whose header the merge read.

    Raises:
        WriteConflictError: The S3 object changed since it was read.
    """
    if is_local(merged):
        return local_path(merged)
    assert is_s3_filename(merged) and etag is not None, "S3 reads report an ETag"
    copy = os.path.join(temp_dir, _name(merged))
    await fs.get_file_if_match(merged, copy, etag)
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

    Raises:
        WriteConflictError: S3 only: another merge published first, or the
            merged log was changed or removed since it was read.
    """
    source.seek(0)
    if is_local(merged):
        path = local_path(merged)
        await _in_owned_thread(lambda: _replace_local(path, source))
        return None
    assert is_s3_filename(merged), "the merge supports local and S3 logs only"
    if exists:
        assert etag is not None, "S3 reads report an ETag"
        return await fs.write_file_conditional(merged, source, if_match=etag)
    return await fs.write_file_conditional(merged, source, if_none_match=True)


async def _in_owned_thread(work: Callable[[], None]) -> None:
    """Run `work` in a worker thread that the caller outlives.

    A directly cancelled asyncio task (``Task.cancel()``, a timeout) can
    leave a ``to_thread`` await while its thread runs on, which would close
    the source and release the merge lock under a worker still replacing
    the merged log, so a later merge's log could be overwritten by this
    one. On cancellation this waits, shielded, for a worker that has
    started to finish, then re-raises.
    """
    lock = threading.Lock()
    finished = threading.Event()
    state = {"started": False, "abandoned": False}

    def run() -> None:
        with lock:
            if state["abandoned"]:
                return
            state["started"] = True
        try:
            work()
        finally:
            finished.set()

    try:
        await anyio.to_thread.run_sync(run)
    except BaseException:
        with lock:
            state["abandoned"] = True
            started = state["started"]
        if started:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(finished.wait)
        raise


def _replace_local(path: str, source: BinaryIO) -> None:
    with atomic_write(path) as f:
        shutil.copyfileobj(source, f, length=1024 * 1024)
