r"""Inspect-specific deviations from standard ACP.

This module owns every part of the ACP server that goes beyond the
ACP spec. Everything here is either:

(a) a JSON-RPC method outside the ACP spec (the ``inspect/*`` namespace),
(b) a payload field carried in ``_meta`` under the ``inspect.*``
    namespace,
(c) behavior gated on Inspect-aware client capability flags.

If you're auditing the server's ACP compliance, deleting this module
would (in principle) leave a strict-ACP server behind.

Audit rule
----------

Other modules in this package must not **synthesize** ``"inspect."``
or ``"inspect/"`` string literals at runtime — they import the
constants and helpers from this module instead.

Docstring / comment references that document what a value looks like
on the wire are fine (a reader chasing ``_meta["inspect.model"]``
from a server payload has to know the literal). The rule is about
producer / consumer code, not about prose.

Producer-side grep audit::

    git grep -nE 'inspect[./]' src/inspect_ai/agent/_acp/

Filter out hits in this file, in docstrings (triple-quoted blocks),
and in line comments (``# ``). Any remaining hit is a bug to fix.
"""

from __future__ import annotations

import asyncio
import math
from logging import getLogger
from typing import TYPE_CHECKING, Any, Callable, Literal

import anyio
from acp.exceptions import RequestError
from pydantic import BaseModel, Field, ValidationError

from inspect_ai.agent._acp._guards import acp_guard, acp_send_guard

if TYPE_CHECKING:
    from acp.connection import Connection
    from acp.router import MessageRouter
    from acp.schema import SessionNotification

    from inspect_ai.agent._acp.connection import ConnectionHandler, ConnectionState
    from inspect_ai.agent._acp.picker import PickerTarget
    from inspect_ai.agent._acp.session import AcpSession
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.model._chat_message import ChatMessageSystem, ChatMessageUser

logger = getLogger(__name__)

# ---------------------------------------------------------------------------
# _meta key strings (carried on standard ACP payloads)
# ---------------------------------------------------------------------------

# clientCapabilities._meta opt-in keys. Standard ACP extensibility
# pattern (``_meta`` is reserved for arbitrary vendor metadata; clients
# who don't recognize the keys ignore them).
PLAN_RENDERING_META_KEY = "inspect.plan_rendering"
RAW_EVENTS_META_KEY = "inspect.raw_events"

# Picker payload. Carried on the ``session/update`` notification that
# pushes the multi-target picker; clients with first-class picker UI
# read the structured target list here, plain editors render the
# numbered-list text body.
PICKER_META_KEY = "inspect.picker.targets"

# Per-chunk attribution on user/system ``user_message_chunk`` and
# assistant ``agent_message_chunk`` notifications. Lets clients
# cross-reference back to the originating transcript event, render
# the model chip per chunk (correct for multi-model evals), and
# track in-flight generation state.
MESSAGE_ID_META_KEY = "inspect.message_id"
MESSAGE_ROLE_META_KEY = "inspect.message_role"
USER_SOURCE_META_KEY = "inspect.user_source"
MODEL_META_KEY = "inspect.model"
MODEL_EVENT_UUID_META_KEY = "inspect.model_event_uuid"
MODEL_EVENT_PENDING_META_KEY = "inspect.model_event_pending"
MODEL_EVENT_COMPLETE_META_KEY = "inspect.model_event_complete"


# ---------------------------------------------------------------------------
# inspect/* JSON-RPC methods (non-standard)
# ---------------------------------------------------------------------------

# Opt-in raw transcript event firehose. Sent as a JSON-RPC notification
# alongside (not instead of) ``session/update`` when the client signed
# ``inspect.raw_events`` at initialize.
INSPECT_EVENT_METHOD = "inspect/event"

# TUI-grade action methods. Always advertised — no capability opt-in.
# Clients that don't know about them simply don't call them.
INSPECT_CANCEL_SAMPLE_METHOD = "inspect/cancel_sample"
INSPECT_CANCEL_TOOL_CALL_METHOD = "inspect/cancel_tool_call"
INSPECT_NEW_SESSION_METHOD = "inspect/new_session"
INSPECT_LIST_SESSIONS_METHOD = "inspect/list_sessions"


# ---------------------------------------------------------------------------
# Capability-detection inputs
# ---------------------------------------------------------------------------

