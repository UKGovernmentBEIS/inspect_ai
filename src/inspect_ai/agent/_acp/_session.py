"""Agent Client Protocol session foundation.

The ``AcpSession`` is the per-agent ACP facade. There are two
implementations:

- ``_NoOpAcpSession`` — null object used as the default ContextVar value
  and as the shadow when ``acp_session()`` is opened inside an already
  active session (sub-agent case).
- ``_LiveAcpSession`` — the active implementation that owns the
  in-process pub/sub bus, the user-message queue, and the turn cancel
  scope.

Phase 1 landed types, factory, and pub/sub. Phase 2 landed the transcript
primitives (``InterruptEvent`` and ``source="operator"``). Phase 3 adds
the cancel/inject machinery: ``turn_scope``, ``before_turn``,
``after_cancel``, plus producer-side ``submit_user_message`` and
``cancel_current_turn``.
"""

import contextlib
from contextvars import ContextVar
from logging import getLogger
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Iterator,
    Literal,
    Protocol,
    runtime_checkable,
)

import anyio
from anyio.streams.memory import (
    MemoryObjectReceiveStream,
    MemoryObjectSendStream,
)
from shortuuid import uuid

from inspect_ai.log._transcript import record_interrupt_event, transcript
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.tool._tool_call import ToolCallError

if TYPE_CHECKING:
    from inspect_ai.agent._acp._router import _AcpEventRouter
    from inspect_ai.agent._agent import AgentState
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.event._tool import ToolEvent

logger = getLogger(__name__)

# Loose heterogeneous payload — Phase 1's tests publish dicts, Phase 6's
# router publishes ``acp.SessionNotification`` Pydantic instances. The
# bus does not narrow; subscribers narrow with ``isinstance`` as needed.
AcpUpdate = Any

# Bounded subscriber buffer. A slow subscriber drops updates rather than
# stalling the agent; replay-on-attach (Phase 10) handles lossless catch-up
# for clients that need it.
_SUBSCRIBER_BUFFER_SIZE = 256

# Sentinel session_id for the no-op variant so callers never need
# isinstance guards.
_NOOP_SESSION_ID = "noop"


class TurnCancelled(Exception):
    """Raised inside :meth:`AcpSession.turn_scope` when a client cancels.

    Distinct from ``CancelledError``, which is reserved for
    sample-level hard cancels propagating from the enclosing task
    group (limit exceeded, eval shutdown). The agent loop catches
    ``TurnCancelled`` to recover and continue with a fresh user
    message; ``CancelledError`` continues to unwind the sample.
    """


