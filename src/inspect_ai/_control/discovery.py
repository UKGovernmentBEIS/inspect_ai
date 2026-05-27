"""Discovery primitives for the control-channel HTTP server.

Each running eval process writes a per-PID discovery JSON at
``<inspect_data_dir>/control/<pid>.json`` describing its AF_UNIX
socket. CLI clients (``inspect ctl ls``, etc.) read this directory to
enumerate live evals.

The filesystem mechanics (PID-based JSON write with 0600, stale-PID
cleanup, dir 0700) come from :mod:`inspect_ai._util.discovery`; this
module is just the ACP-style schema layer (control-specific dir,
``DiscoveredControlServer`` shape, enumeration with our field
expectations).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from inspect_ai._util.appdirs import inspect_data_dir
from inspect_ai._util.discovery import list_alive_discovery_entries


def discovery_dir() -> Path:
    """The directory holding per-process control discovery files + default sockets."""
    return inspect_data_dir("control")


def default_socket_path(pid: int) -> Path:
    """Default AF_UNIX socket path for a control server bound by ``pid``."""
    return discovery_dir() / f"{pid}.sock"


def discovery_file_path(pid: int) -> Path:
    """Path to the discovery JSON for a given pid."""
    return discovery_dir() / f"{pid}.json"


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
    results: list[DiscoveredControlServer] = []
    for data in list_alive_discovery_entries(discovery_dir()):
        sock = data.get("socket_path")
        run_id = data.get("run_id")
        if not sock or not run_id:
            continue
        try:
            pid = int(data["pid"])
        except (KeyError, TypeError, ValueError):
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
