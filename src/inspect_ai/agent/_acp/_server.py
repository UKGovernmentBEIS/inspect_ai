"""Phase 8/9 — JSON-RPC 2.0 transport server for ACP clients.

When an eval is launched with ``agent_acp`` enabled (via the
``--agent-acp`` CLI flag or the ``EvalConfig.agent_acp`` field), the
:func:`acp_server` async context manager spins up a JSON-RPC server
bound to either an AF_UNIX socket (default) or a TCP loopback port,
writes a discovery JSON file so clients can enumerate running evals,
and accepts incoming connections.

Phase 8 landed the transport (bind / accept / connection lifecycle)
with an empty router that returned ``method not found`` for every
request. Phase 9 installs **per-connection** method dispatch for the
in-channel session picker: ``initialize``, ``session/new``,
``session/load``, plus ``session/prompt`` and ``session/cancel`` in
their control-session (picker) form. Each accepted connection gets
its own handler instance + state so two concurrent clients can pick
different target sessions independently.

Phase 9 does NOT implement ``session/prompt`` forwarding to a bound
target's :func:`AcpSession.submit_user_message`, ``session/cancel``
forwarding to :func:`AcpSession.cancel_current_turn`, or
``session/update`` replay from the in-process bus to the socket.
Those land in Phase 10.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import Any, AsyncIterator, cast

from acp.agent.router import build_agent_router
from acp.connection import Connection
from acp.exceptions import RequestError
from acp.interfaces import Agent
from acp.meta import CLIENT_METHODS, PROTOCOL_VERSION
from acp.schema import (
    AgentCapabilities,
    AgentMessageChunk,
    Implementation,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PromptResponse,
    SessionCapabilities,
    TextContentBlock,
)
from shortuuid import uuid

from inspect_ai._util.appdirs import inspect_data_dir
from inspect_ai.agent._acp._picker import (
    PICKER_META_KEY,
    _PickerTarget,
    build_picker_notification,
    list_picker_targets,
    resolve_selection,
)

logger = getLogger(__name__)

# Version banner included in InitializeResponse. The eval is the
# server in the ACP relationship.
_AGENT_NAME = "inspect-ai"
_AGENT_VERSION = "0.9"  # Phase 9 picker; bumps with each protocol phase.

# JSON-RPC method name for the picker confirmation / target list
# notification sent on `session/update`.
_SESSION_UPDATE_METHOD = CLIENT_METHODS["session_update"]


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

        Each accepted connection gets its own :class:`_ConnectionHandler`
        instance plus a fresh :class:`MessageRouter` (built by
        :func:`acp.agent.router.build_agent_router`). Per-connection
        state — synthetic control sessionId, bound target sessionId —
        lives on the handler so two concurrent clients can pick
        different target sessions without interference.

        Phase 9 handles ``initialize`` / ``session/new`` /
        ``session/load`` / ``session/prompt`` (picker selection only)
        / ``session/cancel`` (silent no-op). Other methods fall
        through ``build_agent_router``'s standard registration with
        no implementation → ``method not found``.
        """
        handler = _ConnectionHandler()
        # The ACP `Agent` protocol declares the full method surface;
        # we implement the subset Phase 9 needs (initialize, new/load
        # session, prompt, cancel) and leave the rest as
        # method-not-found via `build_agent_router`'s `func=None` fall-
        # through. `cast` avoids a structural-typing complaint about
        # the partial implementation.
        router = build_agent_router(cast(Agent, handler))
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


@dataclass
class _ConnectionState:
    """Per-connection routing state.

    Three independent fields combine into the connection's mode:

    - ``wire_session_id``: the sessionId the client knows. Returned
      from ``session/new`` (synthetic control id when the picker is
      shown, or the target id on single-target auto-bind) or passed
      in by the client to ``session/load`` (always equals the matched
      target id). **Stable across rebind** — the picker flow's
      contract is "client's sessionId stays stable from their POV",
      so a successful picker selection keeps ``wire_session_id``
      unchanged while ``target_session_id`` switches from None to
      the chosen target.
    - ``target_session_id``: the internal ``_LiveAcpSession.session_id``
      this connection is bound to. None while the picker is pending.
    - ``picker_targets``: snapshot of the target list shown to the
      client when picker mode was entered (or re-displayed). Numeric
      picker selections (``"1"``, ``"2"``) are resolved against this
      snapshot rather than a fresh enumeration — if samples start /
      finish / reorder between the picker push and the selection
      prompt, the index the user picked still resolves to the same
      target they saw.

    Mode derivation:

    - **Unbound**: ``wire_session_id is None`` (client hasn't called
      ``session/new`` or ``session/load`` yet).
    - **Control / picker**: ``wire_session_id`` set,
      ``target_session_id is None``, ``picker_targets`` is a list.
    - **Bound**: ``target_session_id`` set (``wire_session_id`` is
      also set; ``picker_targets`` is None).

    Validation: every incoming ``session/prompt`` and
    ``session/cancel`` must carry the same sessionId as the
    connection's ``wire_session_id`` — mismatches are rejected
    rather than silently re-routed.
    """

    wire_session_id: str | None = None
    target_session_id: str | None = None
    picker_targets: list[_PickerTarget] | None = None


