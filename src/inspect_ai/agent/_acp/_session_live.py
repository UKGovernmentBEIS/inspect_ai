"""Live (active) AcpSession implementation + composed helpers.

Six helper classes own cohesive slices of ``LiveAcpSession``'s state
machine: fan-out subscriber bookkeeping, the user-message queue, the
interrupt-pending state machine, transcript capture, turn-cancel
snapshotting, and the approver-client registry. ``LiveAcpSession``
composes these and delegates its Protocol methods through. The split
exists for cognitive load — each cluster has enough internal detail to
read more clearly as a named object than as scattered fields.

Sub-agent filtering is a single bool kept inline on ``LiveAcpSession``
(``_filter_subagent_events``) — not worth its own helper class.
"""

from __future__ import annotations

import contextlib
from logging import getLogger
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterator,
    Literal,
    Sequence,
)

import anyio
from anyio.streams.memory import (
    MemoryObjectReceiveStream,
    MemoryObjectSendStream,
)
from shortuuid import uuid

from inspect_ai.agent._acp._session import (
    _SUBSCRIBER_BUFFER_SIZE,
    AcpSession,
    AcpUpdate,
    ApproverClient,
    TurnCancelled,
)
from inspect_ai.log._transcript import transcript
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.tool._tool_call import ToolCallError

if TYPE_CHECKING:
    from inspect_ai.agent._acp._event_mapping import _AcpEventRouter
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.log._transcript import Transcript

logger = getLogger(__name__)


# ---------------------------------------------------------------------------
# LiveAcpSession internal helpers
# ---------------------------------------------------------------------------


class _PubSubBus:
    """Fan-out send streams for ``session/update`` subscribers.

    Owns the list of (send, receive) pairs. Each ``attach()`` mints a
    new stream pair; the bus keeps the send half for ``publish()`` and
    hands the receive half to the caller. Slow consumers don't stall
    siblings (per-subscriber buffer) and dead consumers prune on next
    publish (``BrokenResourceError``).
    """

    def __init__(self) -> None:
        self._subscribers: list[
            tuple[
                MemoryObjectSendStream[AcpUpdate],
                MemoryObjectReceiveStream[AcpUpdate],
            ]
        ] = []

    def attach(self) -> MemoryObjectReceiveStream[AcpUpdate]:
        send, receive = anyio.create_memory_object_stream[AcpUpdate](
            max_buffer_size=_SUBSCRIBER_BUFFER_SIZE
        )
        self._subscribers.append((send, receive))
        return receive

    def detach(self, stream: MemoryObjectReceiveStream[AcpUpdate]) -> None:
        for i, (send, receive) in enumerate(self._subscribers):
            if receive is stream:
                send.close()
                del self._subscribers[i]
                return

    def publish(self, update: AcpUpdate) -> None:
        dead: list[int] = []
        for i, (send, _) in enumerate(self._subscribers):
            try:
                send.send_nowait(update)
            except anyio.BrokenResourceError:
                dead.append(i)
        for i in reversed(dead):
            send, _ = self._subscribers.pop(i)
            send.close()

    def close_all(self) -> None:
        """Close every subscriber send half; receivers see clean EOF."""
        for send, _ in self._subscribers:
            send.close()
        self._subscribers.clear()