# Clients whose ``client_info.name`` matches this allowlist
# (case-insensitive) are treated as plan-rendering — the forwarder
# substitutes ``AgentPlanUpdate`` for ``update_plan`` / ``todo_write``
# tool-call notifications. Clients with first-class ``Plan`` UI:
# - Zed (live plan panel + completed-plan snapshot in chat history)
# - Toad (sidebar plan widget with status icons + priority pills)
# Other clients can opt in explicitly via ``PLAN_RENDERING_META_KEY``.
PLAN_RENDERING_CLIENTS = frozenset({"zed", "toad"})


# ---------------------------------------------------------------------------
# Inspect-specific tool knowledge
# ---------------------------------------------------------------------------

# Tool names whose invocations translate to ACP's ``AgentPlanUpdate``
# for plan-capable clients. Hard-coded by tool name (matches Inspect's
# first-party planning tools — see ``tool/_tools/_update_plan.py`` and
# ``tool/_tools/_todo_write.py``).
PLAN_TOOL_NAMES = frozenset({"update_plan", "todo_write"})


# ---------------------------------------------------------------------------
# inspect/* method parameter models + route registration
# ---------------------------------------------------------------------------


class CancelSampleParams(BaseModel):
    """Pydantic param model for :data:`INSPECT_CANCEL_SAMPLE_METHOD`."""

    session_id: str = Field(alias="sessionId")
    action: Literal["score", "error"]

    model_config = {"populate_by_name": True}


class CancelToolCallParams(BaseModel):
    """Pydantic param model for :data:`INSPECT_CANCEL_TOOL_CALL_METHOD`."""

    session_id: str = Field(alias="sessionId")
    tool_call_id: str = Field(alias="toolCallId")

    model_config = {"populate_by_name": True}


class NewSessionParams(BaseModel):
    """Pydantic param model for :data:`INSPECT_NEW_SESSION_METHOD`.

    Inspect-aware clients (the TUI, editors that already know which
    sample to attach to) pass the ``task/sample_id/epoch`` triple
    directly to skip the picker. The standard ACP ``session/new``
    Pydantic schema (``NewSessionRequest``) doesn't allow extra
    top-level fields, so this lives as a separate inspect-namespace
    method with its own model.
    """

    cwd: str
    mcp_servers: Any = Field(default=None, alias="mcpServers")
    target: str
    """``task/sample_id/epoch`` direct-bind spec — slash-delimited."""

    model_config = {"populate_by_name": True}


class ListSessionsParams(BaseModel):
    """Pydantic param model for :data:`INSPECT_LIST_SESSIONS_METHOD` (no params)."""


def wrap_action_handler(func: Any, model: type[BaseModel]) -> Any:
    """Build a router wrapper that validates params + unpacks kwargs.

    Mirrors :meth:`acp.router.MessageRouter._make_func` but for our
    inline Pydantic models (the ACP ``schema`` module doesn't carry
    them since ``inspect/*`` is a non-standard extension). The router
    invokes the returned callable with the raw params dict; the
    wrapper validates, extracts kwargs honoring camelCase aliases, and
    forwards to the bound handler.
    """

    async def wrapper(params: Any) -> Any:
        # JSON-RPC allows the params member to be omitted entirely.
        # When omitted, the dispatcher hands us ``None`` — but
        # ``model.model_validate(None)`` fails for empty / all-optional
        # models like :class:`ListSessionsParams`. Coerce to an empty
        # dict so handlers that take no required params accept the
        # omitted form transparently. Handlers with required fields
        # still surface a clean validation error on the missing keys.
        if params is None:
            params = {}
        try:
            request = model.model_validate(params)
        except ValidationError as exc:
            # Translate Pydantic validation failures into a standard
            # JSON-RPC ``invalid_params`` error so clients get a clean,
            # protocol-conformant response rather than relying on the
            # ACP framework's outer catch to do it for us. Carries the
            # structured errors so capability-aware clients can render
            # field-level diagnostics.
            raise RequestError.invalid_params(
                {
                    "reason": "params failed validation",
                    "errors": exc.errors(),
                }
            )
        kwargs = {
            field_name: getattr(request, field_name)
            for field_name in model.model_fields
        }
        return await func(**kwargs)

    return wrapper


