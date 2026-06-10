"""Process-level utilities (PID liveness checks etc.)."""

from __future__ import annotations

import os


def pid_alive(pid: int) -> bool:
    """Return True if a process with ``pid`` is currently alive.

    Uses ``os.kill(pid, 0)`` — sends no actual signal, only checks
    existence + that the caller has permission to signal the process.
    Non-positive PIDs always return False.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        return False