@runtime_checkable
class AcpSession(Protocol):
    """Per-agent ACP session facade.

    Provides the in-process pub/sub bus (Phase 1), plus the
    cancel/inject machinery (Phase 3): turn scopes, user-message queue,
    and producer-side cancel/submit methods.
    """

    @property
    def session_id(self) -> str:
        """Opaque identifier for this session.

        Stable for the lifetime of a live session; returns the sentinel
        ``"noop"`` for the no-op variant so callers never need
        ``isinstance`` guards before logging or correlating.
        """
        ...

    async def __aenter__(self) -> "AcpSession":
        """Enter the session scope.

        Returns ``self``. The session is installed in the ACP
        ContextVar by the ``acp_session()`` factory immediately before
        this is called; consumers can call :func:`current_acp_session`
        from anywhere inside the scope to retrieve it.
        """
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the session scope.

        Closes every attached subscriber's send half so receivers see
        clean EOF. No drain — closing *is* the termination signal.
        """
        ...

    def attach(self) -> MemoryObjectReceiveStream[AcpUpdate]:
        """Register a subscriber and return its receive stream.

        Caller iterates with ``async for update in stream``. The session
        closes all subscriber streams on exit, so an idle ``async for``
        terminates cleanly.
        """
        ...

    def detach(self, stream: MemoryObjectReceiveStream[AcpUpdate]) -> None:
        """Unregister a subscriber previously returned by :meth:`attach`.

        Closes the matching send half and drops the subscriber from the
        fan-out list. Safe to call with an already-detached or unknown
        stream — silently does nothing.
        """
        ...

    def publish(self, update: AcpUpdate) -> None:
        """Fan ``update`` out to every attached subscriber.

        Non-blocking: a subscriber with a full buffer drops the update
        with a logged warning rather than stalling the producer.
        """
        ...

    def turn_scope(self) -> contextlib.AbstractContextManager[None]:
        """Wrap one agent turn so an ACP client cancel can interrupt it.

        Synchronous context manager. ACP ``session/cancel`` causes the
        wrapped block to raise :class:`TurnCancelled`. Sample-level
        cancels (limit, eval shutdown) continue to propagate as
        ``CancelledError`` past this scope unchanged.
        """
        ...

    async def before_turn(self, state: "AgentState") -> list[ChatMessageUser]:
        """Drain queued operator messages and return them.

        On the very first call to this method, if ``state.messages``
        contains no user message yet, blocks until at least one is
        submitted. On subsequent calls, drains non-blockingly and
        returns immediately (possibly with an empty list).
        """
        ...

    async def after_cancel(
        self, messages: list[ChatMessage] | None = None
    ) -> list[ChatMessage]:
        """Return repair + follow-up messages after a turn cancel.

        Returns synthetic :class:`ChatMessageTool` results for any tool
        calls that were in flight at cancel time, followed by drained
        operator user messages. Blocks until at least one user message
        is available if the queue is empty. Returned list is ready to
        extend onto ``state.messages``.

        When ``messages`` is provided, scans the last assistant
        message's ``tool_calls`` and synthesizes a repair for every id
        that doesn't yet have a matching :class:`ChatMessageTool`
        result. This catches partially-completed tool batches that
        anyio cancellation interrupts before ``_execute_tools_impl``
        can return.
        """
        ...

    def submit_user_message(self, msg: ChatMessageUser) -> None:
        """Queue a user message for the next turn or after-cancel drain.

        Called by transports (Phase 7+: TUI, sockets) when an ACP
        client sends ``session/prompt``.
        """
        ...

    def cancel_current_turn(self) -> None:
        """Cancel the current turn and record an :class:`InterruptEvent`.

        Snapshots :data:`_active_model_event` and the current
        in-flight tool calls (via :meth:`track_tool_call`) to populate
        the event's ``interrupted`` / id fields. Fire-and-forget — never
        raises on the caller's side.
        """
        ...

    def track_tool_call(
        self, tool_call_id: str, event: "ToolEvent | None" = None
    ) -> contextlib.AbstractContextManager[None]:
        """Mark a tool call as in flight for the lifetime of the scope.

        Wraps each top-level tool execution so :meth:`cancel_current_turn`
        knows which tool call ids to record in :class:`InterruptEvent`
        and which to repair with synthetic results in :meth:`after_cancel`.
        When ``event`` is provided, :meth:`cancel_current_turn` also
        clears its ``pending`` flag on cancellation (otherwise the
        transcript shows cancelled tool rows as still in-flight).
        Nested-agent tool calls go to the no-op session and are not
        tracked here.
        """
        ...

    def track_model_event(
        self, event: "ModelEvent"
    ) -> contextlib.AbstractContextManager[None]:
        """Mark a model call as in flight for the lifetime of the scope.

        Stored on the session (not a ContextVar) so a cancel coming
        from a sibling transport task can read it. The agent / generate
        path wraps each ``ModelEvent`` in this so
        :meth:`cancel_current_turn` can populate
        :attr:`InterruptEvent.interrupted_model_event_id`. Sibling to
        :func:`inspect_ai.log._samples.track_active_model_event` (which
        sets the ContextVar consumed by transcript/log writers); both
        coexist.
        """
        ...


class _NoOpAcpSession:
    """No-op session installed when ACP is not active or shadowed.

    ``attach()`` returns an already-closed receive stream so callers can
    still write transport code uniformly — the ``async for`` just exits
    immediately.
    """

    @property
    def session_id(self) -> str:
        """Always returns the ``"noop"`` sentinel."""
        return _NOOP_SESSION_ID

    async def __aenter__(self) -> "AcpSession":
        """No-op enter; returns ``self``."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """No-op exit."""
        return None

    def attach(self) -> MemoryObjectReceiveStream[AcpUpdate]:
        """Return an already-closed receive stream.

        Lets callers wire transport code identically against either
        variant — iterating the stream yields no updates and exits
        immediately.
        """
        send, receive = anyio.create_memory_object_stream[AcpUpdate](0)
        send.close()
        return receive

    def detach(self, stream: MemoryObjectReceiveStream[AcpUpdate]) -> None:
        """No-op detach."""
        return None

    def publish(self, update: AcpUpdate) -> None:
        """No-op publish — updates are discarded."""
        return None

    @contextlib.contextmanager
    def turn_scope(self) -> Iterator[None]:
        """No-op turn scope — yields once and exits without cancellation handling."""
        yield

    async def before_turn(self, state: "AgentState") -> list[ChatMessageUser]:
        """No-op — never blocks, returns an empty list."""
        return []

    async def after_cancel(
        self, messages: list[ChatMessage] | None = None
    ) -> list[ChatMessage]:
        """No-op — never reachable on the no-op session (no cancel can fire)."""
        return []

    def submit_user_message(self, msg: ChatMessageUser) -> None:
        """No-op submit — message is discarded."""
        return None

    def cancel_current_turn(self) -> None:
        """No-op cancel.

        Does not call ``record_interrupt_event`` — sub-agents must not
        emit cancel events into the top-level transcript.
        """
        return None

    @contextlib.contextmanager
    def track_tool_call(
        self, tool_call_id: str, event: "ToolEvent | None" = None
    ) -> Iterator[None]:
        """No-op tool-call tracker — yields once."""
        yield

    @contextlib.contextmanager
    def track_model_event(self, event: "ModelEvent") -> Iterator[None]:
        """No-op model-event tracker — yields once."""
        yield


class _LiveAcpSession:
    """Active ACP session: owns the in-process pub/sub bus.

    Installed by :func:`acp_session` as the outermost ACP scope in a
    sample. Subscribers (the in-process TUI in Phase 7, the socket
    transport in Phase 8+) call :meth:`attach` to receive
    ``session/update``-shaped payloads.
    """

    def __init__(self) -> None:
        self._session_id: str = uuid()
        self._subscribers: list[
            tuple[
                MemoryObjectSendStream[AcpUpdate],
                MemoryObjectReceiveStream[AcpUpdate],
            ]
        ] = []
        # User-message queue: simple list + event for "wait for next message".
        self._user_messages: list[ChatMessageUser] = []
        self._user_message_event = anyio.Event()
        self._first_before_turn_called = False
        # Turn cancel scope: set inside turn_scope, used by cancel_current_turn.
        self._turn_cancel_scope: anyio.CancelScope | None = None
        # Flag discriminates a client-driven cancel (we cancelled the scope)
        # from a sample-level cancel propagating from outside.
        self._pending_turn_cancel = False
        # Top-level tool calls currently executing — push/pop by track_tool_call.
        self._in_flight_tool_calls: list[str] = []
        # Tool events keyed by call id so cancel_current_turn can clear
        # `pending=True` on cancellation (otherwise the transcript shows
        # cancelled tool rows as still in-flight forever).
        self._in_flight_tool_events: dict[str, "ToolEvent"] = {}
        # Snapshot taken at cancel_current_turn time so after_cancel knows
        # what synthetic ChatMessageTool repair messages to produce (used as
        # a fallback when caller doesn't pass state.messages).
        self._cancelled_tool_call_ids: list[str] = []
        # In-flight model call — set by track_model_event. Stored on the
        # session (not a ContextVar) so a transport task firing a cancel
        # from a sibling task can read it.
        self._active_model_event: "ModelEvent | None" = None
        # When True, the router (Phase 6) drops events emitted inside
        # sub-agents (depth>0). Standard ACP semantic for editor clients.
        # Disabled by consumers (debugging tooling, raw-stream TUIs) that
        # want full sub-agent visibility through the pub/sub bus.
        self._filter_subagent_events: bool = True
        # Router attached at __aenter__; detached at __aexit__. Owns the
        # transcript subscription that maps events to SessionNotifications.
        self._router: "_AcpEventRouter | None" = None

    @property
    def session_id(self) -> str:
        """Opaque, stable identifier minted at construction (shortuuid)."""
        return self._session_id

    async def __aenter__(self) -> "AcpSession":
        """Enter the session scope; attach the event router and return ``self``.

        Also registers ``self`` on the current :class:`ActiveSample`
        (if any) so out-of-task consumers like the Phase 7 Inspect TUI
        can locate the live session by sample reference.
        """
        from inspect_ai.agent._acp._router import _AcpEventRouter
        from inspect_ai.log._samples import sample_active

        self._router = _AcpEventRouter(self)
        self._router.attach()
        active = sample_active()
        if active is not None:
            active.acp_session = self
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Detach the router, deregister from ActiveSample, close subscribers.

        Receivers see clean EOF (``anyio.EndOfStream``) and their
        ``async for`` loops terminate.
        """
        from inspect_ai.log._samples import sample_active

        if self._router is not None:
            self._router.detach()
            self._router = None
        active = sample_active()
        # `is self` identity guard: don't clear someone else's registration
        # if a stale __aexit__ ever races with a sibling live session.
        if active is not None and active.acp_session is self:
            active.acp_session = None
        for send, _ in self._subscribers:
            send.close()
        self._subscribers.clear()

    def disable_subagent_filtering(self) -> None:
        """Allow sub-agent transcript events through to the pub/sub bus.

        By default the Phase 6 router drops any transcript event emitted
        while a sub-agent boundary is open — the standard ACP semantic
        where the editor sees only the outer agent's conversation. Some
        consumers (debugging tooling, raw-event TUIs) want every event
        instead; calling this method disables the filter for the rest of
        the session.
        """
        self._filter_subagent_events = False

    def attach(self) -> MemoryObjectReceiveStream[AcpUpdate]:
        """Create a new subscriber stream pair, keep the send half, return the receive half.

        Each subscriber gets its own bounded buffer; slow consumers
        don't stall siblings.
        """
        send, receive = anyio.create_memory_object_stream[AcpUpdate](
            max_buffer_size=_SUBSCRIBER_BUFFER_SIZE
        )
        self._subscribers.append((send, receive))
        return receive

    def detach(self, stream: MemoryObjectReceiveStream[AcpUpdate]) -> None:
        """Close the matching send half and drop the subscriber.

        Identity match (``receive is stream``). Safe to call with an
        unknown or already-detached stream — silently does nothing.
        """
        for i, (send, receive) in enumerate(self._subscribers):
            if receive is stream:
                send.close()
                del self._subscribers[i]
                return

    def publish(self, update: AcpUpdate) -> None:
        """Fan ``update`` out non-blockingly to all attached subscribers.

        A subscriber with a full buffer logs a warning and drops the
        update. A subscriber whose receive half was closed by the
        consumer is pruned from the subscriber list so subsequent
        publishes don't keep hitting the same dead stream.
        """
        dead: list[int] = []
        for i, (send, _) in enumerate(self._subscribers):
            try:
                send.send_nowait(update)
            except anyio.WouldBlock:
                logger.warning(
                    f"AcpSession {self._session_id}: subscriber buffer full; "
                    "dropping update"
                )
            except anyio.BrokenResourceError:
                # Receive end closed by the consumer; prune.
                dead.append(i)
        for i in reversed(dead):
            send, _ = self._subscribers.pop(i)
            send.close()

    @contextlib.contextmanager
    def turn_scope(self) -> Iterator[None]:
        """Wrap one agent turn so a client cancel can interrupt it.

        Opens a fresh anyio ``CancelScope``. If
        :meth:`cancel_current_turn` is called while this scope is
        active, the wrapped block raises :class:`TurnCancelled`. A
        sample-level cancel (outer task group) propagates through
        unchanged — the inner scope only catches what was targeted
        at it.
        """
        self._pending_turn_cancel = False
        self._cancelled_tool_call_ids.clear()
        with anyio.CancelScope() as scope:
            self._turn_cancel_scope = scope
            try:
                yield
            finally:
                self._turn_cancel_scope = None
        if scope.cancelled_caught and self._pending_turn_cancel:
            self._pending_turn_cancel = False
            raise TurnCancelled()

    async def before_turn(self, state: "AgentState") -> list[ChatMessageUser]:
        """Drain queued operator messages and return them.

        On the first call, if ``state.messages`` has no user content
        yet, blocks for at least one queued message — covers the
        "no dataset prompt, operator types the first message" case.
        Subsequent calls drain immediately.
        """
        if not self._first_before_turn_called:
            self._first_before_turn_called = True
            if not any(isinstance(m, ChatMessageUser) for m in state.messages):
                while not self._user_messages:
                    evt = self._user_message_event
                    await evt.wait()
        drained = list(self._user_messages)
        self._user_messages.clear()
        self._user_message_event = anyio.Event()
        return drained

    async def after_cancel(
        self, messages: list[ChatMessage] | None = None
    ) -> list[ChatMessage]:
        """Return synthetic tool repair messages + drained user messages.

        The agent loop catches :class:`TurnCancelled` and extends
        ``state.messages`` with the result of this call. Synthetic
        :class:`ChatMessageTool` results come first (one per cancelled
        tool call) so the assistant's pending tool calls have matching
        responses; the new operator user message(s) come next. Blocks
        if the user-message queue is empty.

        When ``messages`` is provided (the normal Phase 4+ case), this
        scans the last assistant message's ``tool_calls`` and synthesizes
        a repair for every id that doesn't yet have a matching
        :class:`ChatMessageTool` result. That covers three cases under
        sequential tool execution: tools that were in flight at cancel,
        tools that never started because an earlier call was cancelled,
        and tools whose completed results were lost when
        ``_execute_tools_impl`` was interrupted before returning. When
        ``messages`` is ``None`` (Phase 3 unit tests), falls back to
        ``_cancelled_tool_call_ids`` (snapshotted in
        :meth:`cancel_current_turn`).
        """
        results: list[ChatMessage] = []
        if messages is not None:
            repair_ids = _unanswered_tool_call_ids(messages)
        else:
            repair_ids = list(self._cancelled_tool_call_ids)
        for tool_call_id in repair_ids:
            results.append(
                ChatMessageTool(
                    tool_call_id=tool_call_id,
                    content="Tool call cancelled by user.",
                    error=ToolCallError(
                        type="cancelled",
                        message="Tool call cancelled by user.",
                    ),
                )
            )
        self._cancelled_tool_call_ids.clear()
        if not self._user_messages:
            while not self._user_messages:
                evt = self._user_message_event
                await evt.wait()
        drained = list(self._user_messages)
        self._user_messages.clear()
        self._user_message_event = anyio.Event()
        results.extend(drained)
        return results

    def submit_user_message(self, msg: ChatMessageUser) -> None:
        """Queue ``msg`` and wake any awaiter blocked on it.

        Normalizes provenance: any message queued through this API is
        treated as operator-injected, so ``source`` is set to
        ``"operator"`` if it isn't already. Callers don't have to
        remember to set it themselves.
        """
        if msg.source != "operator":
            msg = msg.model_copy(update={"source": "operator"})
        self._user_messages.append(msg)
        self._user_message_event.set()

    def cancel_current_turn(self) -> None:
        """Cancel the current turn and record an :class:`InterruptEvent`.

        Fire-and-forget. Snapshots the in-flight tool call (if any) or
        the active :class:`ModelEvent` (if any) to populate the event's
        cross-reference fields. Also clears ``pending=True`` on the
        in-flight model and tool events so the transcript / log viewer
        doesn't show them as still in-flight after the cancel (anyio
        cancellation bypasses the normal completion paths that would
        otherwise have cleared the flag). If no turn is active, the
        event is still recorded with ``interrupted="between_turns"``
        and the cancel is a no-op (the queued user message, if any,
        will be picked up by the next :meth:`before_turn`).
        """
        interrupted_model_event_id: str | None = None
        interrupted_tool_call_id: str | None = None
        interrupted: Literal["generate", "tool_call", "between_turns"]
        if self._in_flight_tool_calls:
            interrupted = "tool_call"
            interrupted_tool_call_id = self._in_flight_tool_calls[0]
            self._cancelled_tool_call_ids = list(self._in_flight_tool_calls)
        elif self._active_model_event is not None:
            interrupted = "generate"
            interrupted_model_event_id = self._active_model_event.uuid
        else:
            interrupted = "between_turns"

        record_interrupt_event(
            source="user_cancel",
            interrupted=interrupted,
            interrupted_tool_call_id=interrupted_tool_call_id,
            interrupted_model_event_id=interrupted_model_event_id,
        )

        # Clear pending on the in-flight events so the transcript / log
        # viewer doesn't render them as forever-running. Mirror the
        # normal-completion paths in `_model.py:_generate_with_event`
        # (`complete()`) and `_call_tools.py:_execute_tools_impl` —
        # both clear `pending = None` then call
        # `transcript()._event_updated(event)` to notify log writers /
        # hook subscribers. Without the `_event_updated` call,
        # downstream consumers buffer the original pending event and
        # never see the cancellation.
        cancelled_events: list[Any] = []
        if self._active_model_event is not None:
            self._active_model_event.pending = None
            cancelled_events.append(self._active_model_event)
        for tc_id in self._in_flight_tool_calls:
            event = self._in_flight_tool_events.get(tc_id)
            if event is not None:
                event.pending = None
                # Mark the ToolEvent as cancelled so downstream consumers
                # (transcript renderers, the Phase 6 ACP router) don't
                # mis-render it as a successful completion. Mirrors the
                # synthetic `ChatMessageTool` repair message produced by
                # :meth:`after_cancel`.
                event.error = ToolCallError(
                    type="cancelled",
                    message="Tool call cancelled by user.",
                )
                event.failed = True
                cancelled_events.append(event)
        if cancelled_events:
            tr = transcript()
            for ev in cancelled_events:
                tr._event_updated(ev)

        if self._turn_cancel_scope is not None:
            self._pending_turn_cancel = True
            self._turn_cancel_scope.cancel()

    @contextlib.contextmanager
    def track_tool_call(
        self, tool_call_id: str, event: "ToolEvent | None" = None
    ) -> Iterator[None]:
        """Push/pop ``tool_call_id`` on the in-flight tool list.

        Phase 4 wraps each top-level tool execution in this so the
        session knows which tool call ids to record on cancel and
        repair afterwards. When ``event`` is provided, also registers
        the ``ToolEvent`` so :meth:`cancel_current_turn` can clear its
        ``pending`` flag. Safe under exceptions — the id and event are
        removed in the ``finally`` block.
        """
        self._in_flight_tool_calls.append(tool_call_id)
        if event is not None:
            self._in_flight_tool_events[tool_call_id] = event
        try:
            yield
        finally:
            try:
                self._in_flight_tool_calls.remove(tool_call_id)
            except ValueError:
                pass
            self._in_flight_tool_events.pop(tool_call_id, None)

    @contextlib.contextmanager
    def track_model_event(self, event: "ModelEvent") -> Iterator[None]:
        """Save/restore the in-flight model event on the session.

        Phase 4 will wrap each top-level model generation in this. We
        store on the session rather than relying on
        :func:`inspect_ai.log._samples.track_active_model_event` (which
        sets a ContextVar) because the transport task that fires the
        cancel runs in a sibling task with its own ContextVar copy and
        would see ``None``. Save/restore (not push/pop) handles nested
        generates correctly without growing a stack.
        """
        prev = self._active_model_event
        self._active_model_event = event
        try:
            yield
        finally:
            self._active_model_event = prev