def register_inspect_routes(router: MessageRouter, handler: ConnectionHandler) -> None:
    """Add the ``inspect/*`` action routes to a per-connection router.

    Each ACP server connection wraps the standard Agent-protocol
    routes in a :class:`MessageRouter`; this function tacks on the
    four Inspect-namespace methods (sample-level cancel, tool-call
    cancel, direct session bind, session enumeration). Called from
    :func:`AcpServer._on_connection` once per accepted connection.

    The methods are always advertised — no capability opt-in. Clients
    that don't know about them simply don't call them.
    """
    from acp.router import Route

    router.add_route(
        Route(
            method=INSPECT_CANCEL_SAMPLE_METHOD,
            func=wrap_action_handler(handler.cancel_sample, CancelSampleParams),
            kind="request",
        )
    )
    router.add_route(
        Route(
            method=INSPECT_CANCEL_TOOL_CALL_METHOD,
            func=wrap_action_handler(handler.cancel_tool_call, CancelToolCallParams),
            kind="request",
        )
    )
    router.add_route(
        Route(
            method=INSPECT_NEW_SESSION_METHOD,
            func=wrap_action_handler(handler.inspect_new_session, NewSessionParams),
            kind="request",
        )
    )
    router.add_route(
        Route(
            method=INSPECT_LIST_SESSIONS_METHOD,
            func=wrap_action_handler(handler.inspect_list_sessions, ListSessionsParams),
            kind="request",
        )
    )


# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------


def detect_capabilities(
    client_info: Any,
    client_capabilities: Any,
) -> tuple[bool, bool]:
    """Decide whether this client opts into Inspect extensions.

    Returns ``(client_renders_plan, raw_events_enabled)``. Two sources
    are consulted for each flag:

    - ``client_info.name`` (case-insensitive) against the
      :data:`PLAN_RENDERING_CLIENTS` allowlist — known editors with
      first-class Plan UI.
    - ``client_capabilities._meta`` for the explicit opt-in keys
      :data:`PLAN_RENDERING_META_KEY` / :data:`RAW_EVENTS_META_KEY`.

    Either source flips the flag on; both default off. Called by
    :meth:`ConnectionHandler.initialize` and the result is frozen on
    :class:`ConnectionState` for the connection lifetime.
    """
    name = client_info.name.lower() if client_info is not None else ""
    meta: dict[str, Any] = {}
    if client_capabilities is not None and client_capabilities.field_meta:
        meta = client_capabilities.field_meta
    client_renders_plan = name in PLAN_RENDERING_CLIENTS or bool(
        meta.get(PLAN_RENDERING_META_KEY)
    )
    raw_events_enabled = bool(meta.get(RAW_EVENTS_META_KEY))
    return client_renders_plan, raw_events_enabled


# ---------------------------------------------------------------------------
# _meta annotators (consumed by event_mapping.py)
# ---------------------------------------------------------------------------
#
# Each annotator returns the dict that goes into ``field_meta=`` on a
# single outbound notification. The event-mapping module supplies the
# rest of the notification body (content, message_id, etc.). Keeping
# only the dict shape here means all Inspect-specific keys remain in
# one auditable place.


def input_message_chunk_meta(
    msg: ChatMessageUser | ChatMessageSystem,
) -> dict[str, Any]:
    """``_meta`` for a ``user_message_chunk`` mapped from a user or system message.

    Always carries :data:`MESSAGE_ID_META_KEY`. System messages add
    :data:`MESSAGE_ROLE_META_KEY` = ``"system"`` so the client can
    label them distinctly without inventing a new ACP role. User
    messages add :data:`USER_SOURCE_META_KEY` (which may be ``None``
    — carried explicitly so the client can tell "explicitly no
    source" from "key forgotten").
    """
    # Imported lazily to keep the inspect_ext module dependency-free at
    # type-check time.
    from inspect_ai.model._chat_message import ChatMessageSystem

    meta: dict[str, Any] = {MESSAGE_ID_META_KEY: msg.id}
    if isinstance(msg, ChatMessageSystem):
        meta[MESSAGE_ROLE_META_KEY] = "system"
    else:
        meta[USER_SOURCE_META_KEY] = msg.source
    return meta


