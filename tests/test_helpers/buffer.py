"""Test helpers for sample-buffer database recovery flows."""

import os
import shutil
from pathlib import Path

from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase

# A PID that does not correspond to a live process, so the recovery flow treats
# the snapshot as belonging to a crashed (not running) eval.
DEAD_PID = 99999999


def simulate_crashed_buffer_db(
    buffer: SampleBufferDatabase, *, pid: int = DEAD_PID
) -> Path:
    """Simulate an eval process crashing with this buffer database still open.

    A real crash leaves the ``.db`` plus its *hot* (uncheckpointed) ``-wal`` /
    ``-shm`` sidecars on disk under the crashed process's PID. With persistent
    per-thread connections the committed data lives in the ``-wal`` until a
    checkpoint, so we snapshot the whole file set to a dead-PID name *without*
    checkpointing first — reproducing a hot-WAL crash (the common case now).

    The live buffer's handles are then released and its (live-PID) files removed,
    leaving only the dead-PID snapshot, which the recovery flow discovers via
    ``psutil`` liveness filtering.

    Args:
        buffer: the live buffer database to "crash".
        pid: the dead PID to use in the snapshot filename.

    Returns:
        Path to the dead-PID ``.db`` snapshot (also assigned to
        ``buffer.db_path``).
    """
    src = buffer.db_path
    dst = src.parent / src.name.replace(f".{os.getpid()}.", f".{pid}.")

    # snapshot the main db + hot WAL sidecars. copy (not move) avoids disturbing
    # the still-open connection's files; plain copy gives the snapshot a fresh
    # mtime so callers that create several crashed DBs get recency ordering that
    # matches call order (the recovery flow picks the newest by mtime).
    for suffix in ("", "-wal", "-shm"):
        source = Path(f"{src}{suffix}")
        if source.exists():
            shutil.copy(source, f"{dst}{suffix}")

    # the crashed process is gone: drop its handles and remove the live-PID files
    # so only the dead-PID snapshot remains (and the name is free for reuse)
    buffer._close_all_connections()
    for suffix in ("", "-wal", "-shm"):
        Path(f"{src}{suffix}").unlink(missing_ok=True)

    buffer.db_path = dst
    return dst
