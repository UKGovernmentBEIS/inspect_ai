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
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, cast

from inspect_ai._util.file import filesystem

_TEMP_PREFIX = ".inspect_tmp_"
_TEMP_SUFFIX = ".writing"
_TEMP_TRIES = 100


def _create_local_tempfile(target_dir: str) -> tuple[int, str]:
    """Create a unique temp file in ``target_dir`` with ``mode=0o666``.

    The kernel applies the current process umask atomically at creation
    (``mode & ~umask``), so the resulting permission bits match what
    ``open(..., "wb")`` would have produced — without the process-global
    ``os.umask(0); os.umask(prev)`` dance, which is not thread-safe.

    Uses ``O_EXCL`` for race-safe creation and ``secrets.token_urlsafe``
    for collision-resistant random names; retries on the astronomically
    unlikely collision.

    Returns:
        ``(fd, path)`` — file descriptor and absolute temp path.

    Raises:
        OSError: If no unique name can be created (typically because the
            target directory is unwritable, in which case the first
            ``os.open`` call raises and propagates without retry).
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY  # Windows: prevent CRLF translation
    for _ in range(_TEMP_TRIES):
        name = f"{_TEMP_PREFIX}{secrets.token_urlsafe(8)}{_TEMP_SUFFIX}"
        temp_path = os.path.join(target_dir, name)
        try:
            return os.open(temp_path, flags, 0o666), temp_path
        except FileExistsError:
            continue
    raise OSError(f"Could not create unique temp file in {target_dir!r}")


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

    # Match fsspec's LocalFileSystem.open behaviour: auto-create missing
    # parent directories. Otherwise tempfile.mkstemp(dir=target_dir) would
    # raise FileNotFoundError for callers like
    # `write_eval_log("new/dir/log.json", format="json")`.
    os.makedirs(target_dir, exist_ok=True)

    # Capture the existing target's mode before we create the temp file,
    # so we can restore it after the rename. For new targets the temp
    # file's OS-applied umask default is already correct and no chmod
    # is needed (matches what `open(..., "wb")` would have produced via
    # the previous fsspec local path). On Windows os.chmod only honours
    # the read-only bit, so this is harmless cross-platform.
    try:
        target_mode_existing: int | None = os.stat(target_path).st_mode & 0o777
    except FileNotFoundError:
        target_mode_existing = None

    # Create the temp file with mode=0o666 so the kernel applies the
    # current process umask atomically at creation — no thread-unsafe
    # `os.umask(0); os.umask(prev)` mutation.
    fd, temp_path = _create_local_tempfile(target_dir)

    try:
        with os.fdopen(fd, mode) as tmp_file:
            yield cast(BinaryIO, tmp_file)

            if fsync:
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

        # Restore the prior mode for existing targets (the OS-applied
        # umask default would otherwise overwrite the file's previous
        # permissions). Doing this before os.replace() means the final
        # inode carries the right mode atomically.
        if target_mode_existing is not None:
            os.chmod(temp_path, target_mode_existing)

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
