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
import os
import stat
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from logging import getLogger
from pathlib import Path
from typing import AsyncIterator, cast

from acp.agent.router import build_agent_router
from acp.connection import Connection
from acp.interfaces import Agent

from inspect_ai._util.discovery import (
    DISCOVERY_FILE_MODE,
    prepare_discovery_dir,
    write_discovery_file,
)
from inspect_ai._util.sockets import has_unix_sockets, parse_host_port
from inspect_ai.agent._acp._config import ACP_STREAM_BUFFER_LIMIT
from inspect_ai.agent._acp._guards import (
    NORMAL_DISCONNECT_EXC,
    install_acp_disconnect_log_filter,
)
from inspect_ai.agent._acp.connection import ConnectionHandler
from inspect_ai.agent._acp.discovery import default_socket_path, discovery_dir
from inspect_ai.agent._acp.inspect_ext import register_inspect_routes

# Socket file permissions — owner-only. Mirrors the control server's
# hardening; defence-in-depth against a misconfigured umask or a
# world-traversable parent directory.
SOCKET_FILE_MODE = DISCOVERY_FILE_MODE

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
        # Live connections, keyed by their ``Connection`` instance and
        # mapped to ``(writer, handler)`` so ``stop()`` can:
        #
        # 1. Drive each handler's graceful shutdown (drain forwarders
        #    → send ``inspect/session_ended`` → detach approver client)
        #    BEFORE closing the underlying connection, so the
        #    forwarder's last notification doesn't race the conn
        #    teardown and arrive as ``ConnectionError("Connection
        #    closed")`` (the symptom: client never sees the lifecycle
        #    pill flip to ``complete`` on eval end).
        # 2. Force-close the transport — the writer is tracked
        #    separately because we build each ``Connection`` with
        #    ``listening=False`` (we drive ``main_loop`` ourselves in
        #    ``_on_connection``), which means the receive task is NOT
        #    registered with the connection's task supervisor. So
        #    ``Connection.close()`` won't cancel the in-flight
        #    ``reader.readline()`` — it just stops the dispatcher /
        #    sender and rejects outgoing requests. Without an explicit
        #    transport close at shutdown the receive loop sits forever
        #    on ``readline()``, the per-connection ``_on_connection``
        #    task never completes, and ``Server.wait_closed()`` blocks
        #    the entire eval process from exiting until the peer
        #    disconnects.
        self._connections: dict[
            Connection, tuple[asyncio.StreamWriter, ConnectionHandler]
        ] = {}

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

        # Suppress upstream ``acp`` library tracebacks for routine peer
        # disconnects (BrokenPipe etc.) — see ``_guards`` for the
        # filter's rationale. Idempotent + global; installed here
        # because this is the earliest "we're actually running an ACP
        # server" entry point.
        install_acp_disconnect_log_filter()

        # Create the discovery directory at 0700 and sweep stale
        # entries / orphan sockets before binding. The 0700 lockdown
        # is defence-in-depth: other users on the same machine can't
        # traverse into the directory and reach the socket / read the
        # discovery JSON. See design/control-channel.md "Security model".
        prepare_discovery_dir(discovery_dir())

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

        # Write the discovery file (0600). The helper handles the
        # chmod; bare ``write_text`` would inherit umask and could end
        # up 0644, leaking the socket path / eval_id to other users on
        # a multi-user box.
        self._discovery_path = write_discovery_file(
            discovery_dir(),
            os.getpid(),
            {
                "pid": os.getpid(),
                "eval_id": self._eval_id,
                "socket_path": (str(self._socket_path) if self._socket_path else None),
                "host": self._host,
                "port": self._port,
                "started_at": time.time(),
            },
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
        # ``limit`` is the StreamReader buffer size for accepted
        # connections — see ACP_STREAM_BUFFER_LIMIT for why we override
        # asyncio's 64 KiB default.
        self._server = await asyncio.start_unix_server(
            self._on_connection,
            path=str(path),
            limit=ACP_STREAM_BUFFER_LIMIT,
        )
        self._socket_path = path
        # Owner-only on the socket file. Defence-in-depth against a
        # loosened parent dir / world-traversable user home — without
        # this the socket inherits umask and may be world-readable.
        # Best-effort: some filesystems ignore chmod.
        try:
            path.chmod(SOCKET_FILE_MODE)
        except OSError:
            pass

    async def _bind_tcp(self, port: int, host: str = "127.0.0.1") -> None:
        self._server = await asyncio.start_server(
            self._on_connection,
            host=host,
            port=port,
            limit=ACP_STREAM_BUFFER_LIMIT,
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
        try:
            # Stop accepting new connections — but do NOT await
            # ``wait_closed()`` yet. On Python 3.12+, ``wait_closed()``
            # blocks until every active connection drains, so it must run
            # AFTER we've closed the per-connection handlers below.
            if self._server is not None:
                self._server.close()

            # Phase 1: graceful per-handler shutdown BEFORE closing
            # connections. ``handler.shutdown()`` drains in-flight
            # forwarders (with the bounded grace window in
            # :meth:`Forwarders.stop`), which gives the semantic
            # forwarder a chance to send ``inspect/session_ended``
            # while the connection is still alive. On the
            # end-of-eval path :meth:`LiveAcpTransport.finalize` has
            # already closed pubsub by the time we get here, so the
            # forwarder is racing to send that final notification —
            # closing the connection first (pre-Phase-7-hardening
            # behaviour) deterministically aborted that send with
            # ``ConnectionError("Connection closed")`` and left the
            # client stuck on the ``running`` lifecycle pill.
            #
            # Best-effort: a handler shutdown failure here means we
            # log and proceed to forcibly tear down anyway — better
            # to surface the error than to hang shutdown waiting for
            # cleanup that won't complete.
            for _conn, (_writer, handler) in list(self._connections.items()):
                try:
                    await handler.shutdown(graceful=True)
                except Exception:
                    logger.exception(
                        "Error during graceful ACP handler shutdown; proceeding to close"
                    )

            # Phase 2: close the underlying connections + transports.
            # Each Connection has an internal receive task; close() shuts
            # it down cleanly — EXCEPT for the ``reader.readline()``
            # blocked in ``_receive_loop``, which ``Connection.close()``
            # does not interrupt (we constructed with ``listening=False``;
            # see the ``_connections`` field comment). Force-close the
            # writer afterwards so the underlying transport tears down
            # and ``readline()`` returns EOF — only then does the
            # per-connection ``_on_connection`` task exit and
            # ``Server.wait_closed()`` below can complete.
            for conn, (writer, _handler) in list(self._connections.items()):
                try:
                    await conn.close()
                except Exception:
                    logger.exception("Error closing ACP connection")
                try:
                    writer.close()
                except Exception:
                    pass
            self._connections.clear()

            # Now safe to await ``wait_closed`` — there are no live
            # connections keeping it pinned open.
            if self._server is not None:
                try:
                    await self._server.wait_closed()
                except Exception:
                    logger.exception("Error closing ACP server socket")
                self._server = None
        finally:
            # Always run filesystem cleanup, even if the awaits above
            # raised CancelledError (e.g. KeyboardInterrupt during eval
            # shutdown). The next-start sweep would eventually reclaim
            # stale files, but tightening the in-process invariant
            # avoids leaving artefacts behind across the shutdown gap.
            if self._socket_path is not None:
                try:
                    self._socket_path.unlink(missing_ok=True)
                except OSError:
                    logger.exception(
                        "Error removing ACP socket file: %s", self._socket_path
                    )

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
        self._connections[conn] = (writer, handler)
        try:
            await conn.main_loop()
        except NORMAL_DISCONNECT_EXC as exc:
            # Peer closed the connection ungracefully (TCP reset,
            # editor process exit, Wi-Fi drop on a routable bind).
            # Routine — log at DEBUG so we don't add a second ERROR
            # on top of the upstream ``acp.connection.main_loop``'s
            # own "Connection main loop failed" ERROR, which fires
            # before we get here (the upstream lib catches Exception,
            # logs at ERROR via the root logger, then re-raises).
            # Cleaner output would require suppressing the upstream
            # log; we accept the one upstream ERROR as the cost of
            # not coupling to the library's internal logging.
            logger.debug(
                "ACP connection main loop: peer disconnected (%s)",
                type(exc).__name__,
            )
        except Exception:
            logger.exception("ACP connection main loop failed")
        finally:
            # Stop forwarder tasks + detach subscribers BEFORE closing
            # the connection so the forwarder's last send_notification
            # call (if any) completes through a live writer. Also
            # cancels any deferred post-response sends (via
            # ``handler.shutdown``) that haven't fired yet — the
            # writer is about to close so further sends would race.
            await handler.shutdown()
            try:
                await conn.close()
            except NORMAL_DISCONNECT_EXC as exc:
                # The peer already went away (matches the main_loop
                # NORMAL_DISCONNECT_EXC branch above). ``conn.close()``
                # tries to flush the sender, which surfaces the same
                # BrokenPipe a second time. Log at DEBUG so disconnect
                # produces no ERROR noise on the eval console.
                logger.debug(
                    "ACP connection close after disconnect (%s)",
                    type(exc).__name__,
                )
            except Exception:
                logger.exception("Error closing ACP connection after main loop")
            self._connections.pop(conn, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


# Set to True by :func:`acp_server` while a server is bound and
# accepting external ACP clients. Routing shims for ``ask_user`` and
# human-approval consult this via :func:`acp_server_accepting_clients`
# to distinguish "external clients can attach" from "a LiveAcpTransport
# happens to be installed for sub-agent isolation but no server is
# running". The Live transport is opened per-sample regardless of
# ``--acp-server`` (sub-agent reachability needs the in-process
# pub/sub plumbing); only this flag actually tracks whether the eval
# is reachable from outside.
_acp_server_accepting_var: ContextVar[bool] = ContextVar(
    "_acp_server_accepting", default=False
)


def acp_server_accepting_clients() -> bool:
    """True iff an :class:`AcpServer` is bound and accepting connections.

    See :data:`_acp_server_accepting_var` for why this is separate from
    "is the current transport a :class:`LiveAcpTransport`" — the latter
    is always True inside a sample, regardless of ``--acp-server``.
    """
    return _acp_server_accepting_var.get()


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

    Flips :func:`acp_server_accepting_clients` to ``True`` for the
    duration of the bound server so the routing shims commit to ACP
    as the human channel. When ``transport`` is falsy the flag stays
    ``False`` and routing falls through to the in-proc panel /
    console — the no-``--acp-server`` baseline.
    """
    if not transport:
        yield None
        return
    server = AcpServer(eval_id=eval_id, transport=transport)
    await server.start()
    token = _acp_server_accepting_var.set(True)
    try:
        yield server
    finally:
        _acp_server_accepting_var.reset(token)
        await server.stop()