class _UserMessageQueue:
    """Operator-injected user messages awaiting drain by the agent loop.

    Two drain semantics:
    - ``drain_initial`` — first ``before_turn`` call; blocks only if
      ``messages`` has no user content yet (covers the "no dataset
      prompt, operator types the first message" case). Subsequent
      ``before_turn`` calls also route through here, drain immediately.
    - ``drain_blocking`` — ``after_cancel`` call; always blocks until at
      least one message is queued, then drains.

    The event is recreated after each drain so a stale ``set()`` from
    a fired-then-drained message doesn't trigger a no-op wake on the
    next wait.
    """

    def __init__(self) -> None:
        self._messages: list[ChatMessageUser] = []
        self._event = anyio.Event()
        self._first_drain_handled = False

    def enqueue(self, msg: ChatMessageUser) -> None:
        self._messages.append(msg)
        self._event.set()

    async def drain_initial(
        self, messages: Sequence[ChatMessage]
    ) -> list[ChatMessageUser]:
        if not self._first_drain_handled:
            self._first_drain_handled = True
            if not any(isinstance(m, ChatMessageUser) for m in messages):
                while not self._messages:
                    evt = self._event
                    await evt.wait()
        return self._drain()

    async def drain_blocking(self) -> list[ChatMessageUser]:
        if not self._messages:
            while not self._messages:
                evt = self._event
                await evt.wait()
        return self._drain()

    def _drain(self) -> list[ChatMessageUser]:
        drained = list(self._messages)
        self._messages.clear()
        self._event = anyio.Event()
        return drained


