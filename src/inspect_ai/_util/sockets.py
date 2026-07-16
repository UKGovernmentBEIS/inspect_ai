"""Socket-related utilities shared by transport-layer code."""

from __future__ import annotations

import asyncio
import socket
import stat
import struct
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


# struct xucred fields read for LOCAL_PEERCRED on macOS / FreeBSD:
# { u_int cr_version; uid_t cr_uid; short cr_ngroups; gid_t cr_groups[16]; }.
# Only the leading (version, uid) pair is unpacked; the buffer size requests
# the full struct (the kernel truncates to the actual length regardless).
_SOL_LOCAL = 0
_LOCAL_PEERCRED = 0x0001
_XUCRED_VERSION = 0
_XUCRED_SIZE = 4 + 4 + 2 + 2 + 16 * 4


def peer_uid(sock: socket.socket) -> int | None:
    """Effective UID of the peer on a connected AF_UNIX stream socket.

    Linux reads ``SO_PEERCRED`` (``struct ucred``: pid / uid / gid, captured
    at connect time); macOS and FreeBSD read ``LOCAL_PEERCRED`` (``struct
    xucred``). Returns ``None`` when the credential cannot be determined —
    a non-AF_UNIX socket, a platform without a peer-credential API (eg.
    Windows), or a failed ``getsockopt``. Callers own the policy for
    ``None``: the control server fails open (the credential check there is
    defence-in-depth on top of the 0700/0600 filesystem permissions, and
    failing closed would brick the surface on platforms without the API).
    """
    if not hasattr(socket, "AF_UNIX") or sock.family != socket.AF_UNIX:
        return None
    try:
        if sys.platform == "linux":
            # struct ucred { pid_t pid; uid_t uid; gid_t gid; } — pid_t is
            # signed but uid_t/gid_t are unsigned; unpacking uid as signed
            # would mangle uids >= 2**31 (eg. nfsnobody 4294967294) and
            # wrongly reject that user's own connection.
            data = sock.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("iII")
            )
            _pid, uid, _gid = struct.unpack("iII", data)
            return int(uid)
        elif sys.platform == "darwin" or sys.platform.startswith("freebsd"):
            data = sock.getsockopt(_SOL_LOCAL, _LOCAL_PEERCRED, _XUCRED_SIZE)
            version, uid = struct.unpack_from("2I", data)
            if version != _XUCRED_VERSION:
                return None
            return int(uid)
        else:
            return None
    except OSError:
        return None


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
