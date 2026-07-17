"""Process-level utilities (PID liveness checks etc.)."""

from __future__ import annotations

import os
import sys

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _ERROR_ACCESS_DENIED = 5
    _STILL_ACTIVE = 259

    # module-level: discovery sweeps call pid_alive once per registry entry.
    # Explicit prototypes keep HANDLE handling exact (the default c_int
    # restype would truncate a handle to 32 bits).
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    def _pid_alive_windows(pid: int) -> bool:
        """Signal-free liveness check via ``OpenProcess``.

        ``os.kill(pid, 0)`` must never run on Windows: it has no signal-0
        semantics there (``0 == signal.CTRL_C_EVENT``), so it delivers a real
        console Ctrl+C to a target that shares the caller's console —
        interrupting the very process being probed — and raises ``OSError``
        (misread as dead) for a live process that doesn't.
        """
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # access denied means the process exists but we can't query it
            # (mirrors the POSIX PermissionError-means-alive case)
            return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
        try:
            # OpenProcess also succeeds for an exited process whose handles
            # are still held open; the exit code distinguishes the two.
            exit_code = wintypes.DWORD()
            if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == _STILL_ACTIVE
        finally:
            _kernel32.CloseHandle(handle)


def pid_alive(pid: int) -> bool:
    """Return True if a process with ``pid`` is currently alive.

    POSIX: uses ``os.kill(pid, 0)`` — sends no actual signal, only checks
    existence + that the caller has permission to signal the process.
    Windows: uses ``OpenProcess`` instead (see ``_pid_alive_windows`` for
    why ``os.kill(pid, 0)`` is unsafe there).
    Non-positive PIDs always return False.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
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