def _is_noop(session: AcpSession) -> bool:
    return isinstance(session, _NoOpAcpSession)


_NOOP_SINGLETON: AcpSession = _NoOpAcpSession()

_acp_var: ContextVar[AcpSession] = ContextVar("_acp_session", default=_NOOP_SINGLETON)


@contextlib.asynccontextmanager
async def acp_session() -> AsyncIterator[AcpSession]:
    """Open an ACP session for the enclosing scope.

    If an ACP session is already active in this context (e.g. we are
    inside a sub-agent invoked from a top-level agent that already
    opened one), this scope installs a no-op shadow so nested agents
    never accidentally drive the outer session. The first non-shadowed
    entry installs the real session.

    Usage::

        async with acp_session() as acp:
            ...
    """
    current = _acp_var.get()
    install: AcpSession = (
        _NoOpAcpSession() if not _is_noop(current) else _LiveAcpSession()
    )
    token = _acp_var.set(install)
    try:
        async with install:
            yield install
    finally:
        _acp_var.reset(token)


def current_acp_session() -> AcpSession:
    """Return the currently active ACP session without entering a scope.

    Returns the no-op singleton when no ACP session is active. Safe to
    call from anywhere; never blocks; never raises.
    """
    return _acp_var.get()


def _unanswered_tool_call_ids(messages: list[ChatMessage]) -> list[str]:
    """Return tool_call ids from the last assistant message that lack a result.

    Used by :meth:`AcpSession.after_cancel` to synthesize repair
    :class:`ChatMessageTool` results for every tool call the assistant
    issued whose response is missing — covers tools that were in flight,
    tools that never started because an earlier call was cancelled, and
    tools whose results were lost when an anyio cancellation interrupted
    ``_execute_tools_impl`` before it could return.
    """
    last_assistant_idx: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], ChatMessageAssistant):
            last_assistant_idx = i
            break
    if last_assistant_idx is None:
        return []
    last_assistant = messages[last_assistant_idx]
    assert isinstance(last_assistant, ChatMessageAssistant)
    if not last_assistant.tool_calls:
        return []
    answered: set[str] = set()
    for m in messages[last_assistant_idx + 1 :]:
        if isinstance(m, ChatMessageTool) and m.tool_call_id:
            answered.add(m.tool_call_id)
    return [tc.id for tc in last_assistant.tool_calls if tc.id not in answered]
