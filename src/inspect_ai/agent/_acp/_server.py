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
import math
import os
import stat
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterator, Literal, cast

import anyio
from acp.agent.router import build_agent_router
from acp.connection import Connection
from acp.exceptions import RequestError
from acp.helpers import plan_entry, session_notification, update_plan
from acp.interfaces import Agent
from acp.meta import CLIENT_METHODS, PROTOCOL_VERSION
from acp.router import Route
from acp.schema import (
    AgentCapabilities,
    AgentMessageChunk,
    Implementation,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PromptResponse,
    SessionCapabilities,
    SessionNotification,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
)
from pydantic import BaseModel, Field
from shortuuid import uuid

from inspect_ai.agent._acp._discovery import (
    _cleanup_stale_discovery_files,
    _default_socket_path,
    _discovery_dir,
    _has_unix_sockets,
    _parse_host_port,
    _pid_alive,  # noqa: F401 — re-exported for back-compat with existing tests
)
from inspect_ai.agent._acp._picker import (
    PICKER_META_KEY,
    _PickerTarget,
    build_picker_notification,
    list_picker_targets,
    resolve_selection,
)
from inspect_ai.agent._acp._router import replay_transcript
from inspect_ai.event import SpanBeginEvent, SpanEndEvent
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.util._span import AGENT_SPAN_TYPE

if TYPE_CHECKING:
    from inspect_ai.agent._acp._session import AcpSession
    from inspect_ai.log._samples import ActiveSample

logger = getLogger(__name__)

# Version banner included in InitializeResponse. The eval is the
# server in the ACP relationship.
_AGENT_NAME = "inspect-ai"
_AGENT_VERSION = "0.10"  # Phase 10 forwarding + replay + plan policy + raw events.

# JSON-RPC method name for the picker confirmation / target list
# notification sent on `session/update`.
_SESSION_UPDATE_METHOD = CLIENT_METHODS["session_update"]

# Phase 10: non-standard JSON-RPC notification method for the opt-in
# raw event stream. Sent only when the client signaled
# ``inspect.raw_events`` in its initialize capabilities.
_RAW_EVENT_METHOD = "inspect/event"

# Phase 10: clients whose `client_info.name` matches this allowlist
# (case-insensitive) are treated as plan-rendering — the forwarder
# substitutes `AgentPlanUpdate` for `update_plan` / `todo_write`
# tool-call notifications. Clients with first-class `Plan` UI:
# - Zed (live plan panel + completed-plan snapshot in chat history)
# - Toad (sidebar plan widget with status icons + priority pills)
# Other clients can opt in explicitly via the `_meta` key below.
PLAN_RENDERING_CLIENTS = frozenset({"zed", "toad"})

# Phase 10: capability flags consumed from `clientCapabilities._meta`.
# Standard ACP extensibility pattern (`_meta` is reserved for arbitrary
# vendor metadata; clients who don't recognize the keys ignore them).
PLAN_RENDERING_META_KEY = "inspect.plan_rendering"
RAW_EVENTS_META_KEY = "inspect.raw_events"

# Phase 10: tool names that translate to ACP's `AgentPlanUpdate` for
# plan-capable clients. Hard-coded by tool name (matches Inspect's
# first-party planning tools — see `tool/_tools/_update_plan.py` and
# `tool/_tools/_todo_write.py`). A future capability marker on tools
# could remove the name coupling; not needed today.
PLAN_TOOL_NAMES = frozenset({"update_plan", "todo_write"})

# Phase 10 replay parameters (hard-coded; configurable later).
# REPLAY_MAX_EVENTS caps replay payload size on late attach so a
# very long-running sample doesn't dump thousands of events on
# every new connection. ELISION_THRESHOLD_BYTES truncates oversized
# tool-call arguments / results during replay (the user can still
# see WHAT tool ran; the inline data is replaced with an elision
# marker if it'd flood the wire).
REPLAY_MAX_EVENTS = 100
ELISION_THRESHOLD_BYTES = 4096


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
        # Register non-standard `inspect/*` action methods that the
        # ACP Agent protocol doesn't include. Always advertised — no
        # capability opt-in. Clients that don't know about them
        # simply don't call them; method dispatch is per-connection
        # so the handler bindings are unique per connection.
        router.add_route(
            Route(
                method="inspect/cancel_sample",
                func=_wrap_action_handler(handler.cancel_sample, _CancelSampleParams),
                kind="request",
            )
        )
        router.add_route(
            Route(
                method="inspect/cancel_tool_call",
                func=_wrap_action_handler(
                    handler.cancel_tool_call, _CancelToolCallParams
                ),
                kind="request",
            )
        )
        router.add_route(
            Route(
                method="inspect/new_session",
                func=_wrap_action_handler(
                    handler.inspect_new_session, _NewSessionParams
                ),
                kind="request",
            )
        )
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

    # Phase 10 client-capability flags, decided at initialize() time
    # and frozen for the connection lifetime. The Phase 10 forwarder
    # consults these to decide whether to substitute AgentPlanUpdate
    # for plan-tool notifications and whether to also forward raw
    # transcript events.
    client_renders_plan: bool = False
    raw_events_enabled: bool = False