def assistant_content_chunk_meta(event: ModelEvent, uuid: str | None) -> dict[str, Any]:
    """``_meta`` for an ``agent_message_chunk`` / ``agent_thought_chunk``.

    Carries :data:`MODEL_META_KEY` for every chunk (per-chunk, not
    session-static, so it's correct for multi-model evals where the
    model switches mid-conversation), plus :data:`MODEL_EVENT_UUID_META_KEY`
    when the originating ``ModelEvent`` has a uuid (so clients can
    cross-reference back to the transcript event — the ACP message_id
    is a UUIDv5 hash, one-way).
    """
    meta: dict[str, Any] = {MODEL_META_KEY: event.model}
    if uuid is not None:
        meta[MODEL_EVENT_UUID_META_KEY] = uuid
    return meta


def assistant_pending_chunk_meta(event: ModelEvent, uuid: str) -> dict[str, Any]:
    """``_meta`` for the empty ``agent_message_chunk`` that signals "generation started".

    Adds :data:`MODEL_EVENT_PENDING_META_KEY` = ``True`` so the
    client can distinguish this from any other empty content chunk
    (e.g. the completion marker emitted on the complete phase when no
    content arrives).
    """
    return {
        MODEL_META_KEY: event.model,
        MODEL_EVENT_UUID_META_KEY: uuid,
        MODEL_EVENT_PENDING_META_KEY: True,
    }


def assistant_complete_chunk_meta(event: ModelEvent, uuid: str) -> dict[str, Any]:
    """``_meta`` for the empty ``agent_message_chunk`` that closes out a generation.

    Sent on the no-content / tool-only / empty-reasoning exit paths
    when a pending marker went out earlier — without it, the client's
    spinner stays stuck. Carries
    :data:`MODEL_EVENT_COMPLETE_META_KEY` = ``True`` to distinguish
    from the pending marker.
    """
    return {
        MODEL_META_KEY: event.model,
        MODEL_EVENT_UUID_META_KEY: uuid,
        MODEL_EVENT_COMPLETE_META_KEY: True,
    }


# ---------------------------------------------------------------------------
# Raw event forwarder (opt-in via RAW_EVENTS_META_KEY)
# ---------------------------------------------------------------------------


