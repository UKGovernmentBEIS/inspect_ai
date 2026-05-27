"""Discovery primitives for the control-channel HTTP server.

Each running eval process writes a per-PID discovery JSON at
``<inspect_data_dir>/control/<pid>.json`` describing its AF_UNIX
socket. CLI clients (``inspect ctl ls``, etc.) read this directory to
enumerate live evals.

The pattern mirrors :mod:`inspect_ai.agent._acp.discovery` but lives
in a separate directory and namespace so the two surfaces stay
structurally independent (per the control-channel design's
"separate from ACP" position).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from inspect_ai._util.appdirs import inspect_data_dir


def discovery_dir() -> Path:
    """The directory holding per-process control discovery files + default sockets."""
    return inspect_data_dir("control")


def default_socket_path(pid: int) -> Path:
    """Default AF_UNIX socket path for a control server bound by ``pid``."""
    return discovery_dir() / f"{pid}.sock"


def discovery_file_path(pid: int) -> Path:
    """Path to the discovery JSON for a given pid."""
    return discovery_dir() / f"{pid}.json"


def pid_alive(pid: int) -> bool:
    """Return True if a process with ``pid`` is currently alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        return False


def cleanup_stale_discovery_files() -> None:
    """Sweep discovery files whose owning PID is no longer alive.

    Also unlinks the orphan AF_UNIX socket node recorded in the file
    so subsequent binds on the same path don't trip over a leftover
    inode. Best-effort — malformed files are silently skipped.
    """
    ctl_dir = discovery_dir()
    if not ctl_dir.exists():
        return
    for path in ctl_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            pid = int(data.get("pid", -1))
            if pid <= 0 or pid_alive(pid):
                continue
            path.unlink(missing_ok=True)
            sock = data.get("socket_path")
            if sock:
                try:
                    Path(sock).unlink(missing_ok=True)
                except OSError:
                    pass
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
            continue


@dataclass(frozen=True)
class DiscoveredControlServer:
    """One entry from the control discovery directory.

    Used by CLI clients to enumerate live evals.
    """

    pid: int
    run_id: str
    socket_path: Path
    started_at: float


def list_discovered_servers() -> list[DiscoveredControlServer]:
    """Enumerate alive control servers from the discovery directory.

    Sorted most-recently-started first. Stale files (dead PID,
    malformed JSON, missing fields) are silently skipped.
    """
    ctl_dir = discovery_dir()
    if not ctl_dir.exists():
        return []
    results: list[DiscoveredControlServer] = []
    for path in ctl_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        try:
            pid = int(data.get("pid", -1))
        except (TypeError, ValueError):
            continue
        if pid <= 0 or not pid_alive(pid):
            continue
        sock = data.get("socket_path")
        run_id = data.get("run_id")
        if not sock or not run_id:
            continue
        try:
            started_at = float(data.get("started_at", 0.0))
        except (TypeError, ValueError):
            started_at = 0.0
        results.append(
            DiscoveredControlServer(
                pid=pid,
                run_id=str(run_id),
                socket_path=Path(str(sock)),
                started_at=started_at,
            )
        )
    results.sort(key=lambda e: e.started_at, reverse=True)
    return results
