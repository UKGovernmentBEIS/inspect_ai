"""Process-level utilities (PID liveness checks etc.)."""

from __future__ import annotations

import os
import sys

import psutil


def pid_alive(pid: int) -> bool:
    """Return True if a process with ``pid`` is currently alive.

    POSIX: uses ``os.kill(pid, 0)`` — sends no actual signal, only checks
    existence + that the caller has permission to signal the process.
    Windows: uses ``psutil.pid_exists()`` — ``os.kill(pid, 0)`` must never
    run there, since Windows has no signal-0 semantics (``0 ==
    signal.CTRL_C_EVENT``), so it can deliver a real console Ctrl+C to a
    target sharing the caller's console, and misreports as dead a live
    process it can't signal. psutil's implementation is the signal-free
    ``OpenProcess`` probe (with access-denied-means-alive and exited-but-
    handle-still-open handling).
    Non-positive PIDs always return False (``psutil.pid_exists(0)`` would
    return True).
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return psutil.pid_exists(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but belongs to another user; we cannot signal it.
        return True
    except OSError:
        return False
