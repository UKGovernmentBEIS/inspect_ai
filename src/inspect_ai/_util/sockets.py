"""Socket-related utilities shared by transport-layer code."""

from __future__ import annotations

import asyncio
import stat
import sys
from pathlib import Path

from inspect_ai._util.discovery import DISCOVERY_FILE_MODE

# Owner-only (0600) on a bound AF_UNIX socket node. Mirrors
# DISCOVERY_FILE_MODE — same threat model: defence-in-depth against a
# loosened / world-traversable parent directory, so the socket can't be
# reached even if the directory perms slip.
SOCKET_FILE_MODE = DISCOVERY_FILE_MODE


def prepare_socket_path(path: Path) -> None:
    """Ready ``path`` for an AF_UNIX bind.

    Ensures the parent dir exists and removes a leftover socket node from a
    stale prior bind. Refuses to remove a path that exists and is **not** a
    mistaken or hostile path (eg. ``--acp-server=/etc/passwd``) raises
    instead of deleting data. Raising here is safe for default-path callers
    too: the control / ACP servers degrade gracefully when their bind fails.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        try:
            mode = path.lstat().st_mode
        except OSError as e:
            raise RuntimeError(
                f"Cannot stat existing path {path} for socket bind: {e}"
            ) from e
        if not stat.S_ISSOCK(mode):
            raise RuntimeError(
                f"Refusing to bind a socket at {path}: path exists and is not a "
                "socket. Remove it or choose a different path."
            )
        path.unlink()


def lock_socket_file(path: Path) -> None:
    """Best-effort owner-only chmod on a bound socket node.

    Defence-in-depth alongside the 0700 parent directory. Some filesystems
    ignore ``chmod`` (FUSE, certain network mounts); that's acceptable — the
    socket still lives under the user-scoped data dir.
    """
    try:
        path.chmod(SOCKET_FILE_MODE)
    except OSError:
        pass


def has_unix_sockets() -> bool:
    """Whether the current platform supports AF_UNIX sockets.

    POSIX always supports them. Windows 10/11 do; older Windows
    versions don't expose :func:`asyncio.start_unix_server`.
    """
    if sys.platform != "win32":
        return True
    return hasattr(asyncio, "start_unix_server")


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

    A bare integer is intentionally NOT parsed here — callers handle
    ``int`` transports separately for the loopback-port shape.
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