class RawEventForwarder:
    """Per-bind raw transcript event firehose.

    Opt-in via :data:`RAW_EVENTS_META_KEY`. Subscribes to the bound
    target's transcript and forwards each event as an
    :data:`INSPECT_EVENT_METHOD` JSON-RPC notification, alongside
    (not instead of) the standard ``session/update`` stream.

    Lifecycle expected by :class:`Forwarders`:

    - :meth:`attach` — sync, before the snapshot/attach race so events
      land in the live buffer rather than being missed.
    - :meth:`replay` — emit snapshot history before live forwarding
      starts so the client sees the full firehose for catch-up.
    - :meth:`start` — launch the background drain task.
    - :meth:`stop` — unsubscribe, close streams, cancel task.
      Idempotent.

    Events are serialized in the synchronous transcript subscriber
    callback (not deferred to the async task) because the subscriber
    runs BEFORE ``Transcript._process_event``'s attachment-extraction
    step. If we enqueued just the event reference, by the time the
    forwarder task picked it up the inline ``call`` payload would
    already be gone. ``model_dump`` in the callback captures the
    pre-condensation state.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._send: Any = None
        self._recv: Any = None
        self._task: asyncio.Task[None] | None = None
        self._unsubscribe: Callable[[], None] | None = None

    def attach(self, target: AcpSession) -> None:
        """Create the bridge stream + subscribe to the target's transcript."""
        self._send, self._recv = anyio.create_memory_object_stream[Any](
            max_buffer_size=math.inf
        )
        self._unsubscribe = target.subscribe_transcript_events(self._on_event)

    async def replay(self, snapshot: list[Any], max_events: int) -> None:
        """Emit the last ``max_events`` from the snapshot as ``inspect/event``.

        Caller (``Forwarders._run_replay``) runs under
        ``ConnectionHandler._bind_lock``, so no concurrent bind can
        invalidate the wire while this loop iterates.

        Per-event error boundary:
        - Serialization failures log a warning and skip the event
          (next event might be fine).
        - Send failures (disconnect or otherwise) **propagate**. The
          caller wraps this entire method in an :func:`acp_send_guard`
          so it sees the failure and can decide to skip semantic
          replay entirely. Catching here and returning normally would
          hide the disconnect, and the underlying ``acp`` library's
          sender task may have already died — a subsequent semantic
          send would enqueue a future with no sender to complete it.

        ``CancelledError`` propagates naturally because it inherits
        from ``BaseException`` (not ``Exception``).
        """
        events = snapshot[-max_events:]
        for event in events:
            payload: Any = None
            with acp_guard("ACP raw replay: event failed to serialize; skipping") as g:
                payload = event.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                )
            if g.failed:
                continue
            # Send failures escape to the caller's outer ``acp_send_guard``.
            await self._connection.send_notification(INSPECT_EVENT_METHOD, payload)

    def start(self, target_session_id: str) -> None:
        """Launch the background drain task. Call after :meth:`replay`."""
        self._task = asyncio.create_task(
            self._run(self._recv),
            name=f"acp-fwd-raw-{target_session_id}",
        )

    async def stop(self) -> None:
        """Unsubscribe, close streams, cancel task. Idempotent."""
        # Unsubscribe first so no more events land while we're tearing down.
        if self._unsubscribe is not None:
            try:
                self._unsubscribe()
            except Exception:
                logger.exception("Error unsubscribing ACP raw forwarder")
            self._unsubscribe = None
        if self._send is not None:
            try:
                self._send.close()
            except Exception:
                pass
            self._send = None
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (anyio.get_cancelled_exc_class(), Exception):
                pass
        self._task = None
        if self._recv is not None:
            try:
                self._recv.close()
            except Exception:
                pass
            self._recv = None

    def _on_event(self, event: Any) -> None:
        """Sync transcript-subscriber callback. Snapshots + enqueues for the drain task.

        See class docstring for why serialization happens here rather
        than in the task body. Non-blocking via ``send_nowait``; a dead
        send half is dropped silently (the cleanup runs first on
        disconnect, so a closed stream here is an expected race).
        """
        if self._send is None:
            return
        try:
            payload = event.model_dump(mode="json", by_alias=True, exclude_none=True)
        except Exception:
            logger.exception(
                "ACP raw event subscriber: event failed to serialize; skipping"
            )
            return
        try:
            self._send.send_nowait(payload)
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            pass

    async def _run(self, recv_stream: Any) -> None:
        """Drain the bridge stream and forward payloads as JSON-RPC notifications.

        Per-payload error boundary:
        - Normal-disconnect on send → DEBUG + exit. Every subsequent
          send would fail the same way; staying in the loop just to
          warn-and-continue would spam the log on every dropped peer.
        - Unexpected send failure → WARNING + exit (connection is
          probably toast).
        - Outer stream-iteration failure → guarded the same way
          (normal close → DEBUG; unexpected → WARNING).

        ``CancelledError`` propagates naturally (BaseException, not
        Exception) so ``stop()`` can tear the task down cleanly.
        """
        with acp_send_guard("ACP raw forwarder: stream iteration failed") as outer:
            async for payload in recv_stream:
                with acp_send_guard("ACP raw forwarder: send failed") as inner:
                    await self._connection.send_notification(
                        INSPECT_EVENT_METHOD, payload
                    )
                if inner.should_exit:
                    return
        if outer.should_exit:
            return


# ---------------------------------------------------------------------------
# Picker shape (consumed by picker.py + connection.py)
# ---------------------------------------------------------------------------


def picker_target_meta_dict(target: PickerTarget) -> dict[str, Any]:
    """Canonical camelCase ``_meta`` shape for a picker target.

    Single source of truth — used by the picker notification, the
    ``inspect/list_sessions`` response, and the binding confirmation.
    Add new fields here and they appear in every payload automatically.
    """
    return {
        "sessionId": target.session_id,
        "task": target.task,
        "sampleId": target.sample_id,
        "epoch": target.epoch,
        "agentName": target.agent_name,
        "startedAt": target.started_at,
        "totalTokens": target.total_tokens,
    }


# ---------------------------------------------------------------------------
# Plan-policy transformation (consumed by Forwarders)
# ---------------------------------------------------------------------------