class _ConnectionHandler:
    """Per-connection method handler. Plays the ACP ``Agent`` role."""

    def __init__(self) -> None:
        self.connection: Connection | None = None
        self.state = _ConnectionState()

    # ------------------------------------------------------------------
    # ACP Agent surface — implemented methods
    # ------------------------------------------------------------------

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: Any = None,
        client_info: Any = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        """Standard ACP handshake. Negotiate protocol version + advertise capabilities."""
        # Server speaks PROTOCOL_VERSION; if the client asked for an
        # older version we currently still answer with our version
        # (acp protocol contract: respond with min(client, server)
        # eventually, but Phase 9 only supports the latest).
        return InitializeResponse(
            protocol_version=min(protocol_version, PROTOCOL_VERSION),
            agent_capabilities=AgentCapabilities(
                load_session=True,
                session_capabilities=SessionCapabilities(),
            ),
            agent_info=Implementation(name=_AGENT_NAME, version=_AGENT_VERSION),
        )

    async def new_session(
        self,
        cwd: str,  # unused but required by the ACP method signature
        mcp_servers: Any = None,  # unused — Phase 9 doesn't host MCP servers
        **kwargs: Any,
    ) -> NewSessionResponse:
        """Create a session. With a single target → auto-bind; else picker."""
        targets = list_picker_targets()
        if len(targets) == 1:
            return await self._auto_bind(targets[0])
        return await self._enter_picker_mode(targets)

    async def load_session(
        self,
        cwd: str,  # unused but required by the ACP method signature
        session_id: str,
        mcp_servers: Any = None,
        **kwargs: Any,
    ) -> LoadSessionResponse:
        """Bind directly to a known target sessionId; error if unknown.

        Standard ACP semantics: ``session/load`` is "load *this*
        specific session". If the id is unknown we return
        ``invalid_params`` rather than silently falling back to a
        picker — clients can call ``session/new`` for the picker.
        """
        targets = list_picker_targets()
        match = next((t for t in targets if t.session_id == session_id), None)
        if match is None:
            raise RequestError.invalid_params(
                {
                    "reason": "unknown session_id",
                    "session_id": session_id,
                    "hint": "call session/new for the picker flow",
                }
            )
        # On a successful load the wire sessionId IS the target's id
        # (the client passed it in, we matched it, no rebind happens).
        self.state.wire_session_id = match.session_id
        self.state.target_session_id = match.session_id
        self.state.picker_targets = None
        await self._notify_binding(match)
        return LoadSessionResponse()

    async def prompt(
        self,
        prompt: list[Any],
        session_id: str,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> PromptResponse:
        """Handle a prompt request. Selection in control mode; placeholder otherwise."""
        # Unbound: client skipped session/new and session/load.
        if self.state.wire_session_id is None:
            raise RequestError.invalid_request(
                {"reason": ("session/prompt called before session/new or session/load")}
            )
        # Reject if the prompt names a different sessionId than the
        # one this connection is currently keyed to. This blocks
        # cross-session prompts on a misbehaving / confused client.
        if session_id != self.state.wire_session_id:
            raise RequestError.invalid_params(
                {
                    "reason": "session_id does not match this connection's session",
                    "session_id": session_id,
                    "expected": self.state.wire_session_id,
                }
            )

        if self.state.picker_targets is not None:
            # Picker selection — first prompt in control mode resolves
            # to a target and rebinds the connection.
            return await self._handle_picker_selection(prompt)
        if self.state.target_session_id is not None:
            # Bound mode. Phase 10 will forward to the target's
            # submit_user_message; Phase 9 stops here with a clear
            # method-not-found so users know they're hitting the
            # deferred boundary, not a generic bug.
            raise RequestError.method_not_found("session/prompt")
        # Defensive — wire is set but neither picker nor bound (should
        # be unreachable given the new/load handlers leave the state
        # in one of those two states).
        raise RequestError.internal_error({"reason": "connection in unknown state"})

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        """No-op in Phase 9. Phase 10 forwards to cancel_current_turn.

        Notifications can't return errors, so a mismatched sessionId
        is silently dropped — the alternative of routing it through
        anyway risks cross-session interference once Phase 10 wires
        the real forwarding.
        """
        if (
            self.state.wire_session_id is None
            or session_id != self.state.wire_session_id
        ):
            return None
        # Phase 10 will dispatch to the bound target's
        # cancel_current_turn here. Phase 9 just accepts silently.
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _enter_picker_mode(
        self, targets: list[_PickerTarget]
    ) -> NewSessionResponse:
        """Mint a control sessionId, snapshot targets, push picker payload."""
        control_id = uuid()
        self.state.wire_session_id = control_id
        self.state.target_session_id = None
        # Snapshot the target list so that the numeric selection (1, 2,
        # ...) resolves against the exact list the client was shown.
        # A fresh enumeration at selection time could disagree if a
        # sample finished or a new one started in between.
        self.state.picker_targets = list(targets)
        notif = build_picker_notification(control_id, targets)
        await self._send_session_update(notif)
        return NewSessionResponse(session_id=control_id)

    async def _auto_bind(self, target: _PickerTarget) -> NewSessionResponse:
        """Skip the picker for the single-target case; bind immediately.

        On the auto-bind path the wire sessionId IS the target's id
        (it's what we hand back in the NewSessionResponse), so the
        client and server agree on the same id.
        """
        self.state.wire_session_id = target.session_id
        self.state.target_session_id = target.session_id
        self.state.picker_targets = None
        await self._notify_binding(target)
        return NewSessionResponse(session_id=target.session_id)

    async def _handle_picker_selection(
        self, prompt_blocks: list[Any]
    ) -> PromptResponse:
        """Parse selection from prompt content, rebind the connection.

        Two-step resolution so we never bind to a sample that has
        already finished:

        1. Resolve the selection against the **snapshot** taken at
           picker-push time. This is what makes the client's numeric
           pick ("1", "2", ...) line up with what they actually saw —
           samples that started/finished/reordered since don't move
           the meaning of the indices.
        2. Re-validate the resolved sessionId is still present in a
           **fresh** ``list_picker_targets()`` enumeration. If the
           sample finished between picker push and selection prompt,
           binding would attach to a sessionId no agent owns; Phase
           10's prompt/cancel forwarding would have nowhere to forward.
           Fall through to redisplay in that case.

        On any miss (bad selection OR stale target), we redisplay and
        re-snapshot so the next numeric pick refers to the redisplayed
        list.
        """
        assert self.state.wire_session_id is not None
        assert self.state.picker_targets is not None
        selection_text = _prompt_text(prompt_blocks)
        target = resolve_selection(selection_text, self.state.picker_targets)

        if target is not None:
            # Confirm the resolved target is still live before binding.
            fresh_targets = list_picker_targets()
            still_active = any(t.session_id == target.session_id for t in fresh_targets)
            if not still_active:
                target = None  # Fall through to the redisplay path.

        if target is None:
            # Redisplay with a fresh enumeration. Re-snapshot too so
            # the client's next numeric pick maps onto the new list.
            fresh_targets = list_picker_targets()
            self.state.picker_targets = list(fresh_targets)
            notif = build_picker_notification(self.state.wire_session_id, fresh_targets)
            await self._send_session_update(notif)
            return PromptResponse(stop_reason="end_turn")

        # Rebind: set the target, clear the picker snapshot. The wire
        # sessionId stays unchanged — the design contract is that the
        # client's sessionId is stable across rebind, so all subsequent
        # outbound notifications continue to use wire_session_id.
        self.state.target_session_id = target.session_id
        self.state.picker_targets = None
        await self._notify_binding(target)
        return PromptResponse(stop_reason="end_turn")

    async def _notify_binding(self, target: _PickerTarget) -> None:
        """Push a confirmation `session/update` carrying the bound target.

        The notification's sessionId is the connection's
        ``wire_session_id`` (NOT necessarily the target's id) so the
        client sees updates on the session id they already know.
        Target details live in the structured ``_meta`` payload.
        """
        assert self.state.wire_session_id is not None
        notif = build_picker_notification(self.state.wire_session_id, [target])
        # Override the visible text so it reads as a confirmation
        # rather than a "pick one" prompt. We built this notification
        # from build_picker_notification which always returns an
        # AgentMessageChunk with a TextContentBlock — assert for mypy.
        assert isinstance(notif.update, AgentMessageChunk)
        notif.update.content = TextContentBlock(
            type="text",
            text=(
                f"Bound to {target.task} / sample {target.sample_id} / "
                f"epoch {target.epoch} [{target.session_id}]."
            ),
        )
        # Keep the structured target list under the same _meta key
        # for consistency with the picker flow.
        assert notif.field_meta is not None
        notif.field_meta[PICKER_META_KEY] = [
            {
                "sessionId": target.session_id,
                "task": target.task,
                "sampleId": target.sample_id,
                "epoch": target.epoch,
            }
        ]
        await self._send_session_update(notif)

    async def _send_session_update(self, notification: Any) -> None:
        """Send a session/update notification over the connection."""
        if self.connection is None:
            # Defensive — this only happens in tests that construct
            # the handler without going through _on_connection.
            logger.warning(
                "Dropped session/update notification: connection not attached"
            )
            return
        payload = notification.model_dump(mode="json", by_alias=True, exclude_none=True)
        await self.connection.send_notification(_SESSION_UPDATE_METHOD, payload)


def _prompt_text(prompt_blocks: list[Any]) -> str:
    """Concatenate text-block content from a prompt request.

    Picker selection is a short string; only text blocks contribute.
    Image / audio / resource blocks are ignored at this stage.
    """
    parts: list[str] = []
    for block in prompt_blocks:
        if isinstance(block, TextContentBlock):
            parts.append(block.text)
    return "".join(parts).strip()


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
