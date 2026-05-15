"""Phase 8 — JSON-RPC 2.0 transport server for ACP clients.

When an eval is launched with ``agent_acp`` enabled (via the
``--agent-acp`` CLI flag or the ``EvalConfig.agent_acp`` field), the
:func:`acp_server` async context manager spins up a JSON-RPC server
bound to either an AF_UNIX socket (default) or a TCP loopback port,
writes a discovery JSON file so clients can enumerate running evals,
and accepts incoming connections.

Phase 8 is transport-only — connections are wrapped in
:class:`acp.connection.Connection` with an **empty**
:class:`acp.router.MessageRouter`, so any incoming JSON-RPC request
returns a standard "method not found" error. Method dispatch
(``initialize`` / ``newSession`` / ``session/prompt`` / ``session/cancel``
/ ``session/update`` notifications, etc.) is the subject of Phase 9
(session picker) and Phase 10 (full SessionRouter + replay-on-attach).
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import time
from contextlib import asynccontextmanager
from logging import getLogger
from pathlib import Path
from typing import AsyncIterator

from acp.connection import Connection
from acp.router import MessageRouter

from inspect_ai._util.appdirs import inspect_data_dir

logger = getLogger(__name__)


class _AcpServer:
    """JSON-RPC 2.0 transport server for ACP clients.

    The :class:`Connection` handles framing and dispatch; this class
    handles socket bind/accept, the per-PID discovery file, and
    graceful shutdown of all live connections.
    """

    def __init__(
        self,
        *,
        eval_id: str,
        transport: bool | int | str,
    ) -> None:
        self._eval_id = eval_id
        self._transport = transport
        self._server: asyncio.base_events.Server | None = None
        self._socket_path: Path | None = None
        self._host: str | None = None
        self._port: int | None = None
        self._discovery_path: Path | None = None
        # Live connections; each entry has its own background receive task.
        # We hold strong references so they don't get GC'd, and so we can
        # close them all at shutdown.
        self._connections: set[Connection] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def socket_path(self) -> Path | None:
        """The bound AF_UNIX socket path, or None if bound to TCP."""
        return self._socket_path

    @property
    def port(self) -> int | None:
        """The bound TCP port, or None if bound to AF_UNIX."""
        return self._port

    @property
    def host(self) -> str | None:
        """The bound TCP host, or None if bound to AF_UNIX.

        Defaults to ``127.0.0.1`` when only a port is supplied; user-
        specified via ``host:port`` (e.g. ``0.0.0.0:4444``) to bind on
        a non-loopback interface.
        """
        return self._host

    @property
    def discovery_path(self) -> Path | None:
        """Path to this server's discovery JSON file, if started."""
        return self._discovery_path

    async def start(self) -> None:
        """Bind the socket, write the discovery file, start accepting."""
        # Clean up any stale discovery files / orphan sockets from
        # processes that crashed without unregistering.
        _cleanup_stale_discovery_files()

        if self._transport is True:
            await self._bind_unix(_default_socket_path(self._eval_id))
        elif isinstance(self._transport, int) and not isinstance(self._transport, bool):
            await self._bind_tcp(self._transport)
        elif isinstance(self._transport, str):
            host_port = _parse_host_port(self._transport)
            if host_port is not None:
                host, port = host_port
                await self._bind_tcp(port, host=host)
            else:
                await self._bind_unix(Path(self._transport))
        else:
            # ``transport`` was falsy — the caller should have skipped us
            # via the asynccontextmanager guard. Defensive check.
            raise ValueError(f"Unsupported agent_acp transport: {self._transport!r}")

        # Write the discovery file describing this server.
        self._discovery_path = _discovery_dir() / f"{os.getpid()}.json"
        self._discovery_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "eval_id": self._eval_id,
                    "socket_path": (
                        str(self._socket_path) if self._socket_path else None
                    ),
                    "host": self._host,
                    "port": self._port,
                    "started_at": time.time(),
                }
            )
        )

    async def _bind_unix(self, path: Path) -> None:
        if not _has_unix_sockets():
            raise RuntimeError(
                "ACP UNIX sockets require Windows 10+ or POSIX. "
                "Pass `--agent-acp=<port>` to bind a TCP loopback port instead."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unlink any leftover socket node from a stale prior bind on the
        # same path. ``_cleanup_stale_discovery_files`` already covers the
        # default path case via the discovery file; this catches
        # user-supplied paths and the rare case where the discovery file
        # is gone but the socket node survived. ONLY unlink actual socket
        # nodes — a user passing ``--acp-server=/etc/passwd`` should get
        # an error, not data loss.
        if path.exists() or path.is_symlink():
            try:
                mode = path.lstat().st_mode
            except OSError as e:
                raise RuntimeError(
                    f"Cannot stat existing path {path} for ACP socket bind: {e}"
                ) from e
            if not stat.S_ISSOCK(mode):
                raise RuntimeError(
                    f"Refusing to bind ACP server at {path}: path exists and "
                    "is not a socket. Pick a different path or remove it first."
                )
            path.unlink()
        self._server = await asyncio.start_unix_server(
            self._on_connection,
            path=str(path),
        )
        self._socket_path = path

    async def _bind_tcp(self, port: int, host: str = "127.0.0.1") -> None:
        self._server = await asyncio.start_server(
            self._on_connection,
            host=host,
            port=port,
        )
        # Resolve the actual bound port (in case the caller passed 0 for
        # an ephemeral port).
        sockets = self._server.sockets or ()
        if sockets:
            self._port = sockets[0].getsockname()[1]
        else:
            self._port = port
        self._host = host

    async def stop(self) -> None:
        """Stop accepting, close all connections, remove socket + discovery file."""
        # Stop accepting new connections first.
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                logger.exception("Error closing ACP server socket")
            self._server = None

        # Close all live connections. Each Connection has an internal
        # receive task; close() shuts it down cleanly.
        for conn in list(self._connections):
            try:
                await conn.close()
            except Exception:
                logger.exception("Error closing ACP connection")
        self._connections.clear()

        # Cancel any per-connection main-loop tasks still alive.
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        self._tasks.clear()

        # Remove the AF_UNIX socket node (TCP doesn't leave anything behind).
        if self._socket_path is not None:
            try:
                self._socket_path.unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    "Error removing ACP socket file: %s", self._socket_path
                )

        # Remove the discovery file.
        if self._discovery_path is not None:
            try:
                self._discovery_path.unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    "Error removing ACP discovery file: %s", self._discovery_path
                )

    async def _on_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Wrap a newly accepted socket in an :class:`acp.connection.Connection`.

        Phase 8: the router is empty, so every incoming method call
        gets a "method not found" response. The framing + lifecycle
        still works end-to-end — clients can connect, send JSON-RPC,
        get well-formed responses, and disconnect cleanly.
        """
        router = MessageRouter()
        # ``listening=False`` lets us drive the receive loop here and
        # know when the peer disconnects, so we can clean up tracking.
        conn = Connection(
            handler=router,
            writer=writer,
            reader=reader,
            listening=False,
        )
        self._connections.add(conn)
        try:
            await conn.main_loop()
        except Exception:
            logger.exception("ACP connection main loop failed")
        finally:
            try:
                await conn.close()
            except Exception:
                logger.exception("Error closing ACP connection after main loop")
            self._connections.discard(conn)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


@asynccontextmanager
async def acp_server(
    *,
    eval_id: str,
    transport: bool | int | str | None,
) -> AsyncIterator[_AcpServer | None]:
    """Optional ACP server context manager keyed off the eval config.

    Yields the started :class:`_AcpServer` when ``transport`` is truthy,
    else yields ``None`` so the eval runner can wrap its body
    unconditionally without branching on whether ACP is enabled.

    ``False`` (the result of ``--agent-acp=false``), ``None`` (no
    flag), and ``0`` are all treated as disabled.
    """
    if not transport:
        yield None
        return
    server = _AcpServer(eval_id=eval_id, transport=transport)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _discovery_dir() -> Path:
    """The directory where discovery JSON files + default sockets live."""
    return inspect_data_dir("acp")


def _default_socket_path(eval_id: str) -> Path:
    """Default AF_UNIX socket path for a given eval_id."""
    return _discovery_dir() / f"{eval_id}.sock"


def _cleanup_stale_discovery_files() -> None:
    """Remove discovery JSON files whose owning PID is no longer alive.

    Called by :meth:`_AcpServer.start` before writing our own discovery
    file. Also unlinks the orphaned AF_UNIX socket node recorded in the
    stale file so subsequent binds on the same path don't trip over a
    leftover inode.
    """
    acp_dir = _discovery_dir()
    if not acp_dir.exists():
        return
    for path in acp_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            pid = int(data.get("pid", -1))
            if pid <= 0 or _pid_alive(pid):
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


def _pid_alive(pid: int) -> bool:
    """Return ``True`` if a process with ``pid`` is currently alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # signal 0 = existence check only
        return True
    except (ProcessLookupError, OSError):
        return False


def _parse_host_port(value: str) -> tuple[str, int] | None:
    """Parse a ``host:port`` or ``[ipv6]:port`` string.

    Returns ``(host, port)`` if ``value`` is a well-formed network
    address, else ``None`` (treat the value as a UNIX socket path).

    A bare integer is intentionally NOT parsed here — the caller
    handles ``int`` transports separately for the loopback-port shape.
    """
    if not value:
        return None
    # IPv6 bracket form: [::1]:4444
    if value.startswith("["):
        end = value.find("]:")
        if end == -1:
            return None
        host = value[1:end]
        port_str = value[end + 2 :]
        try:
            return host, int(port_str)
        except ValueError:
            return None
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
        return host, int(port_str)
    except ValueError:
        return None


def _has_unix_sockets() -> bool:
    """Whether the current platform supports AF_UNIX sockets.

    POSIX always supports them. Windows 10/11 do; older Windows
    versions don't expose :func:`asyncio.start_unix_server`.
    """
    if sys.platform != "win32":
        return True
    return hasattr(asyncio, "start_unix_server")
