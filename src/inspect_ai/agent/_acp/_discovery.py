"""Discovery primitives shared by the ACP server and CLI clients.

These were originally module-private to ``_server.py``; lifted into
their own module so the CLI bridge (``inspect acp --stdio``) and the
Phase 15 TUI client can reuse them without importing server internals.

Public surface:

- :func:`discovery_dir` — the directory holding per-process discovery
  JSON files + default UNIX socket nodes.
- :func:`default_socket_path` — default AF_UNIX socket path for an
  ``eval_id`` (sibling of the discovery file).
- :func:`pid_alive` — POSIX-only "is this process still alive" check.
- :func:`parse_host_port` — ``host:port`` parser (with IPv6 bracket
  support); returns ``None`` when ``value`` is a path-like or otherwise
  not a network address.
- :func:`has_unix_sockets` — platform support check.
- :func:`cleanup_stale_discovery_files` — best-effort sweep for files
  whose owning PID is no longer alive.
- :class:`TargetAddress` + :func:`resolve_target` — pick a connectable
  address from the discovery dir / explicit overrides (used by the
  Phase 13 stdio bridge and Phase 15 TUI client).

The names without a leading underscore are the public surface; the
underscored aliases at the bottom of this module preserve back-compat
for callers in ``_server.py`` that haven't migrated yet.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from inspect_ai._util.appdirs import inspect_data_dir


def discovery_dir() -> Path:
    """The directory where discovery JSON files + default sockets live."""
    return inspect_data_dir("acp")


def default_socket_path(eval_id: str) -> Path:
    """Default AF_UNIX socket path for a given eval_id."""
    return discovery_dir() / f"{eval_id}.sock"


def pid_alive(pid: int) -> bool:
    """Return ``True`` if a process with ``pid`` is currently alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # signal 0 = existence check only
        return True
    except (ProcessLookupError, OSError):
        return False


def parse_host_port(value: str) -> tuple[str, int] | None:
    """Parse a ``host:port`` or ``[ipv6]:port`` string.

    Returns ``(host, port)`` if ``value`` is a well-formed network
    address, else ``None`` (treat the value as a UNIX socket path).

    Raises :class:`ValueError` when ``value`` parses as ``host:port``
    syntactically (so it's clearly intended as a network address)
    but the port is out of the valid TCP range ``[0, 65535]``.
    Falling through to UNIX-path interpretation in that case would
    silently bind/connect to a literal path like
    ``"127.0.0.1:99999"`` — misleading and harder to diagnose than
    a clean error.

    A bare integer is intentionally NOT parsed here — the caller
    handles ``int`` transports separately for the loopback-port shape.
    """
    if not value:
        return None

    def _check_port(port: int) -> int:
        if port < 0 or port > 65535:
            raise ValueError(f"port out of range (must be 0-65535, got {port})")
        return port

    # IPv6 bracket form: [::1]:4444
    if value.startswith("["):
        end = value.find("]:")
        if end == -1:
            return None
        host = value[1:end]
        port_str = value[end + 2 :]
        try:
            port = int(port_str)
        except ValueError:
            return None
        return host, _check_port(port)
    # Path-like values never have ``host:port`` semantics — a UNIX socket
    # at ``/tmp/foo`` should not be misread as host "" port "foo".
    if "/" in value or "\\" in value:
        return None
    if ":" not in value:
        return None
    host, _, port_str = value.rpartition(":")
    if not host or not port_str:
        return None
    try:
        port = int(port_str)
    except ValueError:
        return None
    return host, _check_port(port)


def has_unix_sockets() -> bool:
    """Whether the current platform supports AF_UNIX sockets.

    POSIX always supports them. Windows 10/11 do; older Windows
    versions don't expose :func:`asyncio.start_unix_server`.
    """
    if sys.platform != "win32":
        return True
    return hasattr(asyncio, "start_unix_server")


def cleanup_stale_discovery_files() -> None:
    """Remove discovery JSON files whose owning PID is no longer alive.

    Called by :meth:`_AcpServer.start` before writing our own discovery
    file. Also unlinks the orphaned AF_UNIX socket node recorded in the
    stale file so subsequent binds on the same path don't trip over a
    leftover inode.
    """
    acp_dir = discovery_dir()
    if not acp_dir.exists():
        return
    for path in acp_dir.glob("*.json"):
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
            # Best effort — skip malformed entries.
            continue


# ---------------------------------------------------------------------------
# Target resolution for client-side attachment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetAddress:
    """A connectable address for one running ACP server.

    Exactly one of ``socket_path`` / ``(host, port)`` is populated.
    The CLI bridge opens the appropriate kind of asyncio connection;
    Phase 15's TUI client uses the same shape.
    """

    socket_path: Path | None = None
    host: str | None = None
    port: int | None = None
    eval_id: str | None = None
    """Owning eval id when resolved via discovery; ``None`` for ``--server`` overrides."""

    def describe(self) -> str:
        """Short human-readable address form (for stderr logging / errors)."""
        if self.socket_path is not None:
            return str(self.socket_path)
        if self.host is not None and self.port is not None:
            host = self.host
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            return f"{host}:{self.port}"
        return "<invalid>"