class _InterruptCoordinator:
    """Modal-prompt-mode state machine and its subscriber registries.

    ``pending`` is True between :meth:`mark_interrupted` (called from
    ``cancel_current_turn``) and :meth:`resolve_if_pending` (called from
    ``submit_user_message`` or the user-message drain in
    ``after_cancel``). Subscribers fire when the state transitions —
    in-proc TUI modal-prompt mode + Inspect-aware ACP clients both use
    these to render/dismiss their prompt UI.
    """

    def __init__(self) -> None:
        self._pending: bool = False
        self._interrupted_subscribers: list[Callable[[], None]] = []
        self._prompt_resolved_subscribers: list[Callable[[], None]] = []

    @property
    def pending(self) -> bool:
        return self._pending

    def mark_interrupted(self) -> None:
        """Set pending=True and notify interrupted subscribers."""
        self._pending = True
        self._fire(self._interrupted_subscribers, "interrupted")

    def resolve_if_pending(self) -> bool:
        """Clear pending and notify resolved subscribers. Return True iff resolved."""
        if not self._pending:
            return False
        self._pending = False
        self._fire(self._prompt_resolved_subscribers, "prompt_resolved")
        return True

    def subscribe_interrupted(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._interrupted_subscribers.append(callback)

        def _unsubscribe() -> None:
            try:
                self._interrupted_subscribers.remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    def subscribe_prompt_resolved(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        self._prompt_resolved_subscribers.append(callback)

        def _unsubscribe() -> None:
            try:
                self._prompt_resolved_subscribers.remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    def clear_subscribers(self) -> None:
        """Drop all subscriber callbacks; called from session __aexit__."""
        self._interrupted_subscribers.clear()
        self._prompt_resolved_subscribers.clear()

    @staticmethod
    def _fire(subs: list[Callable[[], None]], label: str) -> None:
        for cb in list(subs):
            try:
                cb()
            except Exception:
                logger.exception(f"{label} subscriber raised; continuing")


class _TranscriptCapture:
    """Sample transcript captured at session entry for sibling-task access.

    ``transcript()`` (the ContextVar lookup) returns the active sample's
    Transcript only when called inside the sample's task.
    ``cancel_current_turn`` runs from sibling tasks (TUI button click,
    socket transport) where the ContextVar would resolve to a default
    empty Transcript — silently losing the InterruptEvent and the
    pending-flag updates on cancelled in-flight events. So we capture
    the ref at ``__aenter__`` time and use the captured ref from sibling
    contexts.

    Falls back to ``transcript()`` when ``capture()`` wasn't called —
    tests construct a bare ``LiveAcpSession`` and set the ContextVar
    directly, and the fallback supports them.

    Also owns ``attach_index``: the transcript event count at the moment
    the live router subscribed. Replay on late attach must skip events
    before this index, or the sub-agent depth filter treats the eval
    framework's outer ``AGENT_SPAN`` (which the live router never saw)
    as a sub-agent boundary and filters every in-scope event.
    """

    def __init__(self) -> None:
        self._captured: Transcript | None = None
        self._attach_index: int = 0

    def capture(self) -> None:
        """Snapshot ``transcript()`` from the current task context."""
        self._captured = transcript()

    @property
    def captured(self) -> Transcript | None:
        return self._captured

    @captured.setter
    def captured(self, value: Transcript | None) -> None:
        # Setter exists so tests can wire up a transcript without
        # entering the session through __aenter__.
        self._captured = value

    def transcript(self) -> Transcript:
        """Return captured transcript; fall back to ContextVar lookup."""
        return self._captured if self._captured is not None else transcript()

    @property
    def attach_index(self) -> int:
        return self._attach_index

    @attach_index.setter
    def attach_index(self, value: int) -> None:
        self._attach_index = value

    def subscribe(self, callback: Callable[[Any], None]) -> Callable[[], None]:
        if self._captured is None:

            def _noop_unsubscribe() -> None:
                return None

            return _noop_unsubscribe
        return self._captured._add_subscriber(callback)

    def snapshot(self) -> Sequence[Any]:
        if self._captured is None:
            return []
        # list() the events sequence so callers iterating concurrently
        # with new ``_event`` appends don't see size changes mid-iteration.
        return list(self._captured.events)[self._attach_index :]


class _CancelSnapshot:
    """Result of :meth:`_TurnCancelMachinery.snapshot_for_cancel`.

    Captures everything ``cancel_current_turn`` needs to populate the
    ``InterruptEvent`` and notify downstream consumers of cancelled
    in-flight events.
    """

    __slots__ = (
        "kind",
        "interrupted_tool_call_id",
        "interrupted_model_event_id",
        "cancelled_events",
    )

    def __init__(
        self,
        kind: Literal["generate", "tool_call", "between_turns"],
        interrupted_tool_call_id: str | None,
        interrupted_model_event_id: str | None,
        cancelled_events: list[Any],
    ) -> None:
        self.kind = kind
        self.interrupted_tool_call_id = interrupted_tool_call_id
        self.interrupted_model_event_id = interrupted_model_event_id
        self.cancelled_events = cancelled_events


class _TurnCancelMachinery:
    """Per-turn cancel scope + in-flight tool/model tracking.

    Bundles the state that ``cancel_current_turn`` consults when a
    client cancel arrives from a sibling task: which tool call (if any)
    is mid-execution, which ModelEvent (if any) is mid-generation, and
    the live ``CancelScope`` to cancel. Also snapshots the in-flight
    tool ids at cancel time so ``after_cancel`` can synthesize repair
    messages when no ``state.messages`` is provided.
    """

    def __init__(self) -> None:
        self._turn_cancel_scope: anyio.CancelScope | None = None
        # Discriminates a client-driven cancel (we cancelled the scope)
        # from a sample-level cancel propagating from outside.
        self._pending_turn_cancel: bool = False
        self._in_flight_tool_calls: list[str] = []
        # Tool events keyed by id so cancel can clear ``pending=True``
        # (otherwise the transcript shows cancelled tool rows as
        # in-flight forever).
        self._in_flight_tool_events: dict[str, ToolEvent] = {}
        # Snapshot at cancel time; ``after_cancel`` consumes when called
        # without ``state.messages``.
        self._cancelled_tool_call_ids: list[str] = []
        # In-flight model call. Stored here (not in a ContextVar) so a
        # sibling transport task firing a cancel can read it.
        self._active_model_event: ModelEvent | None = None

    @contextlib.contextmanager
    def turn_scope(self) -> Iterator[None]:
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

    @contextlib.contextmanager
    def track_tool_call(
        self, tool_call_id: str, event: ToolEvent | None = None
    ) -> Iterator[None]:
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
    def track_model_event(self, event: ModelEvent) -> Iterator[None]:
        prev = self._active_model_event
        self._active_model_event = event
        try:
            yield
        finally:
            self._active_model_event = prev

    def snapshot_for_cancel(self) -> _CancelSnapshot:
        """Snapshot in-flight state and mark events as cancelled.

        Mutates the in-flight model event + tool events to clear
        ``pending=True`` and set the appropriate error/failed fields so
        downstream consumers (transcript renderers, the ACP router) see
        them as cancelled rather than forever-in-flight. Returns the
        snapshot so ``cancel_current_turn`` can record the
        ``InterruptEvent`` and call ``_event_updated`` on each modified
        event.

        Mirrors the normal-completion paths in
        ``_model.py:_generate_with_event`` and
        ``_call_tools.py:_execute_tools_impl`` — both clear
        ``pending = None`` and call ``transcript()._event_updated(event)``
        to notify log writers / hook subscribers.
        """
        # Deferred import — `inspect_ai.event` circularly references the
        # session module via the event union.
        from inspect_ai.event._model import OPERATOR_CANCEL_ERROR

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

        cancelled_events: list[Any] = []
        if self._active_model_event is not None:
            self._active_model_event.pending = None
            # Mark the ModelEvent as operator-cancelled so the natural
            # ``complete()`` path in ``_model.py`` skips overwriting
            # ``output`` if the model's streamed response finishes inside
            # the cancellation propagation window. Without this, the
            # accumulated model text gets painted into the transcript
            # below the InterruptEvent.
            self._active_model_event.error = OPERATOR_CANCEL_ERROR
            cancelled_events.append(self._active_model_event)
        for tc_id in self._in_flight_tool_calls:
            event = self._in_flight_tool_events.get(tc_id)
            if event is not None:
                event.pending = None
                event.error = ToolCallError(
                    type="cancelled",
                    message="Tool call cancelled by user.",
                )
                event.failed = True
                cancelled_events.append(event)

        return _CancelSnapshot(
            kind=interrupted,
            interrupted_tool_call_id=interrupted_tool_call_id,
            interrupted_model_event_id=interrupted_model_event_id,
            cancelled_events=cancelled_events,
        )

    def request_cancel(self) -> bool:
        """Cancel the active turn scope. Returns True iff a turn was active."""
        if self._turn_cancel_scope is not None:
            self._pending_turn_cancel = True
            self._turn_cancel_scope.cancel()
            return True
        return False

    @property
    def cancelled_tool_call_ids(self) -> list[str]:
        return self._cancelled_tool_call_ids

    def clear_cancelled_tool_ids(self) -> None:
        self._cancelled_tool_call_ids.clear()


class _ApproverClientRegistry:
    """Attached ACP clients capable of handling ``session/request_permission``.

    The configured ``human_approver`` routes tool-approval prompts
    through here when at least one client is attached, falling back to
    the in-proc panel / console flow when none are. Clients register on
    bind (``Forwarders.start``) and detach on unbind / disconnect
    (``Forwarders.stop``).
    """

    def __init__(self) -> None:
        self._clients: list[ApproverClient] = []

    def attach(self, client: ApproverClient) -> Callable[[], None]:
        self._clients.append(client)

        def _unsubscribe() -> None:
            try:
                self._clients.remove(client)
            except ValueError:
                pass

        return _unsubscribe

    def has_clients(self) -> bool:
        return bool(self._clients)

    def clients(self) -> list[ApproverClient]:
        """Snapshot copy so iteration is stable against concurrent attach/detach."""
        return list(self._clients)

    def clear(self) -> None:
        self._clients.clear()


# ---------------------------------------------------------------------------
# LiveAcpSession
# ---------------------------------------------------------------------------


class LiveAcpSession:
    """Active ACP session: owns the in-process pub/sub bus.

    Installed by :func:`acp_session` as the outermost ACP scope in a
    sample. Subscribers (the in-process TUI and the socket transport)
    call :meth:`attach` to receive ``session/update``-shaped payloads.
    """

    def __init__(self) -> None:
        self._session_id: str = uuid()
        self._pubsub = _PubSubBus()
        self._user_messages = _UserMessageQueue()
        self._interrupt = _InterruptCoordinator()
        self._transcript_capture = _TranscriptCapture()
        self._turn_cancel = _TurnCancelMachinery()
        self._approvers = _ApproverClientRegistry()
        # When True, the live router drops events emitted inside
        # sub-agents (depth>0). Standard ACP semantic for editor clients.
        # Disabled by consumers (debugging tooling, raw-stream TUIs) that
        # want full sub-agent visibility through the pub/sub bus.
        # Kept inline (not wrapped in a helper) — single bool not worth
        # the encapsulation overhead.
        self._filter_subagent_events: bool = True
        # Router attached at __aenter__; detached at __aexit__. Owns the
        # transcript subscription that maps events to SessionNotifications.
        self._router: _AcpEventRouter | None = None

    @property
    def session_id(self) -> str:
        """Opaque, stable identifier minted at construction (shortuuid)."""
        return self._session_id

    async def __aenter__(self) -> AcpSession:
        """Enter the session scope; attach the event router and return ``self``.

        Also registers ``self`` on the current :class:`ActiveSample`
        (if any) so out-of-task consumers like the in-process Inspect
        TUI can locate the live session by sample reference.
        """
        from inspect_ai.agent._acp._event_mapping import _AcpEventRouter
        from inspect_ai.log._samples import sample_active

        self._transcript_capture.capture()
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
        self._pubsub.close_all()
        # Drop interrupt-coordination subscribers so a late listener
        # (TUI widget unmount race, connection-handler unbind race)
        # doesn't end up holding a callback that fires into a closed
        # context. Drop approver-client registrations for the same
        # reason — a late-arriving approval prompt after session exit
        # would otherwise try to call into a closed connection.
        self._interrupt.clear_subscribers()
        self._approvers.clear()

    # Property delegations that preserve the field-access surface the
    # router and a handful of tests already depend on. Storage lives in
    # the helper objects; these are the read/write paths through the
    # session facade.

    @property
    def _transcript(self) -> Transcript | None:
        return self._transcript_capture.captured

    @_transcript.setter
    def _transcript(self, value: Transcript | None) -> None:
        self._transcript_capture.captured = value

    @property
    def _router_attach_index(self) -> int:
        return self._transcript_capture.attach_index

    @_router_attach_index.setter
    def _router_attach_index(self, value: int) -> None:
        self._transcript_capture.attach_index = value

    @property
    def _subscribers(
        self,
    ) -> list[
        tuple[
            MemoryObjectSendStream[AcpUpdate],
            MemoryObjectReceiveStream[AcpUpdate],
        ]
    ]:
        return self._pubsub._subscribers

    def disable_subagent_filtering(self) -> None:
        """Allow sub-agent transcript events through to the pub/sub bus.

        By default the live router drops any transcript event emitted
        while a sub-agent boundary is open — the standard ACP semantic
        where the editor sees only the outer agent's conversation. Some
        consumers (debugging tooling, raw-event TUIs) want every event
        instead; calling this method disables the filter for the rest of
        the session.
        """
        self._filter_subagent_events = False

    def attach(self) -> MemoryObjectReceiveStream[AcpUpdate]:
        """Create a new subscriber stream pair, keep the send half, return the receive half."""
        return self._pubsub.attach()

    def detach(self, stream: MemoryObjectReceiveStream[AcpUpdate]) -> None:
        """Close the matching send half and drop the subscriber.

        Identity match (``receive is stream``). Safe to call with an
        unknown or already-detached stream — silently does nothing.
        """
        self._pubsub.detach(stream)

    def publish(self, update: AcpUpdate) -> None:
        """Fan ``update`` out non-blockingly to all attached subscribers."""
        self._pubsub.publish(update)

    def subscribe_transcript_events(
        self, callback: Callable[[Any], None]
    ) -> Callable[[], None]:
        """Register a sync callback on this session's captured transcript.

        Raw-event forwarder hook. Wraps
        :meth:`Transcript._add_subscriber` so callers can subscribe
        without reaching into private session state and without the
        ContextVar-lookup gotcha (we run from the connection's task,
        not the sample's, so ``transcript()`` would return the empty
        default).
        """
        return self._transcript_capture.subscribe(callback)

    def transcript_events_snapshot(self) -> Sequence[Any]:
        """Snapshot the captured transcript's event list for replay.

        Returns an empty sequence if the session hasn't been entered
        yet (defensive — should be unreachable in practice).

        Slices off the events from before the router attached: those
        pre-attach events include the eval framework's outer
        ``AGENT_SPAN`` begin, which the live router never saw (it
        subscribed inside that span). If they bleed into replay, the
        sub-agent depth filter treats every in-scope event as a
        sub-agent and silently filters the entire conversation.
        """
        return self._transcript_capture.snapshot()

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
        with self._turn_cancel.turn_scope():
            yield

    async def before_turn(
        self, messages: Sequence[ChatMessage]
    ) -> list[ChatMessageUser]:
        """Drain queued operator messages and return them.

        On the first call, if ``messages`` has no user content yet,
        blocks for at least one queued message — covers the "no dataset
        prompt, operator types the first message" case. Subsequent
        calls drain immediately.
        """
        return await self._user_messages.drain_initial(messages)

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

        When ``messages`` is provided (the normal production path), this
        scans the last assistant message's ``tool_calls`` and synthesizes
        a repair for every id that doesn't yet have a matching
        :class:`ChatMessageTool` result. That covers three cases under
        sequential tool execution: tools that were in flight at cancel,
        tools that never started because an earlier call was cancelled,
        and tools whose completed results were lost when
        ``_execute_tools_impl`` was interrupted before returning. When
        ``messages`` is ``None`` (unit tests), falls back to
        ``_cancelled_tool_call_ids`` (snapshotted in
        :meth:`cancel_current_turn`).
        """
        results: list[ChatMessage] = []
        if messages is not None:
            repair_ids = _unanswered_tool_call_ids(messages)
        else:
            repair_ids = list(self._turn_cancel.cancelled_tool_call_ids)
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
        self._turn_cancel.clear_cancelled_tool_ids()
        drained = await self._user_messages.drain_blocking()
        results.extend(drained)

        # The agent has now consumed the resumption text, so the
        # interrupt is logically resolved — clear the pending flag and
        # notify prompt-resolved subscribers if they haven't already
        # been fired. ``submit_user_message`` clears + fires when the
        # message arrives AFTER the cancel; this branch covers the
        # other ordering (message queued BEFORE the cancel, then
        # drained here without ``submit_user_message`` being called
        # post-cancel). Without this, a modal-prompt client would be
        # stuck in pending state forever after that sequence.
        self._interrupt.resolve_if_pending()

        return results

    def submit_user_message(self, msg: ChatMessageUser) -> None:
        """Queue ``msg`` and wake any awaiter blocked on it.

        Normalizes provenance: any message queued through this API is
        treated as operator-injected, so ``source`` is set to
        ``"operator"`` if it isn't already. Callers don't have to
        remember to set it themselves.

        If an interrupt is pending (``cancel_current_turn`` fired and
        wasn't yet resolved), clear the pending flag and notify
        prompt-resolved subscribers. The in-proc TUI's modal prompt
        mode and Inspect-aware ACP clients use this to dismiss their
        prompt UI when a sibling client provides the resumption text.
        """
        if msg.source != "operator":
            msg = msg.model_copy(update={"source": "operator"})
        self._user_messages.enqueue(msg)
        self._interrupt.resolve_if_pending()

    @property
    def interrupt_pending(self) -> bool:
        """True between ``cancel_current_turn`` and the next ``submit_user_message``."""
        return self._interrupt.pending

    def subscribe_interrupted(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback fired on every ``cancel_current_turn``.

        Returns an idempotent unsubscribe callable. Callbacks run
        synchronously in the producer's task; exceptions are logged
        and swallowed so one broken subscriber can't block others.
        """
        return self._interrupt.subscribe_interrupted(callback)

    def subscribe_prompt_resolved(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback fired when an interrupt is resolved.

        Fires when ``submit_user_message`` lands while ``interrupt_pending``
        is True (i.e. the message resolves an open interrupt). Does NOT
        fire for ordinary user messages outside an interrupt cycle.

        Returns an idempotent unsubscribe callable.
        """
        return self._interrupt.subscribe_prompt_resolved(callback)

    def attach_approver_client(self, client: ApproverClient) -> Callable[[], None]:
        """Register ``client`` as a recipient for approval prompts.

        Returns an idempotent unsubscribe callable. Re-attaching the
        same client multiple times is allowed (and adds N entries) —
        each attach is paired with one returned unsubscribe.
        """
        return self._approvers.attach(client)

    def has_approver_clients(self) -> bool:
        """True if at least one approver client is currently attached."""
        return self._approvers.has_clients()

    def approver_clients(self) -> list[ApproverClient]:
        """Snapshot copy of attached clients.

        Returns a copy so iteration is stable against concurrent
        attach / detach (a client can disconnect mid-race).
        """
        return self._approvers.clients()

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
        # snapshot_for_cancel mutates the in-flight events (clears
        # pending, sets error/failed) and returns the data we need to
        # populate the InterruptEvent + notify downstream consumers.
        snapshot = self._turn_cancel.snapshot_for_cancel()

        # Deferred import — `inspect_ai.event` circularly references
        # this module via the event union.
        from inspect_ai.event._interrupt import InterruptEvent

        # Append InterruptEvent + the modified in-flight events to the
        # sample's transcript via the captured reference (NOT
        # ``transcript()``). The caller usually runs in a sibling task
        # where the ContextVar would resolve to a default empty
        # Transcript — see the comment on :class:`_TranscriptCapture`.
        tr = self._transcript_capture.transcript()
        tr._event(
            InterruptEvent(
                source="user_cancel",
                interrupted=snapshot.kind,
                interrupted_tool_call_id=snapshot.interrupted_tool_call_id,
                interrupted_model_event_id=snapshot.interrupted_model_event_id,
            )
        )
        # Notify log writers / hook subscribers about the cleared
        # pending flag — without ``_event_updated``, downstream
        # consumers buffer the original pending event and never see
        # the cancellation.
        for ev in snapshot.cancelled_events:
            tr._event_updated(ev)

        self._turn_cancel.request_cancel()

        # Mark the interrupt as pending and notify subscribers so
        # prompt-mode clients (the in-proc TUI; Inspect-aware ACP
        # clients via inspect/prompt_resolved) can render their
        # modal prompt UI. The next ``submit_user_message`` clears
        # the flag and fires the resolved subscribers.
        self._interrupt.mark_interrupted()

    @contextlib.contextmanager
    def track_tool_call(
        self, tool_call_id: str, event: ToolEvent | None = None
    ) -> Iterator[None]:
        """Push/pop ``tool_call_id`` on the in-flight tool list.

        Top-level tool execution wraps in this so the session knows
        which tool call ids to record on cancel and
        repair afterwards. When ``event`` is provided, also registers
        the ``ToolEvent`` so :meth:`cancel_current_turn` can clear its
        ``pending`` flag. Safe under exceptions — the id and event are
        removed in the ``finally`` block.
        """
        with self._turn_cancel.track_tool_call(tool_call_id, event):
            yield

    @contextlib.contextmanager
    def track_model_event(self, event: ModelEvent) -> Iterator[None]:
        """Save/restore the in-flight model event on the session.

        Top-level model generation wraps in this. We store on the
        session rather than relying on
        :func:`inspect_ai.log._samples.track_active_model_event` (which
        sets a ContextVar) because the transport task that fires the
        cancel runs in a sibling task with its own ContextVar copy and
        would see ``None``. Save/restore (not push/pop) handles nested
        generates correctly without growing a stack.
        """
        with self._turn_cancel.track_model_event(event):
            yield


def _unanswered_tool_call_ids(messages: list[ChatMessage]) -> list[str]:
    """Return tool_call ids from the last assistant message that lack a result.

    Used by :meth:`LiveAcpSession.after_cancel` to synthesize repair
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
