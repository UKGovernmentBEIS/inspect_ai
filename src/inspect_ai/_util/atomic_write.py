"""Atomic file writing utilities for durability and crash safety.

This module provides utilities for writing files atomically to prevent
corruption from disk-full errors, process interruptions, or system crashes.

The atomic write pattern implemented here:
1. Write data to a temporary file in the same directory as the target
2. Flush and fsync the temporary file to ensure data reaches disk
3. Atomically rename/replace the temporary file to the final location
4. Clean up temporary file in case of any errors

This approach ensures that the target file is never left in a partially
written or corrupted state.
"""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Iterator, cast

from inspect_ai._util.file import file, filesystem


@contextmanager
def atomic_write(
    target_path: str,
    mode: str = "wb",
    fsync: bool = True,
    fs_options: dict[str, Any] | None = None,
) -> Iterator[BinaryIO]:
    """Context manager for atomic file writes with durability guarantees.

    Implements write-to-temporary-then-atomic-move pattern to prevent
    corruption from disk-full errors, interruptions, or crashes.

    The temporary file is created in the same directory as the target to
    ensure both are on the same filesystem, which is required for atomic
    rename operations.

    Args:
        target_path: Final destination path (local or remote URI)
        mode: File mode (only "wb" supported for atomicity)
        fsync: Whether to fsync before move (ensures durability)
        fs_options: Optional filesystem-specific options

    Yields:
        File handle to write to (writes go to temporary file)

    Raises:
        ValueError: If mode is not "wb"
        OSError: If temp write or atomic move fails

    Example:
        ```python
        with atomic_write("logs/eval.json") as f:
            f.write(json_bytes)
        # File appears atomically at logs/eval.json
        ```

    Implementation details:
        For local filesystems:
            - Uses tempfile.mkstemp() to create temp file in same directory
            - Writes to temp file
            - Calls fsync() to flush OS buffers to disk
            - Uses os.replace() for atomic rename (POSIX and Windows)
            - Cleans up temp file in finally block

        For remote filesystems (S3, Azure, GCS):
            - Writes to local temporary file
            - Uploads to remote destination
            - Most cloud providers have atomic upload semantics
            - Cleans up local temp file
    """
    if mode != "wb":
        raise ValueError("atomic_write only supports binary write mode 'wb'")

    fs_options = fs_options or {}
    fs = filesystem(target_path)

    # Determine parent directory and temp file strategy
    if fs.is_local():
        # Local filesystem: use os.replace() for atomic move
        target_dir = str(Path(target_path).parent)

        # Create temp file in same directory (ensures same filesystem)
        # This is critical for os.replace() to be atomic
        fd, temp_path = tempfile.mkstemp(
            dir=target_dir, prefix=".inspect_tmp_", suffix=".writing"
        )

        try:
            # Write to temp file
            with os.fdopen(fd, mode) as tmp_file:
                yield cast(BinaryIO, tmp_file)

                # Ensure data reaches disk before move
                if fsync:
                    tmp_file.flush()
                    os.fsync(tmp_file.fileno())

            # Atomic move: os.replace() is atomic on POSIX and Windows
            # On POSIX: calls rename() syscall (atomic)
            # On Windows: calls MoveFileEx with MOVEFILE_REPLACE_EXISTING (atomic)
            os.replace(temp_path, target_path)

        except Exception:
            # Clean up temp file on any error
            try:
                os.unlink(temp_path)
            except OSError:
                pass  # Temp file may not exist if error was very early
            raise

    else:
        # Remote filesystem (S3, Azure, GCS): write-then-upload
        # Note: Remote FS writes are often atomic at cloud provider level
        # S3 PutObject, Azure Blob uploads, and GCS uploads are atomic
        with tempfile.NamedTemporaryFile(mode=mode, delete=False) as tmp_file:
            temp_path = tmp_file.name

            try:
                # Write to local temp file
                yield cast(BinaryIO, tmp_file)

                # Ensure data reaches local disk
                if fsync:
                    tmp_file.flush()
                    os.fsync(tmp_file.fileno())

                # Close temp file before reading
                tmp_file.close()

                # Upload to remote (this is atomic for most cloud providers)
                with open(temp_path, "rb") as tf:
                    with file(target_path, "wb", fs_options=fs_options) as rf:
                        rf.write(tf.read())
                        if hasattr(rf, "flush"):
                            rf.flush()

            finally:
                # Clean up local temp file
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass


def atomic_write_bytes(
    target_path: str,
    data: bytes,
    fsync: bool = True,
    fs_options: dict[str, Any] | None = None,
) -> None:
    """Atomically write bytes to a file.

    Convenience function for single-shot atomic writes.

    Args:
        target_path: Final destination path
        data: Bytes to write
        fsync: Whether to fsync before move
        fs_options: Optional filesystem-specific options

    Example:
        ```python
        atomic_write_bytes("logs/eval.json", json_bytes)
        ```
    """
    with atomic_write(target_path, fsync=fsync, fs_options=fs_options) as f:
        f.write(data)