class _ConnectionHandler:
    """Per-connection method handler. Plays the ACP ``Agent`` role."""

    def __init__(self) -> None:
        self.connection: Connection | None = None
        self.state = _ConnectionState()
        # Phase 10 forwarder runtime — populated when the connection
        # binds to a target. The receive stream is the subscriber half
        # returned by ``target.attach()``; the task body runs
        # ``_run_semantic_forwarder``. Both are cleaned up in
        # ``_on_connection``'s finally block.
        self._target: "AcpSession | None" = None
        self._semantic_stream: Any = None  # MemoryObjectReceiveStream
        self._semantic_task: asyncio.Task[None] | None = None
        # Phase 10 raw event forwarder runtime (opt-in via
        # ``inspect.raw_events`` capability). The send/receive pair
        # bridges the sync transcript subscriber callback into the
        # async forwarder task. The unsubscribe callable removes us
        # from the target transcript's subscriber list at teardown.
        self._raw_send: Any = None  # MemoryObjectSendStream
        self._raw_recv: Any = None  # MemoryObjectReceiveStream
        self._raw_task: asyncio.Task[None] | None = None
        self._raw_unsubscribe: Any = None  # Callable[[], None]
        # Per-tool stash for the plan-policy transformation. Plan-
        # capable clients suppress the in-progress ToolCallStart for
        # plan tools; we remember the raw_input + title here so when
        # the matching ToolCallProgress arrives (no raw_input on its
        # own), we can build the AgentPlanUpdate from the original
        # arguments. Cleared per tool on emit.
        self._plan_tool_stash: dict[str, dict[str, Any]] = {}

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
        """Standard ACP handshake. Negotiate protocol version + advertise capabilities.

        Also captures Phase 10 client-capability flags
        (``client_renders_plan``, ``raw_events_enabled``) so the
        per-connection forwarder can switch behavior per client.
        """
        # Capture client-capability flags. Two sources:
        # - `client_info.name` against the plan-rendering allowlist
        #   (case-insensitive) — known editors with first-class Plan UI.
        # - `clientCapabilities._meta` for explicit per-client opt-in
        #   keys (`inspect.plan_rendering`, `inspect.raw_events`).
        # Either source flips the flag on; both default off.
        name = client_info.name.lower() if client_info is not None else ""
        meta: dict[str, Any] = {}
        if client_capabilities is not None and client_capabilities.field_meta:
            meta = client_capabilities.field_meta
        self.state.client_renders_plan = name in PLAN_RENDERING_CLIENTS or bool(
            meta.get(PLAN_RENDERING_META_KEY)
        )
        self.state.raw_events_enabled = bool(meta.get(RAW_EVENTS_META_KEY))

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
        await self._start_forwarders(match.session_id)
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
            # Bound mode. Forward to the bound target session's
            # submit_user_message. Translates ACP content blocks to a
            # ChatMessageUser; only text blocks are honored fully today
            # (other variants degrade to placeholder text — see
            # ``_translate_prompt_blocks``).
            target = _find_live_session(self.state.target_session_id)
            if target is None:
                # The underlying ActiveSample finished after we bound
                # but before this prompt arrived. Surface a clear error
                # so the client can drop the binding and reconnect.
                raise RequestError.internal_error(
                    {
                        "reason": "bound session no longer active",
                        "target_session_id": self.state.target_session_id,
                    }
                )
            text = _translate_prompt_blocks(prompt)
            msg = ChatMessageUser(content=text, source="operator")
            target.submit_user_message(msg)
            return PromptResponse(stop_reason="end_turn")
        # Defensive — wire is set but neither picker nor bound (should
        # be unreachable given the new/load handlers leave the state
        # in one of those two states).
        raise RequestError.internal_error({"reason": "connection in unknown state"})

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        """Forward cancel notifications to the bound target session.

        Notifications can't return errors, so any mismatch (wrong wire
        sessionId, bound target gone, unbound connection) is silently
        dropped — the alternative of routing it through anyway risks
        cross-session interference.
        """
        if (
            self.state.wire_session_id is None
            or session_id != self.state.wire_session_id
        ):
            return None
        if self.state.target_session_id is None:
            # Connection is in picker mode (no target bound yet) — a
            # cancel here is meaningless; silently drop.
            return None
        target = _find_live_session(self.state.target_session_id)
        if target is None:
            # Bound target has already finished; nothing to cancel.
            return None
        target.cancel_current_turn()
        return None

    # ------------------------------------------------------------------
    # `inspect/*` action methods (non-standard ACP extension)
    # ------------------------------------------------------------------

    async def inspect_new_session(
        self,
        cwd: str,  # unused but kept for shape parity with session/new
        target: str,
        mcp_servers: Any = None,  # unused — Phase 9 doesn't host MCP servers
    ) -> NewSessionResponse:
        """Bind directly to ``target`` without going through the picker.

        ``target`` is a ``task/sample_id/epoch`` slash-delimited
        string. If it matches an active sample, bind immediately
        (same auto-bind path used by ``session/new`` when there's
        exactly one running sample). On miss, raise ``invalid_params``
        with the list of available targets so the client can show a
        helpful diagnostic — never silently fall through to the
        picker, which would mask an explicit-but-stale ask.

        Returns a standard :class:`NewSessionResponse` so the client
        learns the canonical sessionId (the target's uuid) to use on
        subsequent requests.
        """
        parsed = _parse_target_spec(target)
        if parsed is None:
            raise RequestError.invalid_params(
                {
                    "reason": (
                        "target must be a 'task/sample_id/epoch' string "
                        "(epoch must be an integer)"
                    ),
                    "value": target,
                }
            )
        task, sample_id, epoch = parsed
        targets = list_picker_targets()
        match = next(
            (
                t
                for t in targets
                if t.task == task and t.sample_id == sample_id and t.epoch == epoch
            ),
            None,
        )
        if match is None:
            raise RequestError.invalid_params(
                {
                    "reason": "no active session matches the requested target",
                    "requested": target,
                    "available": [f"{t.task}/{t.sample_id}/{t.epoch}" for t in targets],
                }
            )
        return await self._auto_bind(match)

    async def cancel_sample(
        self,
        session_id: str,
        action: Literal["score", "error"],
    ) -> dict[str, Any]:
        """Terminate the bound sample via :meth:`ActiveSample.interrupt`.

        ``action`` selects the post-cancel outcome:

        - ``"score"`` — run the scorer on whatever work landed.
        - ``"error"`` — mark the sample errored. Gated to match the
          TUI's button-visibility: accepted only when the sample is
          NOT already configured to ``fails_on_error`` (in that case
          the manual error action is moot — the sample would error
          on its own; only the score action is meaningful from a
          client's perspective).

        Distinct from ``session/cancel``, which interrupts the
        current turn but lets the agent loop recover. This method is
        terminal: the sample finishes.
        """
        if session_id != self.state.wire_session_id:
            raise RequestError.invalid_params(
                {
                    "reason": "session_id does not match this connection's session",
                    "session_id": session_id,
                    "expected": self.state.wire_session_id,
                }
            )
        if self.state.target_session_id is None:
            raise RequestError.invalid_request(
                {
                    "reason": (
                        "inspect/cancel_sample called before binding "
                        "(connection has no target session)"
                    )
                }
            )
        sample = _find_active_sample(self.state.target_session_id)
        if sample is None:
            raise RequestError.internal_error(
                {
                    "reason": "bound sample no longer active",
                    "target_session_id": self.state.target_session_id,
                }
            )
        if action == "error" and sample.fails_on_error:
            raise RequestError.invalid_params(
                {
                    "reason": (
                        "action='error' not permitted when sample is "
                        "configured fails_on_error=True (use action='score')"
                    )
                }
            )
        sample.interrupt(action)
        return {}

    async def cancel_tool_call(
        self,
        session_id: str,
        tool_call_id: str,
    ) -> dict[str, Any]:
        """Cancel a pending tool call by id.

        Walks the full sample transcript for a matching pending
        ``ToolEvent`` (superset of the TUI which only handles
        top-level tools). The found event's ``_cancel_fn`` — set by
        the tool dispatcher at ``_call_tools.py`` — is invoked,
        triggering the per-tool task-group cancel.

        Return value reports whether the tool is now cancelled
        (``event.cancelled`` after the call), NOT whether *this*
        request caused the cancel. So:

        - unknown id / no longer pending / sample gone → ``False``
        - pending tool with no ``_cancel_fn`` set → ``False`` (the
          ``_cancel`` no-ops; the tool keeps running)
        - pending tool with ``_cancel_fn`` → ``True``
        - already-cancelled pending tool (rapid double-cancel) →
          ``True`` (idempotent — the cancel previously landed)

        For nested tools (inside a ``task`` dispatch or
        ``as_tool`` / ``handoff``), the per-tool task-group cancel
        propagates upward through the enclosing sub-agent's run —
        see the dedicated integration test for the observed
        propagation contract.
        """
        # Avoid module-level circular import.
        from inspect_ai.event._tool import ToolEvent

        if session_id != self.state.wire_session_id:
            raise RequestError.invalid_params(
                {
                    "reason": "session_id does not match this connection's session",
                    "session_id": session_id,
                    "expected": self.state.wire_session_id,
                }
            )
        if self.state.target_session_id is None:
            raise RequestError.invalid_request(
                {
                    "reason": (
                        "inspect/cancel_tool_call called before binding "
                        "(connection has no target session)"
                    )
                }
            )
        sample = _find_active_sample(self.state.target_session_id)
        if sample is None:
            # Sample finished — nothing to cancel. Idempotent.
            return {"cancelled": False}
        for event in sample.transcript.events:
            if (
                isinstance(event, ToolEvent)
                and event.id == tool_call_id
                and event.pending
            ):
                # ``_cancel()`` is a no-op when ``_cancel_fn`` isn't
                # set OR the event was already cancelled — read the
                # post-call state rather than assuming success. In
                # current production paths ``_call_tools.py`` always
                # installs ``_cancel_fn`` before the event reaches
                # the transcript, so this primarily matters for
                # defensive correctness and the idempotent-retry
                # case.
                event._cancel()
                return {"cancelled": event.cancelled}
        return {"cancelled": False}

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
        await self._start_forwarders(target.session_id)
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
        await self._start_forwarders(target.session_id)
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

    # ------------------------------------------------------------------
    # Phase 10 — per-connection forwarders
    # ------------------------------------------------------------------

    async def _start_forwarders(self, target_session_id: str) -> None:
        """Begin live forwarding for a freshly-bound target session.

        Three-step setup ordered to avoid both lost events AND
        replay/live duplicates:

        1. **Snapshot transcript events** for replay (sync).
        2. **Attach live subscribers** (sync) — new events from this
           point land in the live forwarder's buffer.
        3. Start the **live forwarder task(s)**, but defer their
           ``send_notification`` work until after **replay completes**
           (replay emits ``session/update`` and ``inspect/event``
           notifications in order before any live ones go out).

        Snapshot + attach are both sync (no ``await`` between them),
        so no event can slip into both — events ≤ snapshot index
        go through replay; events > snapshot index go through live.

        **Rebind safety**: if the connection was previously bound to
        another target (a client calling ``session/load`` / ``new``
        twice, or selecting again post-picker), the prior forwarders
        + subscriber are torn down before installing the new ones.
        Without this teardown the old target would keep streaming
        notifications into the same connection, cross-polluting
        with the new target's stream.

        No-op if the target session can't be looked up (e.g. the
        underlying ``ActiveSample`` finished between binding and
        forwarder startup). Incoming prompts also fail with
        ``internal_error`` until the client rebinds.
        """
        # Tear down any previous binding first. Idempotent — a no-op
        # on the first bind. Cleanly cancels old forwarder tasks and
        # detaches the old subscriber so the prior target stops
        # publishing into this connection.
        await self._stop_forwarders()

        target = _find_live_session(target_session_id)
        if target is None:
            return
        self._target = target

        # SNAPSHOT (sync) — captures everything that's happened so far.
        snapshot = list(target.transcript_events_snapshot())

        # ATTACH live subscribers (also sync) — from here on new
        # events go into the live buffers, not the snapshot.
        self._semantic_stream = target.attach()
        if self.state.raw_events_enabled:
            self._raw_send, self._raw_recv = anyio.create_memory_object_stream[Any](
                max_buffer_size=math.inf
            )
            self._raw_unsubscribe = target.subscribe_transcript_events(
                self._on_raw_event
            )

        # REPLAY — emit historical notifications synchronously before
        # live ones. Raw replay (if enabled) first, then semantic.
        await self._run_replay(snapshot)

        # LIVE forwarders — drain the buffers that have been filling
        # since attach.
        self._semantic_task = asyncio.create_task(
            self._run_semantic_forwarder(target, self._semantic_stream),
            name=f"acp-fwd-semantic-{target_session_id}",
        )
        if self.state.raw_events_enabled:
            self._raw_task = asyncio.create_task(
                self._run_raw_forwarder(self._raw_recv),
                name=f"acp-fwd-raw-{target_session_id}",
            )

    async def _stop_forwarders(self) -> None:
        """Cancel forwarder tasks + detach subscribers. Idempotent."""
        # Unsubscribe from the transcript first so no more raw events
        # land in the queue while we're tearing down.
        if self._raw_unsubscribe is not None:
            try:
                self._raw_unsubscribe()
            except Exception:
                logger.exception("Error unsubscribing ACP raw forwarder")
            self._raw_unsubscribe = None
        if self._raw_send is not None:
            try:
                self._raw_send.close()
            except Exception:
                pass
            self._raw_send = None
        for task in (self._semantic_task, self._raw_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._semantic_task = None
        self._raw_task = None
        if self._target is not None and self._semantic_stream is not None:
            try:
                self._target.detach(self._semantic_stream)
            except Exception:
                logger.exception("Error detaching ACP forwarder subscriber")
        self._semantic_stream = None
        self._raw_recv = None
        self._target = None

    async def _run_semantic_forwarder(
        self, target: "AcpSession", recv_stream: Any
    ) -> None:
        """Background task: drain the subscriber stream and forward.

        Each notification has its ``session_id`` rewritten to the
        connection's ``wire_session_id`` before forwarding. The
        Phase 6 router publishes notifications keyed to the target's
        ``_LiveAcpSession.session_id``, but after a picker selection
        the connection's wire id is the synthetic control id — so
        passthroughs would otherwise reach the client with a session
        id they've never seen. The auto-bind / direct loadSession
        paths have wire == target, so the rewrite is a no-op there
        (we skip the ``model_copy`` when ids already match).
        """
        try:
            async for notif in recv_stream:
                out = self._maybe_transform_plan_tool(notif)
                if out is None:
                    continue  # plan-policy suppressed this notification
                out = self._rewrite_session_id(out)
                await self._send_session_update(out)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ACP semantic forwarder failed")

    def _rewrite_session_id(self, notif: SessionNotification) -> SessionNotification:
        """Return ``notif`` keyed to the wire sessionId.

        Cheap fast-path: when the notification already carries
        ``wire_session_id`` (auto-bind / direct loadSession cases),
        return it unchanged. Only the picker-selection path actually
        differs; that's the case the rewrite exists for.
        """
        if (
            self.state.wire_session_id is None
            or notif.session_id == self.state.wire_session_id
        ):
            return notif
        return notif.model_copy(update={"session_id": self.state.wire_session_id})

    def _on_raw_event(self, event: Any) -> None:
        """Sync transcript subscriber callback. Snapshots + enqueues for the forwarder.

        Serializes the event **here** rather than in the forwarder
        task because the subscriber callback runs BEFORE
        ``Transcript._process_event``'s attachment-extraction step
        (``walk_model_call`` reassigns ``event.call`` to an
        attachment-ref form). If we enqueued just the event reference
        and serialized later, by the time the forwarder task picked
        it up the inline ``call`` payload would already be gone. Doing
        ``model_dump`` here captures the pre-condensation state — the
        producer pays the serialization cost in exchange for the
        client seeing full inline data (this is the contract Phase 10
        documents under "pre-condensation forwarding guarantee").

        Non-blocking via ``send_nowait``; dead send half is dropped
        (the forwarder cleanup runs first on disconnect, so a closed
        stream here is an expected race).
        """
        if self._raw_send is None:
            return
        try:
            payload = event.model_dump(mode="json", by_alias=True, exclude_none=True)
        except Exception:
            logger.exception(
                "ACP raw event subscriber: event failed to serialize; skipping"
            )
            return
        try:
            self._raw_send.send_nowait(payload)
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            # Forwarder task already shut down; drop silently.
            pass

    async def _run_raw_forwarder(self, recv_stream: Any) -> None:
        """Background task: drain serialized raw events out as inspect/event."""
        try:
            async for payload in recv_stream:
                if self.connection is None:
                    return
                await self.connection.send_notification(_RAW_EVENT_METHOD, payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ACP raw forwarder failed")

    def _maybe_transform_plan_tool(
        self, notif: SessionNotification
    ) -> SessionNotification | None:
        """Apply the per-connection plan-policy transformation.

        For plan-capable clients (``state.client_renders_plan``):
        - ToolCallStart for a plan tool with ``status="in_progress"``:
          stash raw_input + title for later use; suppress (return None).
        - ToolCallStart for a plan tool with terminal status (e.g.
          ``status="completed"`` — instant-complete case): build and
          return the ``AgentPlanUpdate`` directly.
        - ToolCallProgress for a previously-stashed plan tool: build
          and return the ``AgentPlanUpdate`` using the stashed input,
          then clear the stash.
        - Any other notification: passthrough.

        Non-plan-capable clients always passthrough.
        """
        if not self.state.client_renders_plan:
            return notif

        update = notif.update
        if isinstance(update, ToolCallStart):
            title = update.title or ""
            if title not in PLAN_TOOL_NAMES:
                return notif
            # Plan tool start. Stash the (title, raw_input) pair so a
            # later ToolCallProgress can find them. raw_input is
            # populated by the Phase 6 router for all start_tool_call
            # emissions (see _router.py).
            self._plan_tool_stash[update.tool_call_id] = {
                "title": title,
                "raw_input": update.raw_input,
            }
            if update.status == "in_progress":
                # Wait for the completion notification before emitting.
                return None
            # Terminal status on start (instant-complete tool): emit
            # the Plan now and clear the stash since no Progress is
            # coming.
            stash = self._plan_tool_stash.pop(update.tool_call_id, None)
            if stash is None:
                return notif
            plan = self._build_plan_update(stash["title"], stash["raw_input"])
            return plan if plan is not None else notif

        if isinstance(update, ToolCallProgress):
            stash = self._plan_tool_stash.pop(update.tool_call_id, None)
            if stash is None:
                # Not a tracked plan tool — pass through.
                return notif
            plan = self._build_plan_update(stash["title"], stash["raw_input"])
            return plan if plan is not None else notif

        return notif

    def _build_plan_update(
        self, title: str, raw_input: Any
    ) -> SessionNotification | None:
        """Translate a plan-tool's raw_input into an AgentPlanUpdate notification.

        Returns ``None`` if the raw_input shape doesn't match what the
        named tool expects (the forwarder falls back to passthrough in
        that case). Defaults ``priority="medium"`` since neither
        ``update_plan`` nor ``todo_write`` carry priority.
        """
        if not isinstance(raw_input, dict) or self.state.wire_session_id is None:
            return None
        if title == "update_plan":
            items = raw_input.get("plan")
            content_key = "step"
        elif title == "todo_write":
            items = raw_input.get("todos")
            content_key = "content"
        else:
            return None
        if not isinstance(items, list):
            return None
        entries = []
        for item in items:
            if not isinstance(item, dict):
                continue
            entries.append(
                plan_entry(
                    str(item.get(content_key, "")),
                    status=item.get("status", "pending"),
                    priority="medium",
                )
            )
        return session_notification(self.state.wire_session_id, update_plan(entries))

    # ------------------------------------------------------------------
    # Phase 10 — replay-on-attach
    # ------------------------------------------------------------------

    async def _run_replay(self, snapshot: list[Any]) -> None:
        """Emit recent transcript history out to this connection.

        Two sub-passes (raw first if enabled, then semantic) so the
        client sees the full firehose for catch-up before semantic
        notifications start. Both passes are capped to
        :data:`REPLAY_MAX_EVENTS` to bound the payload on late
        attaches into long-running samples.

        Tool-call raw_input / raw_output (semantic notifications) and
        ToolEvent arguments / result (raw events) are elided when
        their JSON-serialized size exceeds
        :data:`ELISION_THRESHOLD_BYTES`, replaced with
        ``{"_inspect.elided": true, "_inspect.original_size": N}``.
        Live forwarding does NOT elide.

        If ``state.wire_session_id`` is unset (shouldn't happen at
        this point but defensive), we skip replay entirely.
        """
        if self.state.wire_session_id is None or self.connection is None:
            return

        # RAW replay (opt-in only). Send all transcript events (no
        # sub-agent filter) capped to the last N. Elide tool-event
        # arguments / result on the serialized payload.
        if self.state.raw_events_enabled:
            raw_events = snapshot[-REPLAY_MAX_EVENTS:]
            for event in raw_events:
                try:
                    payload = event.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    )
                except Exception:
                    logger.exception(
                        "ACP raw replay: event failed to serialize; skipping"
                    )
                    continue
                _elide_raw_event_payload(payload, ELISION_THRESHOLD_BYTES)
                await self.connection.send_notification(_RAW_EVENT_METHOD, payload)

        # SEMANTIC replay. Apply the same sub-agent filter the live
        # router uses. Take the last N events post-filter, then map to
        # SessionNotifications, then apply plan policy + elision.
        filtered = list(_filter_subagent_events(snapshot))[-REPLAY_MAX_EVENTS:]
        notifications = list(
            replay_transcript(
                filtered,
                self.state.wire_session_id,
                filter_subagents=False,  # already pre-filtered
            )
        )
        for notif in notifications:
            transformed = self._maybe_transform_plan_tool(notif)
            if transformed is None:
                continue
            elided = _elide_tool_call_notification(transformed, ELISION_THRESHOLD_BYTES)
            await self._send_session_update(elided)


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


def _translate_prompt_blocks(prompt_blocks: list[Any]) -> str:
    """Translate ACP prompt content blocks into a ChatMessageUser body.

    Phase 10 supports :class:`TextContentBlock` fully. Other ACP
    content variants (image / audio / resource / embedded-resource)
    lower to placeholder text — full multi-modal translation lands in
    Phase 13. We log a warning on first sight of a non-text block per
    connection so users notice without flooding logs.
    """
    parts: list[str] = []
    saw_non_text = False
    for block in prompt_blocks:
        if isinstance(block, TextContentBlock):
            parts.append(block.text)
        else:
            saw_non_text = True
            # Cheap descriptive placeholder. Type name is enough for
            # the agent to know "the user attached something we
            # haven't surfaced".
            type_label = getattr(block, "type", type(block).__name__)
            parts.append(f"[{type_label} content omitted]")
    if saw_non_text:
        logger.warning(
            "ACP prompt contained non-text content blocks; only text is "
            "fully translated in Phase 10. Use Phase 13's multi-modal "
            "support for richer content."
        )
    return "".join(parts)


def _find_live_session(session_id: str) -> "AcpSession | None":
    """Look up a live :class:`AcpSession` by sessionId.

    Walks :func:`inspect_ai.log._samples.active_samples` for a sample
    whose ``acp_session.session_id`` matches. Returns ``None`` if
    nothing matches (the underlying sample has finished and torn
    down its session).
    """
    from inspect_ai.log._samples import active_samples

    for sample in active_samples():
        sess = sample.acp_session
        if sess is not None and sess.session_id == session_id:
            return sess
    return None


def _find_active_sample(session_id: str) -> "ActiveSample | None":
    """Look up the :class:`ActiveSample` whose acp_session matches.

    Sibling of :func:`_find_live_session` — that helper returns the
    session, this one returns the enclosing ``ActiveSample`` because
    the ``inspect/*`` action methods need fields the session doesn't
    expose (``fails_on_error``, ``transcript``, ``interrupt``).
    """
    from inspect_ai.log._samples import active_samples

    for sample in active_samples():
        sess = sample.acp_session
        if sess is not None and sess.session_id == session_id:
            return sample
    return None


# ----------------------------------------------------------------------
# `inspect/*` action methods — sample + tool-call cancel
# ----------------------------------------------------------------------
#
# Two non-standard JSON-RPC methods that mirror affordances the Inspect
# Textual TUI provides but no generic ACP client does. Both are inbound
# requests; both validate the connection's ``wire_session_id`` first
# (same pattern as ``session/prompt`` / ``session/cancel``).
#
# - ``inspect/cancel_sample {sessionId, action}`` — terminal cancel of
#   the bound sample. ``action="score"`` runs the scorer on partial
#   work; ``action="error"`` marks the sample errored. The error
#   action is gated to match the TUI's button-visibility rule:
#   accepted only when ``sample.fails_on_error == False``.
# - ``inspect/cancel_tool_call {sessionId, toolCallId}`` — cancel a
#   pending tool call by id. Walks the full sample transcript so
#   nested tools (inside ``task`` dispatch, ``as_tool``, ``handoff``)
#   are reachable — superset of the TUI which only handles top-level.
#
# Both methods are always advertised; no capability opt-in. Clients
# that don't know about them simply don't call them.


class _CancelSampleParams(BaseModel):
    """Pydantic param model for ``inspect/cancel_sample``."""

    session_id: str = Field(alias="sessionId")
    action: Literal["score", "error"]


class _CancelToolCallParams(BaseModel):
    """Pydantic param model for ``inspect/cancel_tool_call``."""

    session_id: str = Field(alias="sessionId")
    tool_call_id: str = Field(alias="toolCallId")


class _NewSessionParams(BaseModel):
    """Pydantic param model for ``inspect/new_session``.

    Inspect-aware clients (the Phase 15 TUI, editors that already
    know which sample to attach to) pass the ``task/sample_id/epoch``
    triple directly to skip the picker. The standard ACP
    ``session/new`` pydantic schema (``NewSessionRequest``) doesn't
    allow extra top-level fields so this lives as a separate
    inspect-namespace method with its own model.
    """

    cwd: str
    mcp_servers: Any = Field(default=None, alias="mcpServers")
    target: str
    """``task/sample_id/epoch`` direct-bind spec — slash-delimited."""


def _wrap_action_handler(func: Any, model: type[BaseModel]) -> Any:
    """Build a router wrapper that validates params + unpacks kwargs.

    Mirrors :meth:`acp.router.MessageRouter._make_func` but for our
    inline Pydantic models (the ACP ``schema`` module doesn't carry
    them since ``inspect/*`` is a non-standard extension). The router
    invokes the returned callable with the raw params dict; the
    wrapper validates, extracts kwargs honoring camelCase aliases,
    and forwards to the bound handler.
    """

    async def wrapper(params: Any) -> Any:
        request = model.model_validate(params)
        kwargs = {
            field_name: getattr(request, field_name)
            for field_name in model.model_fields
        }
        return await func(**kwargs)

    return wrapper


def _filter_subagent_events(events: list[Any]) -> Iterator[Any]:
    """Yield only top-level events (depth==0 by sub-agent spans).

    Mirrors the depth-tracking logic in
    :func:`inspect_ai.agent._acp._router.replay_transcript` but
    returns events (not session notifications) so callers can apply
    counting / slicing / further transforms before mapping.
    Span begin/end markers are consumed (never yielded — they're
    bookkeeping, not user-visible content).
    """
    sub_agent_depth = 0
    boundary_span_ids: set[str] = set()
    for event in events:
        if isinstance(event, SpanBeginEvent) and event.type == AGENT_SPAN_TYPE:
            boundary_span_ids.add(event.id)
            sub_agent_depth += 1
            continue
        if isinstance(event, SpanEndEvent) and event.id in boundary_span_ids:
            boundary_span_ids.discard(event.id)
            sub_agent_depth -= 1
            continue
        if sub_agent_depth > 0:
            continue
        yield event


def _elided_marker(size_bytes: int) -> dict[str, Any]:
    """Build the standard elision marker dict."""
    return {"_inspect.elided": True, "_inspect.original_size": size_bytes}


def _maybe_elide(value: Any, threshold: int) -> Any:
    """Return an elision marker if ``value`` serializes to more than ``threshold`` bytes.

    Pass-through otherwise (including for ``None``, which doesn't
    contribute size). Serialization uses ``json.dumps(..., default=str)``
    so non-JSON-native types still get sized (best-effort).
    """
    if value is None:
        return None
    try:
        size = len(json.dumps(value, default=str))
    except Exception:
        # Couldn't size — pass through unchanged.
        return value
    if size > threshold:
        return _elided_marker(size)
    return value


def _elide_tool_call_notification(
    notif: SessionNotification, threshold: int
) -> SessionNotification:
    """Return ``notif`` with oversized raw_input/raw_output elided.

    Only affects ``ToolCallStart`` / ``ToolCallProgress`` payloads.
    Returns the original notification untouched for any other update
    variant. Uses ``model_copy(update=...)`` so the original is not
    mutated.
    """
    update = notif.update
    if not isinstance(update, (ToolCallStart, ToolCallProgress)):
        return notif
    new_raw_input = _maybe_elide(update.raw_input, threshold)
    new_raw_output = _maybe_elide(update.raw_output, threshold)
    if new_raw_input is update.raw_input and new_raw_output is update.raw_output:
        return notif  # nothing changed; skip the copy
    new_update = update.model_copy(
        update={"raw_input": new_raw_input, "raw_output": new_raw_output}
    )
    return notif.model_copy(update={"update": new_update})


def _elide_raw_event_payload(payload: dict[str, Any], threshold: int) -> None:
    """In-place elide oversized fields on a serialized transcript event payload.

    Currently targets ToolEvent's ``arguments`` and ``result`` fields
    (the most likely sources of huge inline blobs). ModelEvent's
    ``call`` field is left alone — large model-call payloads are
    handled by the log-writer's attachment-extraction step, but the
    Phase 10 raw forwarder sees them before that extraction (and
    consumers explicitly opted in for the firehose).

    Mutates ``payload`` in place since the caller built it via
    ``model_dump`` specifically for sending.
    """
    if payload.get("event") != "tool":
        return
    for key in ("arguments", "result"):
        if key in payload:
            payload[key] = _maybe_elide(payload[key], threshold)


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


def _parse_target_spec(spec: str) -> tuple[str, str, int] | None:
    """Parse a ``task/sample_id/epoch`` direct-target string.

    Returns ``(task, sample_id, epoch)`` on success, ``None`` on
    malformed input. Splits on the LAST two slashes so a task name
    containing slashes still parses correctly (sample_id with
    embedded slashes is unsupported — uncommon in practice; if it
    matters later, switch to a different delimiter or URL-encode).

    Empty task or empty sample_id is allowed (the latter happens when
    a sample has no explicit id — see ``list_picker_targets`` which
    stringifies a missing id to ``""``). Epoch must be an integer.
    """
    if not spec:
        return None
    # Strip the epoch (rightmost segment).
    rest, sep, epoch_str = spec.rpartition("/")
    if not sep:
        return None
    try:
        epoch = int(epoch_str)
    except ValueError:
        return None
    # Strip the sample_id (next-rightmost segment); whatever remains
    # is the task name.
    task, sep, sample_id = rest.rpartition("/")
    if not sep:
        return None
    return task, sample_id, epoch


# Discovery / socket helpers (``_discovery_dir``, ``_default_socket_path``,
# ``_pid_alive``, ``_parse_host_port``, ``_has_unix_sockets``,
# ``_cleanup_stale_discovery_files``) now live in ``_discovery.py`` so
# the CLI bridge and Phase 15 TUI can import them without pulling in
# server internals. The names are still re-exported here via the
# top-of-file import for back-compat.
