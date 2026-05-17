"""JSON-RPC 2.0 transport server for ACP clients.

When an eval is launched with ``acp_server`` enabled (via the
``--acp-server`` CLI flag or the ``EvalConfig.acp_server`` field), the
:func:`acp_server` async context manager spins up a JSON-RPC server
bound to either an AF_UNIX socket (default) or a TCP loopback port,
writes a discovery JSON file so clients can enumerate running evals,
and accepts incoming connections.

This module is responsible for **transport only** — bind / accept /
shutdown plus per-connection setup that delegates to
:class:`ConnectionHandler` from :mod:`.connection` for the actual
method dispatch and to :class:`Forwarders` from :mod:`.session_router`
for outbound forwarding.

asyncio anchor — this module is **asyncio-bound** at the
``acp.Connection`` boundary. See ``design/acp/agent-acp.md`` "asyncio /
anyio boundary" for the rationale.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import time
from contextlib import asynccontextmanager
from logging import getLogger
from pathlib import Path
from typing import AsyncIterator, cast

from acp.agent.router import build_agent_router
from acp.connection import Connection
from acp.interfaces import Agent

from inspect_ai.agent._acp.connection import ConnectionHandler
from inspect_ai.agent._acp.discovery import (
    cleanup_stale_discovery_files,
    default_socket_path,
    discovery_dir,
    has_unix_sockets,
    parse_host_port,
)
from inspect_ai.agent._acp.inspect_ext import register_inspect_routes

logger = getLogger(__name__)


class AcpServer:
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
        # Fail fast when running under trio: the underlying ``acp``
        # library uses asyncio.StreamReader/Writer/Future directly, so
        # ``asyncio.start_unix_server`` / ``asyncio.start_server`` below
        # need an asyncio loop. The rest of inspect_ai runs fine under
        # trio (anyio-native); only ``--acp-server`` is incompatible.
        # Error here rather than surfacing the asyncio call's confusing
        # "no running event loop" message. See
        # ``design/acp/agent-acp.md`` "asyncio / anyio boundary" for the
        # full rationale.
        from inspect_ai._util._async import current_async_backend

        if current_async_backend() == "trio":
            raise RuntimeError(
                "--acp-server (Agent Client Protocol server) cannot be used "
                "with the trio async backend — the underlying `acp` library "
                "is asyncio-only. Either unset INSPECT_ASYNC_BACKEND (default "
                "asyncio) or omit --acp-server."
            )

        # Clean up any stale discovery files / orphan sockets from
        # processes that crashed without unregistering.
        cleanup_stale_discovery_files()

        if self._transport is True:
            await self._bind_unix(default_socket_path(self._eval_id))
        elif isinstance(self._transport, int) and not isinstance(self._transport, bool):
            await self._bind_tcp(self._transport)
        elif isinstance(self._transport, str):
            host_port = parse_host_port(self._transport)
            if host_port is not None:
                host, port = host_port
                await self._bind_tcp(port, host=host)
            else:
                await self._bind_unix(Path(self._transport))
        else:
            # ``transport`` was falsy — the caller should have skipped
            # us via the asynccontextmanager guard. Defensive check.
            raise ValueError(f"Unsupported acp_server transport: {self._transport!r}")

        # Write the discovery file describing this server.
        self._discovery_path = discovery_dir() / f"{os.getpid()}.json"
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
        if not has_unix_sockets():
            raise RuntimeError(
                "ACP UNIX sockets require Windows 10+ or POSIX. "
                "Pass `--acp-server=<port>` to bind a TCP loopback port instead."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unlink any leftover socket node from a stale prior bind on
        # the same path. ``cleanup_stale_discovery_files`` already
        # covers the default path case via the discovery file; this
        # catches user-supplied paths and the rare case where the
        # discovery file is gone but the socket node survived. ONLY
        # unlink actual socket nodes — a user passing
        # ``--acp-server=/etc/passwd`` should get an error, not data
        # loss.
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
        # Resolve the actual bound port (in case the caller passed 0
        # for an ephemeral port).
        sockets = self._server.sockets or ()
        if sockets:
            self._port = sockets[0].getsockname()[1]
        else:
            self._port = port
        self._host = host

    async def stop(self) -> None:
        """Stop accepting, close all connections, remove socket + discovery file."""
        # Stop accepting new connections — but do NOT await
        # ``wait_closed()`` yet. On Python 3.12+, ``wait_closed()``
        # blocks until every active connection drains, so it must run
        # AFTER we've closed the per-connection handlers below.
        if self._server is not None:
            self._server.close()

        # Close all live connections. Each Connection has an internal
        # receive task; close() shuts it down cleanly.
        for conn in list(self._connections):
            try:
                await conn.close()
            except Exception:
                logger.exception("Error closing ACP connection")
        self._connections.clear()

        # Now safe to await ``wait_closed`` — there are no live
        # connections keeping it pinned open.
        if self._server is not None:
            try:
                await self._server.wait_closed()
            except Exception:
                logger.exception("Error closing ACP server socket")
            self._server = None

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

        Each accepted connection gets its own :class:`ConnectionHandler`
        instance plus a fresh :class:`MessageRouter` (built by
        :func:`acp.agent.router.build_agent_router`). Per-connection
        state — synthetic control sessionId, bound target sessionId —
        lives on the handler so two concurrent clients can pick
        different target sessions without interference.
        """
        handler = ConnectionHandler()
        # The ACP `Agent` protocol declares the full method surface;
        # we implement the subset our handler needs (initialize,
        # new/load session, prompt, cancel) and leave the rest as
        # method-not-found via `build_agent_router`'s `func=None`
        # fall-through. `cast` avoids a structural-typing complaint
        # about the partial implementation.
        router = build_agent_router(cast(Agent, handler))
        # Register the Inspect extension methods (the ``inspect/*``
        # action namespace). See :mod:`inspect_ext` for the method
        # name strings + param models.
        register_inspect_routes(router, handler)
        # ``listening=False`` lets us drive the receive loop here and
        # know when the peer disconnects, so we can clean up tracking.
        conn = Connection(
            handler=router,
            writer=writer,
            reader=reader,
            listening=False,
        )
        # Attach the connection back-reference so handlers can push
        # `session/update` notifications via `conn.send_notification`.
        handler.connection = conn
        self._connections.add(conn)
        try:
            await conn.main_loop()
        except Exception:
            logger.exception("ACP connection main loop failed")
        finally:
            # Stop forwarder tasks + detach subscribers BEFORE closing
            # the connection so the forwarder's last send_notification
            # call (if any) completes through a live writer.
            await handler._stop_forwarders()
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
) -> AsyncIterator[AcpServer | None]:
    """Optional ACP server context manager keyed off the eval config.

    Yields the started :class:`AcpServer` when ``transport`` is truthy,
    else yields ``None`` so the eval runner can wrap its body
    unconditionally without branching on whether ACP is enabled.

    ``False`` (the result of ``--acp-server=false``), ``None`` (no
    flag), and ``0`` are all treated as disabled.
    """
    if not transport:
        yield None
        return
    server = AcpServer(eval_id=eval_id, transport=transport)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()