@dataclass(frozen=True)
class DiscoveredEval:
    """One entry from the discovery directory.

    Used by callers that want to enumerate live evals (e.g. Phase 15's
    unified picker).
    """

    eval_id: str
    started_at: float
    target: TargetAddress


class TargetResolutionError(Exception):
    """Raised when :func:`resolve_target` cannot pick a connectable target.

    The CLI layer catches this and prints ``str(exc)`` to stderr +
    exits non-zero. The message is the user-facing diagnostic; keep it
    actionable.
    """


def _target_from_discovery_data(data: dict[str, object]) -> TargetAddress | None:
    """Build a :class:`TargetAddress` from a discovery JSON dict.

    Returns ``None`` if the file is structurally invalid (missing both
    socket_path and host:port). Callers using this on stale files should
    treat ``None`` as "skip this entry."
    """
    eval_id_raw = data.get("eval_id")
    eval_id = str(eval_id_raw) if eval_id_raw is not None else None
    sock = data.get("socket_path")
    if sock:
        return TargetAddress(socket_path=Path(str(sock)), eval_id=eval_id)
    host = data.get("host")
    port = data.get("port")
    if host is not None and port is not None:
        try:
            return TargetAddress(host=str(host), port=int(port), eval_id=eval_id)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            return None
    return None


def list_discovered_evals() -> list[DiscoveredEval]:
    """Enumerate alive ACP servers from the discovery directory.

    Sorted most-recently-started first. Stale files (dead PID,
    malformed JSON, missing fields) are silently skipped — same
    resilience contract as :func:`cleanup_stale_discovery_files`.
    """
    acp_dir = discovery_dir()
    if not acp_dir.exists():
        return []
    results: list[DiscoveredEval] = []
    for path in acp_dir.glob("*.json"):
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
        target = _target_from_discovery_data(data)
        if target is None:
            continue
        try:
            started_at = float(data.get("started_at", 0.0))
        except (TypeError, ValueError):
            started_at = 0.0
        eval_id = target.eval_id or ""
        if not eval_id:
            continue
        results.append(
            DiscoveredEval(eval_id=eval_id, started_at=started_at, target=target)
        )
    results.sort(key=lambda e: e.started_at, reverse=True)
    return results


def resolve_target(
    eval_id: str | None,
    server: str | None,
) -> tuple[TargetAddress, list[DiscoveredEval] | None]:
    """Pick a connectable target from --eval-id / --server / discovery.

    Returns ``(target, picked_from)`` where ``picked_from`` is the
    full candidate list when discovery had to disambiguate (so the
    CLI can log "picked X out of N" to stderr), else ``None``.

    Raises :class:`TargetResolutionError` when no reasonable choice
    exists. Precedence:

    1. ``server`` (explicit override) — never touches the discovery
       dir; useful for editor configs that hard-code an address or
       for connecting to a remote ACP server.
    2. ``eval_id`` — look up the entry whose ``eval_id`` matches.
       Error if no live eval has that id.
    3. Otherwise — pick the most-recently-started live eval. Error
       only when zero are alive.

    ``server`` and ``eval_id`` are mutually exclusive at the CLI
    layer (the click decorator rejects when both are provided); this
    function tolerates either order if both happen to be set, but
    callers should not rely on that.
    """
    if server:
        try:
            host_port = parse_host_port(server)
        except ValueError as exc:
            # Syntactically host:port but out-of-range port; surface as
            # a resolution error rather than letting it fall through to
            # UNIX-path interpretation (where the eventual bind/connect
            # would fail with a confusing path-not-found).
            raise TargetResolutionError(
                f"invalid --server value {server!r}: {exc}"
            ) from exc
        if host_port is not None:
            host, port = host_port
            return TargetAddress(host=host, port=port), None
        return TargetAddress(socket_path=Path(server)), None

    discovered = list_discovered_evals()

    if eval_id is not None:
        for entry in discovered:
            if entry.eval_id == eval_id:
                return entry.target, None
        raise TargetResolutionError(
            f"no running eval with id {eval_id!r} (checked {discovery_dir()})"
        )

    if not discovered:
        raise TargetResolutionError(
            f"no running evals found in {discovery_dir()}. "
            f"Start one with `inspect eval <task> --acp-server`."
        )

    # Most-recently-started wins; report ambiguity to the caller so the
    # CLI can surface a "picked X of N" notice on stderr.
    if len(discovered) == 1:
        return discovered[0].target, None
    return discovered[0].target, discovered


# ---------------------------------------------------------------------------
# Back-compat aliases for the underscore names previously exported by
# ``_server.py``. New callers should use the unprefixed names above.
# ---------------------------------------------------------------------------

_discovery_dir = discovery_dir
_default_socket_path = default_socket_path
_pid_alive = pid_alive
_parse_host_port = parse_host_port
_has_unix_sockets = has_unix_sockets
_cleanup_stale_discovery_files = cleanup_stale_discovery_files
