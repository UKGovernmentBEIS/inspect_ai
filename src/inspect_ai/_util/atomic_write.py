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

Known trade-offs (accepted):

- Transient 2x disk usage: the temp file and the old target coexist until
  the rename, so a write needs free space for a full extra copy. On a
  nearly-full disk the write fails earlier (ENOSPC on the temp file) but
  the previous valid target survives — which is the point of the pattern.
- Windows reader contention: ``os.replace()`` needs DELETE access on the
  target, which Windows denies while another process holds the file open
  without ``FILE_SHARE_DELETE`` (Python's ``open()`` does not request it).
  A viewer reading a log mid-flush can therefore cause ``PermissionError``
  where the previous truncate-in-place write would have succeeded. Viewer
  reads are short-lived so the window is small, and the failed flush
  leaves the previous valid log intact; this is an accepted risk rather
  than something we retry or fall back around.

Scope: local filesystem only. Remote stores (S3, Azure, GCS) already
provide atomic uploads at the provider level (S3 ``PutObject``, Azure
Blob upload, GCS upload), and inspect_ai consolidates remote I/O on
:class:`~inspect_ai._util.asyncfiles.AsyncFilesystem` for proper async
semantics. Callers should gate calls to :func:`atomic_write` on
``filesystem(path).is_local()`` and route remote writes through
``AsyncFilesystem`` instead.

Related helper: :func:`inspect_ai._util.file.write_atomic_text` provides
the same rename-based atomicity for a *text* writer callback. This module
is the binary counterpart, adding what the log recorders need that the
text helper does not: a streaming context manager (so a temp file can be
``shutil.copyfileobj``'d in), one-shot ``bytes``, mode preservation, an
``fsync`` toggle, and ``O_EXCL`` temp creation. The two are kept separate
deliberately; they could be unified later if the extra features are wanted
on the text path too.
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
        fsync: Whether to ``fsync()`` the temp file before renaming.

    Yields:
        A binary file handle (opened ``"wb"``). Writes go to the temporary
        file; the move to ``target_path`` happens on successful exit.

    Raises:
        ValueError: If ``target_path`` does not resolve to a local
            filesystem.
        OSError: If the temp write or the atomic rename fails.

    Example:
        ```python
        with atomic_write("logs/eval.json") as f:
            f.write(json_bytes)
        # File appears atomically at logs/eval.json
        ```

    Implementation:
        - A unique temp file is created in the target's directory via
          :func:`_create_local_tempfile` (``os.open`` with
          ``O_CREAT | O_EXCL`` and a ``.inspect_tmp_*.writing`` name).
        - The handle is yielded to the caller for writes.
        - On normal exit: ``fsync()`` (when ``fsync=True``) is followed
          by ``os.replace()`` — atomic on POSIX (``rename()``) and on
          Windows (``MoveFileEx`` with ``MOVEFILE_REPLACE_EXISTING``) —
          and, on POSIX, the parent directory is ``fsync``'d so the rename
          itself is crash-durable.
        - If ``target_path`` is a symlink, it is resolved so the write
          goes through to the referent (matching ``open(path, "wb")``),
          rather than replacing the link with a regular file.
        - On any exception (including ``KeyboardInterrupt``), the temp file
          is unlinked and the exception re-raised; the target is untouched.
    """
    fs = filesystem(target_path)
    if not fs.is_local():
        raise ValueError(
            f"atomic_write only supports local paths; got {target_path!r}. "
            "Use AsyncFilesystem.write_file_streaming for remote stores."
        )

    # Resolve a symlinked target so we write through to the referent and
    # os.replace() updates the real file, rather than replacing the link
    # with a regular file. The old `open(path, "wb")` path followed
    # symlinks; preserve that. The temp file is then created in the
    # *resolved* target's directory, keeping it on the same filesystem so
    # the rename stays atomic.
    target = (
        os.path.realpath(target_path) if os.path.islink(target_path) else target_path
    )
    target_dir = str(Path(target).parent)

    # Match fsspec's LocalFileSystem.open behaviour: auto-create missing
    # parent directories.
    os.makedirs(target_dir, exist_ok=True)

    # Capture the existing target's mode before we create the temp file,
    # so we can restore it after the rename. For new targets the temp
    # file's OS-applied umask default is already correct and no chmod
    # is needed (matches what `open(..., "wb")` would have produced via
    # the previous fsspec local path). On Windows os.chmod only honours
    # the read-only bit, so this is harmless cross-platform.
    try:
        target_mode_existing: int | None = os.stat(target).st_mode & 0o777
    except FileNotFoundError:
        target_mode_existing = None

    # Create the temp file with mode=0o666 so the kernel applies the
    # current process umask atomically at creation — no thread-unsafe
    # `os.umask(0); os.umask(prev)` mutation.
    fd, temp_path = _create_local_tempfile(target_dir)

    try:
        with os.fdopen(fd, "wb") as tmp_file:
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
        os.replace(temp_path, target)

        # Durability: fsync the parent directory so the rename survives a
        # crash/power-loss right after os.replace (POSIX allows the new
        # directory entry to be lost otherwise, even though the file data
        # was fsync'd). Opening a directory fd is POSIX-only; on Windows
        # os.open of a directory fails, so skip it there.
        if fsync and hasattr(os, "O_DIRECTORY"):
            dir_fd = os.open(target_dir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

    except BaseException:
        # Clean up temp file on any error, including KeyboardInterrupt —
        # eval runs are Ctrl-C'd often, and leaked .inspect_tmp_* files
        # would otherwise accumulate in users' log dirs. Re-raise so the
        # interrupt still propagates; the target is left untouched.
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