class PlanPolicyTransformer:
    """Per-bind plan-tool → ``AgentPlanUpdate`` rewriter.

    For plan-capable clients (Zed, Toad, or anything that opted in via
    :data:`PLAN_RENDERING_META_KEY`), substitutes ACP's
    ``AgentPlanUpdate`` for the standard tool-call notifications of
    Inspect's first-party planning tools (:data:`PLAN_TOOL_NAMES`).

    Owns a per-tool stash so the in-progress → completed transition can
    look up the original ``raw_input`` (which the completion
    notification doesn't carry on its own). The stash dies with the
    instance — :class:`Forwarders` constructs a fresh transformer per
    bind, so a cancelled mid-flight plan tool on a previous bind can
    never leak its stash into the next.
    """

    def __init__(self, state: ConnectionState) -> None:
        self._state = state
        self._stash: dict[str, dict[str, Any]] = {}

    def transform(self, notif: SessionNotification) -> SessionNotification | None:
        """Apply the per-connection plan-policy transformation.

        - ToolCallStart for a plan tool with ``status="in_progress"``:
          stash raw_input + title; suppress (return ``None``).
        - ToolCallStart for a plan tool with terminal status
          (instant-complete case): build and return the
          ``AgentPlanUpdate`` directly.
        - ToolCallProgress for a previously-stashed plan tool: build
          and return the ``AgentPlanUpdate`` using the stashed input,
          then clear the stash.
        - Any other notification (including all notifications when the
          client is not plan-capable): passthrough.
        """
        # Imported lazily to avoid a heavy acp.schema dependency at
        # inspect_ext import time.
        from acp.schema import ToolCallProgress, ToolCallStart

        if not self._state.client_renders_plan:
            return notif

        update = notif.update
        if isinstance(update, ToolCallStart):
            title = update.title or ""
            if title not in PLAN_TOOL_NAMES:
                return notif
            self._stash[update.tool_call_id] = {
                "title": title,
                "raw_input": update.raw_input,
            }
            if update.status == "in_progress":
                return None
            stash = self._stash.pop(update.tool_call_id, None)
            if stash is None:
                return notif
            plan = self._build_plan_update(stash["title"], stash["raw_input"])
            return plan if plan is not None else notif

        if isinstance(update, ToolCallProgress):
            stash = self._stash.pop(update.tool_call_id, None)
            if stash is None:
                return notif
            plan = self._build_plan_update(stash["title"], stash["raw_input"])
            return plan if plan is not None else notif

        return notif

    def _build_plan_update(
        self, title: str, raw_input: Any
    ) -> SessionNotification | None:
        """Translate a plan-tool's raw_input into an ``AgentPlanUpdate`` notification.

        Returns ``None`` if the raw_input shape doesn't match what the
        named tool expects (caller falls back to passthrough). Defaults
        ``priority="medium"`` since neither ``update_plan`` nor
        ``todo_write`` carry priority.
        """
        from acp.helpers import plan_entry, session_notification, update_plan

        if not isinstance(raw_input, dict) or self._state.wire_session_id is None:
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
        return session_notification(self._state.wire_session_id, update_plan(entries))


def build_picker_notification(
    session_id: str,
    targets: list[PickerTarget],
) -> SessionNotification:
    """Build the picker ``session/update`` notification payload.

    ``session_id`` is the value to address the notification at — the
    caller chooses whether to use a synthetic control session uuid
    (the typical picker case) or a target's id (the auto-bind /
    confirmation case).

    The body is an ``agent_message_chunk`` with a numbered list any
    ACP-aware client can render as text. ``_meta`` carries the same
    list as a structured array under :data:`PICKER_META_KEY` so a
    capability-aware client (e.g. ``inspect acp``) can match by
    ``(task, sample_id, epoch)`` without re-parsing the text.

    Both the text format and the ``_meta`` shape are Inspect-specific
    extensions on a standard ACP notification.
    """
    from acp.helpers import session_notification, text_block, update_agent_message

    if not targets:
        text = (
            "No sessions are currently available. Wait for an eval to start "
            "and try again."
        )
    else:
        lines = ["Available sessions — reply with a number or sessionId:"]
        for i, target in enumerate(targets, start=1):
            lines.append(
                f"  {i}. {target.task} / sample {target.sample_id} / "
                f"epoch {target.epoch}    [{target.session_id}]"
            )
        text = "\n".join(lines)

    meta: dict[str, Any] = {
        PICKER_META_KEY: [picker_target_meta_dict(t) for t in targets],
    }

    notification = session_notification(
        session_id=session_id,
        update=update_agent_message(text_block(text)),
    )
    notification.field_meta = meta
    return notification
