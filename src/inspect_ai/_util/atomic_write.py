"""Atomic file writing utilities for local filesystem durability.

This module provides utilities for writing files atomically on the local
filesystem to prevent corruption from disk-full errors, process
interruptions, or system crashes.

The atomic write pattern implemented here:

1. Write data to a temporary file in the same directory as the target.
2. Flush and fsync the temporary file to ensure data reaches disk.
3. Atomically rename/replace the temporary file to the final location.
4. Clean up the temporary file in case of any errors.

This approach ensures the target file is never left in a partially
written or corrupted state.

Scope: local filesystem only. Remote stores (S3, Azure, GCS) already
provide atomic uploads at the provider level (S3 ``PutObject``, Azure
Blob upload, GCS upload), and inspect_ai consolidates remote I/O on
:class:`~inspect_ai._util.asyncfiles.AsyncFilesystem` for proper async
semantics. Callers should gate calls to :func:`atomic_write` on
``filesystem(path).is_local()`` and route remote writes through
``AsyncFilesystem`` instead.
"""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, cast

from inspect_ai._util.file import filesystem


@contextmanager
def atomic_write(
    target_path: str,
    mode: str = "wb",
    fsync: bool = True,
) -> Iterator[BinaryIO]:
    """Context manager for atomic local-file writes with durability guarantees.

    Implements the write-to-temporary-then-atomic-move pattern to prevent
    corruption from disk-full errors, interruptions, or crashes. The
    temporary file is created in the same directory as the target so both
    are on the same filesystem, which is required for ``os.replace()`` to
    be atomic.

    Args:
        target_path: Final destination path. Must be local; remote paths
            (``s3://``, ``gs://``, etc.) raise ``ValueError``. Use
            :class:`~inspect_ai._util.asyncfiles.AsyncFilesystem` for
            remote writes.
        mode: File mode. Only ``"wb"`` is supported.
        fsync: Whether to ``fsync()`` the temp file before renaming.

    Yields:
        A binary file handle. Writes go to the temporary file; the move
        to ``target_path`` happens on successful exit.

    Raises:
        ValueError: If ``mode`` is not ``"wb"``, or if ``target_path``
            does not resolve to a local filesystem.
        OSError: If the temp write or the atomic rename fails.

    Example:
        ```python
        with atomic_write("logs/eval.json") as f:
            f.write(json_bytes)
        # File appears atomically at logs/eval.json
        ```

    Implementation:
        - ``tempfile.mkstemp()`` creates the temp file in the target's
          directory with a ``.inspect_tmp_*.writing`` name.
        - The handle is yielded to the caller for writes.
        - On normal exit: ``fsync()`` (when ``fsync=True``) is followed
          by ``os.replace()`` — atomic on POSIX (``rename()``) and on
          Windows (``MoveFileEx`` with ``MOVEFILE_REPLACE_EXISTING``).
        - On any exception, the temp file is unlinked and the exception
          re-raised; the target file is left untouched.
    """
    if mode != "wb":
        raise ValueError("atomic_write only supports binary write mode 'wb'")

    fs = filesystem(target_path)
    if not fs.is_local():
        raise ValueError(
            f"atomic_write only supports local paths; got {target_path!r}. "
            "Use AsyncFilesystem.write_file_streaming for remote stores."
        )

    target_dir = str(Path(target_path).parent)

    # Create temp file in the target's directory so os.replace() is atomic.
    fd, temp_path = tempfile.mkstemp(
        dir=target_dir, prefix=".inspect_tmp_", suffix=".writing"
    )

    try:
        with os.fdopen(fd, mode) as tmp_file:
            yield cast(BinaryIO, tmp_file)

            if fsync:
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

        # Atomic rename: POSIX rename() / Windows MoveFileEx.
        os.replace(temp_path, target_path)

    except Exception:
        # Clean up temp file on any error; target is left untouched.
        try:
            os.unlink(temp_path)
        except OSError:
            pass  # Temp file may not exist if the error was very early.
        raise


def atomic_write_bytes(
    target_path: str,
    data: bytes,
    fsync: bool = True,
) -> None:
    """Atomically write bytes to a local file.

    Convenience wrapper around :func:`atomic_write` for single-shot
    writes.

    Args:
        target_path: Local destination path. Remote paths raise
            ``ValueError`` (see :func:`atomic_write`).
        data: Bytes to write.
        fsync: Whether to ``fsync()`` before renaming.

    Raises:
        ValueError: If ``target_path`` does not resolve to a local
            filesystem.

    Example:
        ```python
        atomic_write_bytes("logs/eval.json", json_bytes)
        ```
    """
    with atomic_write(target_path, fsync=fsync) as f:
        f.write(data)
