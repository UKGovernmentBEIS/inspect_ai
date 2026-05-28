"""Live (active) AcpTransport implementation + composed helpers.

Six helper classes own cohesive slices of ``LiveAcpTransport``'s state
machine: fan-out subscriber bookkeeping, the user-message queue, the
interrupt-pending state machine, transcript capture, turn-cancel
snapshotting, and the approver-client registry. ``LiveAcpTransport``
composes these and delegates its Protocol methods through. The split
exists for cognitive load — each cluster has enough internal detail to
read more clearly as a named object than as scattered fields.

Sub-agent filtering is a single bool kept inline on ``LiveAcpTransport``
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

from inspect_ai.agent._acp._client_registry import _ClientDriverRegistry
from inspect_ai.agent._acp._guards import acp_guard
from inspect_ai.agent._acp.transport import (
    _SUBSCRIBER_BUFFER_SIZE,
    AcpTransport,
    AcpUpdate,
    ApproverClient,
    ElicitationClient,
)
from inspect_ai.log._transcript import transcript
from inspect_ai.model._chat_message import (
    ChatMessageUser,
)
from inspect_ai.tool._tool_call import ToolCallError

if TYPE_CHECKING:
    from inspect_ai.agent._acp.event_mapping import _AcpEventRouter
    from inspect_ai.agent._channel import AgentChannel, AgentRef
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.log._transcript import Transcript

logger = getLogger(__name__)


# ---------------------------------------------------------------------------
# LiveAcpTransport internal helpers
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
        # Catches both ``BrokenResourceError`` (receive half closed) and
        # ``ClosedResourceError`` (send half closed by a concurrent
        # ``detach()`` / ``close_all()``) — the second can race with this
        # publish because we run from the agent task while teardown runs
        # from a sibling. Any other unexpected exception is logged at
        # WARNING; this method is called from the agent's hot path
        # (transcript subscriber callback) and must never propagate.
        dead: list[int] = []
        for i, (send, _) in enumerate(self._subscribers):
            try:
                send.send_nowait(update)
            except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                dead.append(i)
            except Exception:
                logger.warning(
                    "ACP publish failed for one subscriber; dropping it",
                    exc_info=True,
                )
                dead.append(i)
        for i in reversed(dead):
            send, _ = self._subscribers.pop(i)
            try:
                send.close()
            except Exception:
                pass

    def close_all(self) -> None:
        """Close every subscriber send half; receivers see clean EOF."""
        for send, _ in self._subscribers:
            send.close()
        self._subscribers.clear()


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
    tests construct a bare ``LiveAcpTransport`` and set the ContextVar
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
    """In-flight tool/model tracking and ``InterruptEvent`` snapshotting.

    Bundles the state that ``cancel_current_turn`` consults when a
    client cancel arrives from a sibling task: which tool call (if any)
    is mid-execution and which ModelEvent (if any) is mid-generation.
    The cancellation primitive itself lives on the agent's
    :class:`~inspect_ai.agent.AgentChannel`; this class only owns the
    ACP-specific telemetry the wire/log layers need.
    """

    def __init__(self) -> None:
        self._in_flight_tool_calls: list[str] = []
        # Tool events keyed by id so cancel can clear ``pending=True``
        # (otherwise the transcript shows cancelled tool rows as
        # in-flight forever).
        self._in_flight_tool_events: dict[str, ToolEvent] = {}
        # In-flight model call. Stored here (not in a ContextVar) so a
        # sibling transport task firing a cancel can read it.
        self._active_model_event: ModelEvent | None = None

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

    def snapshot_for_cancel(
        self,
        cause: Literal["user_cancel", "limit", "system"] = "user_cancel",
    ) -> _CancelSnapshot:
        """Snapshot in-flight state and mark events as cancelled.

        Mutates the in-flight model event + tool events to clear
        ``pending=True`` and set the appropriate error/failed fields so
        downstream consumers (transcript renderers, the ACP router) see
        them as cancelled rather than forever-in-flight. Returns the
        snapshot so ``cancel_current_turn`` can record the
        ``InterruptEvent`` and call ``_event_updated`` on each modified
        event.

        ``cause`` selects the sentinel stamped on each in-flight
        event so the per-event provenance matches
        ``InterruptEvent.source`` — without this, a limit-driven cancel
        would stamp ``OPERATOR_CANCEL_ERROR`` / "cancelled by user" on
        events the operator never touched, leaving JSON logs and
        downstream consumers with conflicting provenance.

        Mirrors the normal-completion paths in
        ``_model.py:_generate_with_event`` and
        ``_call_tools.py:_execute_tools_impl`` — both clear
        ``pending = None`` and call ``transcript()._event_updated(event)``
        to notify log writers / hook subscribers.
        """
        # Deferred import — `inspect_ai.event` circularly references the
        # session module via the event union.
        from inspect_ai.event._model import (
            LIMIT_CANCEL_ERROR,
            OPERATOR_CANCEL_ERROR,
            SYSTEM_CANCEL_ERROR,
        )

        model_error_for_cause: dict[str, str] = {
            "user_cancel": OPERATOR_CANCEL_ERROR,
            "limit": LIMIT_CANCEL_ERROR,
            "system": SYSTEM_CANCEL_ERROR,
        }
        tool_message_for_cause: dict[str, str] = {
            "user_cancel": "Tool call cancelled by user.",
            "limit": "Tool call cancelled by limit.",
            "system": "Tool call cancelled by system.",
        }

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
            # Mark the ModelEvent with the cause-appropriate cancel
            # sentinel so the natural ``complete()`` path in
            # ``_model.py`` skips overwriting ``output`` if the model's
            # streamed response finishes inside the cancellation
            # propagation window. Without this, the accumulated model
            # text gets painted into the transcript below the
            # InterruptEvent. The sentinel choice mirrors
            # ``InterruptEvent.source`` so per-event provenance is
            # consistent with the sample-level interrupt record.
            self._active_model_event.error = model_error_for_cause[cause]
            cancelled_events.append(self._active_model_event)
        for tc_id in self._in_flight_tool_calls:
            event = self._in_flight_tool_events.get(tc_id)
            if event is not None:
                event.pending = None
                event.error = ToolCallError(
                    type="cancelled",
                    message=tool_message_for_cause[cause],
                )
                event.failed = True
                cancelled_events.append(event)

        return _CancelSnapshot(
            kind=interrupted,
            interrupted_tool_call_id=interrupted_tool_call_id,
            interrupted_model_event_id=interrupted_model_event_id,
            cancelled_events=cancelled_events,
        )


class _ApproverClientRegistry(_ClientDriverRegistry[ApproverClient]):
    """Driver-chain registry for ``ApproverClient`` instances.

    The configured ``human_approver`` routes tool-approval prompts to
    a SINGLE driver — the last client to send a ``session/prompt`` on
    this session, with first-attached as the fallback when no prompt
    has been sent yet. Clients register on bind
    (``Forwarders.start``) and detach on unbind / disconnect
    (``Forwarders.stop``).

    All behaviour comes from :class:`_ClientDriverRegistry`; this class
    exists for nominal type distinctness and to anchor the doc-string
    that explains the approval-side usage of the chain.
    """


class _ElicitationClientRegistry(_ClientDriverRegistry[ElicitationClient]):
    """Driver-chain registry for ``ElicitationClient`` instances.

    The Phase 6 ``acp_handler`` routes ``elicitation/create`` requests
    to a SINGLE driver — same first-attached-fallback and
    last-prompt-wins semantics as the approval registry. Clients
    register on bind only when the client advertised
    ``elicitation.form`` capability during ``initialize`` (gated in
    ``connection.py``); without that capability the connection
    handler skips the elicitation attach entirely.
    """


class _SessionClientRegistries:
    """Group of client-driver registries for an ACP session.

    Each registry stays domain-specific: clients attach (and detach)
    per-domain — the elicitation registry is capability-gated in the
    connection handler so the connection only attaches there when the
    client advertised ``elicitation.form``. Cross-cutting operations
    that should fan out to **every** registry — ``mark_active`` on
    each ``session/prompt``, ``clear`` on teardown — live here so
    adding a new registry doesn't require chasing every call site.
    """

    def __init__(self) -> None:
        self.approvers = _ApproverClientRegistry()
        self.elicitations = _ElicitationClientRegistry()

    def _all(self) -> tuple[_ClientDriverRegistry[Any], ...]:
        return (self.approvers, self.elicitations)

    def mark_active(self, client: Any) -> None:
        """Promote ``client`` as driver for every registry it belongs to.

        Each registry's :meth:`mark_active` is a no-op when the client
        isn't in its lists, so this is safe to call unconditionally —
        a connection that's only registered as an approver (no
        elicitation capability) silently skips promotion in the
        elicitation registry.
        """
        for reg in self._all():
            reg.mark_active(client)

    def clear(self) -> None:
        for reg in self._all():
            reg.clear()


# ---------------------------------------------------------------------------
# LiveAcpTransport
# ---------------------------------------------------------------------------


class LiveAcpTransport:
    """Active ACP session: owns the in-process pub/sub bus.

    Installed by :func:`acp_session` as the outermost ACP scope in a
    sample. Subscribers (the in-process TUI and the socket transport)
    call :meth:`attach` to receive ``session/update``-shaped payloads.
    """

    def __init__(self) -> None:
        self._session_id: str = uuid()
        self._pubsub = _PubSubBus()
        self._interrupt = _InterruptCoordinator()
        self._transcript_capture = _TranscriptCapture()
        self._turn_cancel = _TurnCancelMachinery()
        self._clients = _SessionClientRegistries()
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
        # Split-phase teardown flags. The agent's ``async with`` block
        # exits before the task runner's scoring + logging block runs;
        # we want scoring events to still reach attached clients. So
        # ``__aexit__`` enters a "post-agent" state when bound to an
        # ActiveSample, and ``finalize()`` does the deferred teardown
        # later (called from ``active_sample().__aexit__``).
        self._agent_completed: bool = False
        self._finalized: bool = False
        # AgentRef captured at react() entry via :meth:`maybe_bind` so
        # producer-side intervention (``submit_user_message`` /
        # ``cancel_current_turn``) routes into the agent's channel.
        # First-binder-wins per active top-level react; cleared by
        # :meth:`unbind`; rebindable by a successor react.
        self._ref: "AgentRef | None" = None
        # Unsubscribe handle for the channel drain observer registered
        # during :meth:`maybe_bind`. Stored so :meth:`unbind` can drop
        # the subscription cleanly; ``None`` when not currently bound.
        self._unsubscribe_drained: Callable[[], None] | None = None
        # Clear handle for the channel's external-reach marker. Set in
        # :meth:`maybe_bind` iff :func:`acp_server_accepting_clients`
        # was True at bind time (i.e. an :class:`AcpServer` is up and
        # accepting); ``None`` otherwise. The Live transport is opened
        # per-sample regardless of ``--acp-server`` for sub-agent /
        # in-proc plumbing reasons, but only the externally-reachable
        # case should flip ``AgentChannel.is_live`` — that's the
        # signal consumers use to decide whether to spin up
        # interactive plumbing (e.g. an agent CLI in stdin-streaming
        # mode).
        self._clear_live: Callable[[], None] | None = None
        # Test-only override for :attr:`is_attachable`. Production code
        # leaves this at ``None`` (the property derives from ``_ref`` +
        # ``_agent_completed``). Test fixtures that hand-wire a session
        # without going through the real bind flow can set this to
        # ``True`` to make the picker treat the session as attachable.
        self._attachable_override: bool | None = None

    @property
    def session_id(self) -> str:
        """Opaque, stable identifier minted at construction (shortuuid)."""
        return self._session_id

    @property
    def ref(self) -> "AgentRef | None":
        """Currently-bound :class:`AgentRef`, or ``None``."""
        return self._ref

    @property
    def is_attachable(self) -> bool:
        """True iff a channel is bound and the agent loop is still live.

        Returns False (a) before the first :meth:`maybe_bind` (sample
        setup window) and (b) after :meth:`finalize` has marked the
        transport agent-completed (scoring window). Either state means
        the session can't actually drive an agent loop and shouldn't
        show up in pickers.

        Tests that exercise picker/forwarding behavior without going
        through the real bind flow can set
        :attr:`_attachable_override` to True to flag a hand-wired
        session as attachable. Production paths leave it at the
        default (``None`` → derived from ``_ref`` + ``_agent_completed``).
        """
        if self._attachable_override is not None:
            return self._attachable_override
        return self._ref is not None and not self._agent_completed

    def maybe_bind(self, channel: "AgentChannel", ref: "AgentRef") -> bool:
        """Accept the (channel, ref) pair as the active producer target if none is bound.

        Returns True iff this call became the binder. Subsequent
        :meth:`maybe_bind` calls return False until :meth:`unbind` clears
        the slot — this is what makes ACP attach to the top-level react()
        only: a nested sub-agent's bind attempt sees the outer's ref still
        present and is rejected.

        On accept, also subscribes to ``channel.subscribe_drained`` so
        the transport learns when its queued :class:`UserMessage` items
        reach the consumer. This is what lets ``interrupt_pending``
        clear correctly when an operator submits BEFORE pressing Esc:
        the channel drains the queued message inside ``after_cancel``,
        the subscription fires, and the coordinator's pending flag
        flips False — observable to the TUI's modal-prompt UI and
        Inspect-aware ACP clients.
        """
        if self._ref is None:
            self._ref = ref
            self._unsubscribe_drained = channel.subscribe_drained(
                self._on_channel_drained
            )
            # Mark the channel "live" iff an ACP server is up and
            # accepting external connections — i.e. iff ``--acp-server``
            # is enabled for this eval. Local import to avoid a
            # module-load cycle (transport_live → server → ...).
            from inspect_ai.agent._acp.server import acp_server_accepting_clients

            if acp_server_accepting_clients():
                self._clear_live = channel.mark_live()
            return True
        return False

    def unbind(self, ref: "AgentRef") -> None:
        """Clear the bound ref if it matches ``ref`` (identity).

        Sub-agents whose :meth:`maybe_bind` was rejected get a no-op
        here. The outer react's unbind clears the slot, so a successor
        react in the same sample can rebind. Also drops the channel
        drain subscription registered in :meth:`maybe_bind`.
        """
        if self._ref is ref:
            self._ref = None
            if self._unsubscribe_drained is not None:
                self._unsubscribe_drained()
                self._unsubscribe_drained = None
            if self._clear_live is not None:
                self._clear_live()
                self._clear_live = None

    def _on_channel_drained(self, items: list[Any]) -> None:
        """Callback fired by the channel after a non-empty drain.

        Resolves a pending interrupt iff the drained items include a
        :class:`UserMessage` — the operator's redirect message reached
        the consumer, so the TUI/client modal-prompt indicator should
        clear. Non-UserMessage drains (e.g. a bare ``Cancel`` item) are
        ignored.
        """
        from inspect_ai.agent._channel import UserMessage as _ChannelUserMessage

        if any(isinstance(it, _ChannelUserMessage) for it in items):
            self._interrupt.resolve_if_pending()

    async def __aenter__(self) -> AcpTransport:
        """Enter the session scope; attach the event router and return ``self``.

        Also registers ``self`` on the current :class:`ActiveSample`
        (if any) so out-of-task consumers like the in-process Inspect
        TUI can locate the live session by sample reference.

        Hard contract: never propagates to the agent loop. Each setup
        step is independently guarded so a partial failure logs a
        warning and the session still becomes usable (just with the
        failed feature degraded). Worst case: the session is an
        effectively-inert object that still satisfies the context
        manager protocol and doesn't crash the eval.
        """
        from inspect_ai.agent._acp.event_mapping import _AcpEventRouter
        from inspect_ai.log._samples import sample_active

        with acp_guard(
            "ACP session: transcript capture failed; events will not be "
            "forwarded for this sample"
        ):
            self._transcript_capture.capture()
        with acp_guard(
            "ACP session: event router attach failed; events will not be "
            "forwarded for this sample"
        ) as g:
            self._router = _AcpEventRouter(self)
            self._router.attach()
        if g.failed:
            self._router = None
        with acp_guard(
            "ACP session: ActiveSample registration failed; in-proc TUI "
            "will not see this session"
        ):
            active = sample_active()
            if active is not None:
                prev = active.acp_transport
                # Predecessor handoff: when a solver runs two agents
                # consecutively in the same sample, the first agent's
                # ``__aexit__`` parks its session awaiting ``active_sample``
                # to finalize it. Without this finalize the predecessor
                # would be orphaned — router still attached, pubsub still
                # open with subscribers, no path to clean it up. Hand
                # over cleanly: detach the predecessor's router, close
                # its pubsub (clients bound to its sessionId see EOF +
                # ``inspect/session_ended``), then bind ourselves.
                # ``finalize()`` is idempotent so this is safe even if
                # the predecessor was already finalized via some other
                # path. Nested sub-agents route through ``NoOpAcpTransport``
                # (the factory's shadow rule), never reaching this code.
                #
                # The ``isinstance(prev, LiveAcpTransport)`` does double
                # duty: it narrows the type for mypy (``finalize`` is on
                # ``LiveAcpTransport``, not the ``AcpTransport`` Protocol) and
                # acts as a runtime sanity check. Per the shadow rule
                # above, a non-self ``prev`` is always a ``LiveAcpTransport``
                # in practice — but we never want a registration that
                # silently broke the invariant to crash an eval here.
                if (
                    prev is not None
                    and prev is not self
                    and isinstance(prev, LiveAcpTransport)
                ):
                    await prev.finalize()
                active.acp_transport = self
                # Install ourselves as the sample's execution observer.
                # The model/tool layers (`_call_tools.py`, `_model.py`)
                # consult `sample.execution_observer.track_*` to record
                # in-flight tool/model events; ACP needs that data to
                # populate `InterruptEvent` and clear `pending=True` on
                # cancelled events. Cleared back to the null default in
                # :meth:`finalize` under the same identity guard.
                active.execution_observer = self
                # Register lifecycle hooks the eval primitive will fire:
                # ``on_complete`` drives the deferred teardown after
                # scoring + logging finish; ``on_interrupt`` clears the
                # in-flight ``ModelEvent.pending=True`` (and other turn
                # state) before the task-group hard cancel propagates,
                # so the TUI's assistant chip stops spinning past the
                # scoring chips. Both are cleared in :meth:`finalize`
                # under the same ``is self`` identity guard.
                active.on_complete = self.finalize
                active.on_interrupt = self.cancel_current_turn
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the agent-scope ``async with``; behavior depends on binding.

        Two branches:

        - **Bound to an ActiveSample** (the normal eval-time path): enter
          a "post-agent" state. The agent's react loop has returned but
          the task runner's scoring + logging block is about to run, and
          we want events from that phase (notably ``ScoreEvent``s) to
          reach attached ACP clients. Keep the router + pubsub +
          ``ActiveSample.acp_transport`` binding alive; clear only the
          per-turn subscriber registries that would be unsafe to keep
          (interrupt coordinator, approver clients) since the agent loop
          is no longer running to drain them. The eventual full teardown
          runs from :meth:`finalize`, invoked by
          ``active_sample().__aexit__`` after the sample is fully done.
        - **Unbound** (test code that constructs ``LiveAcpTransport()``
          directly without an ActiveSample): full immediate teardown, the
          original single-phase behavior.

        Hard contract: never propagates a teardown failure to the
        agent loop (which would mask the original exception when the
        session body raised). Each cleanup step is independently
        guarded so one failure doesn't skip the remaining cleanup.
        """
        from inspect_ai.log._samples import sample_active

        active = sample_active()
        bound = active is not None and active.acp_transport is self
        if bound:
            # Split-phase: park the session for the scoring window.
            self._agent_completed = True
            # The interrupt coordinator and approver-client registry only
            # make sense while the agent loop is running; drop their
            # subscribers / clients so a late listener can't fire into a
            # closed context post-agent. Router + pubsub stay attached
            # so scoring events still flow.
            with acp_guard("ACP session: interrupt clear_subscribers failed"):
                self._interrupt.clear_subscribers()
            with acp_guard("ACP session: client registries clear failed"):
                self._clients.clear()
            return

        # Unbound — full immediate teardown. Reached in two cases:
        # 1. Tests construct ``LiveAcpTransport()`` directly without an
        #    enclosing ``active_sample()`` context.
        # 2. Production: the ``acp_guard("ACP session: ActiveSample
        #    registration failed")`` block in ``__aenter__`` caught an
        #    exception, so ``active.acp_transport`` was never assigned and
        #    ``bound`` is False. Without this branch a registration
        #    failure would leak the router + pubsub for the rest of the
        #    sample's lifetime (the registration-driven ``on_complete``
        #    hook also never fired, so ``active_sample().__aexit__``
        #    can't finalize us either).
        if self._router is not None:
            with acp_guard("ACP session: router detach failed"):
                self._router.detach()
            self._router = None
        with acp_guard("ACP session: pubsub close_all failed"):
            self._pubsub.close_all()
        # Drop interrupt-coordination subscribers so a late listener
        # (TUI widget unmount race, connection-handler unbind race)
        # doesn't end up holding a callback that fires into a closed
        # context. Drop approver-client registrations for the same
        # reason — a late-arriving approval prompt after session exit
        # would otherwise try to call into a closed connection.
        with acp_guard("ACP session: interrupt clear_subscribers failed"):
            self._interrupt.clear_subscribers()
        with acp_guard("ACP session: client registries clear failed"):
            self._clients.clear()

    async def finalize(self) -> None:
        """Deferred teardown for split-phase exit. Idempotent.

        Called from ``active_sample().__aexit__`` after scoring + logging
        finishes (intrinsic to ActiveSample lifetime — runs strictly
        after everything inside the body, including ``emit_sample_end``).
        Also called from :meth:`__aenter__` of a successor session when
        two agents run consecutively in the same sample.

        Ordering matters: detach the router first so no further
        notifications get published, then close pubsub. The per-connection
        semantic forwarder sees ``EndOfStream`` on its attach() receive
        stream — which is what triggers the existing
        ``inspect/session_ended`` emission downstream.
        """
        from inspect_ai.log._samples import sample_active

        if self._finalized:
            return
        self._finalized = True
        if self._router is not None:
            with acp_guard("ACP session: router detach failed"):
                self._router.detach()
            self._router = None
        with acp_guard("ACP session: pubsub close_all failed"):
            self._pubsub.close_all()
        with acp_guard("ACP session: ActiveSample deregistration failed"):
            active = sample_active()
            # `is self` identity guard: don't clear someone else's
            # registration if a successor session has already taken over.
            if active is not None and active.acp_transport is self:
                active.acp_transport = None
                active.on_complete = None
                active.on_interrupt = None
                # Restore the null observer; subsequent track_* calls on
                # the (now winding-down) sample are no-ops.
                from inspect_ai.agent._channel import null_execution_observer

                active.execution_observer = null_execution_observer()

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

    def submit_user_message(self, msg: ChatMessageUser) -> None:
        """Forward ``msg`` to the bound :class:`AgentChannel` as a producer.

        Normalizes provenance: any message submitted through this API
        is treated as operator-injected, so ``source`` is set to
        ``"operator"`` if it isn't already. If an interrupt is pending
        (``cancel_current_turn`` fired and wasn't yet resolved), clears
        the pending flag and notifies prompt-resolved subscribers — the
        in-proc TUI's modal prompt mode and Inspect-aware ACP clients
        use this to dismiss their prompt UI when a sibling client
        provides the resumption text.

        Hard contract: never propagates to the caller. The TUI Send
        button or a wire ``session/prompt`` can land any time, including
        after the agent has parked; failure here is logged but the
        message is dropped silently rather than crashing the connection
        handler (or the TUI input handler) that called us. Likewise,
        messages submitted with no channel bound are silently dropped
        (no consumer to receive them).
        """
        if self._agent_completed:
            return
        with acp_guard("ACP submit_user_message raised; message dropped"):
            if msg.source != "operator":
                msg = msg.model_copy(update={"source": "operator"})
            self._interrupt.resolve_if_pending()
            if self._ref is not None:
                from inspect_ai.agent._channel import UserMessage as _ChannelUserMessage

                self._ref.post(_ChannelUserMessage(message=msg))

    @property
    def interrupt_pending(self) -> bool:
        """True between ``cancel_current_turn`` and the next ``submit_user_message``."""
        return self._interrupt.pending

    @property
    def agent_completed(self) -> bool:
        """True after ``__aexit__`` parked the session for scoring."""
        return self._agent_completed

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

        Returns an idempotent unsubscribe callable. Each
        ``ConnectionHandler`` is its own approver-client instance
        (passed as ``self`` to ``Forwarders``), so the same client
        object attaching twice does not occur in practice and is
        NOT supported: ``notify_approver_attach`` would only
        promote one of the pending entries to ready, and the
        ``driver_chain`` filter (``c is not driver``) does not
        distinguish duplicate references to the same client.

        On internal error, logs a warning and returns a no-op
        unsubscribe so the caller still gets a callable to invoke at
        teardown.

        Network-reachable: a ``Forwarders.start`` chain runs on every
        binding, including those that complete during the scoring
        window. The approver registry was cleared at park time and
        approvals don't make sense during scoring — hand back a no-op
        unsubscribe so the connection-side teardown stays uniform.
        """
        if self._agent_completed:
            return lambda: None
        with acp_guard(
            "ACP attach_approver_client raised; approval routing disabled "
            "for this client"
        ):
            return self._clients.approvers.attach(client)
        return lambda: None

    def has_approver_clients(self) -> bool:
        """True if at least one approver client is currently attached.

        On internal error, logs a warning and returns False so the
        approval shim falls back to the in-proc panel rather than
        attempting a doomed ACP route.
        """
        with acp_guard(
            "ACP has_approver_clients raised; falling back to in-proc approval"
        ):
            return self._clients.approvers.has_clients()
        return False

    def has_ever_had_approver_client(self) -> bool:
        """True if any approver client has attached during this session.

        One-way: flips True on first attach and never resets. Lets
        the approval shim distinguish "no operator ever connected"
        (panel-fallback territory) from "operator attached then
        disconnected mid-approval" (park-and-wait territory).

        On internal error, logs a warning and returns False so the
        approval shim conservatively falls back to in-proc rather
        than parking forever in the wait-for-attach loop.
        """
        with acp_guard(
            "ACP has_ever_had_approver_client raised; falling back to in-proc approval"
        ):
            return self._clients.approvers.has_ever_attached()
        return False

    def subscribe_approver_attach(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register ``callback`` to fire on every approver-client attach.

        Used by :func:`_request_from_driver_with_fallback` to park
        until a fresh client shows up after the current driver chain
        exhausts (operator switched away mid-approval). Mirrors
        :meth:`subscribe_interrupted`.

        Returns an idempotent unsubscribe callable. On internal error,
        logs a warning and returns a no-op unsubscribe so the caller
        still gets a callable to invoke in its ``finally`` block.
        """
        with acp_guard(
            "ACP subscribe_approver_attach raised; attach notifications disabled"
        ):
            return self._clients.approvers.subscribe_attach(callback)
        return lambda: None

    def notify_approver_attach(self, client: ApproverClient) -> None:
        """Promote ``client`` from pending to ready and fire subscribers.

        Decoupled from :meth:`attach_approver_client` (which runs
        inside ``Forwarders.start`` BEFORE replay and only registers
        the client as PENDING — invisible to
        :meth:`approver_driver_chain`). The connection handler
        invokes this from ``_post_bind_setup_locked`` after replay
        completes AND after :meth:`mark_active_session_client`
        promotes the connection.

        Only the named client is promoted. A second connection that
        is concurrently mid-bind stays pending until its own bind
        sequence calls ``notify_approver_attach`` for itself — the
        approval shim never dispatches into a half-bound sibling.

        On internal error, logs a warning and continues — a missed
        notification means a parked approval shim doesn't wake on
        this attach, but a subsequent attach (or sample cancel)
        will still unwind it.
        """
        with acp_guard(
            "ACP notify_approver_attach raised; "
            "parked approval shim may miss this attach"
        ):
            self._clients.approvers.notify_attach(client)

    def mark_active_session_client(self, client: object) -> None:
        """Promote ``client`` as active driver across every registry it belongs to.

        Called by the connection handler after it forwards a
        ``session/prompt`` — the strongest signal the client is the
        operator's current surface. The next
        ``session/request_permission`` (and the next
        ``elicitation/create``) will route to this client first; if
        the client has since disconnected, the dispatch shim falls
        through to the next attached client in attach order.

        Fans out across every registry the client belongs to. Each
        registry's :meth:`mark_active` is a no-op when the client
        isn't in its lists, so this is safe to call regardless of
        which registries the connection actually attached to (an
        approver-only client gracefully no-ops in the elicitation
        registry).

        On internal error, logs a warning and continues.
        """
        with acp_guard(
            "ACP mark_active_session_client raised; driver selection unchanged"
        ):
            self._clients.mark_active(client)

    def approver_driver_chain(self) -> list[ApproverClient]:
        """Approver clients in fallback order: driver first, then others.

        The driver is the client whose ``session/prompt`` most
        recently landed (via :meth:`mark_active_session_client`);
        when no prompt has been sent yet on this session, the
        fallback is first-attached. Subsequent entries are the
        remaining attached clients in attach order — the approval
        shim tries each in turn if the driver's request raises (typ.
        ``ConnectionError`` on mid-prompt disconnect).

        Returns a snapshot copy so iteration is stable against
        concurrent attach / detach. On internal error, returns an
        empty list — caller falls back to in-proc approval.
        """
        with acp_guard(
            "ACP approver_driver_chain raised; falling back to in-proc approval"
        ):
            return self._clients.approvers.driver_chain()
        return []

    def attach_elicitation_client(
        self, client: ElicitationClient
    ) -> Callable[[], None]:
        """Register ``client`` as a recipient for elicitation prompts.

        Same idempotent unsubscribe semantics as
        :meth:`attach_approver_client`. The connection handler gates
        this call on the client's advertised ``elicitation.form``
        capability — clients without that capability never attach
        here.
        """
        if self._agent_completed:
            return lambda: None
        with acp_guard(
            "ACP attach_elicitation_client raised; elicitation routing disabled "
            "for this client"
        ):
            return self._clients.elicitations.attach(client)
        return lambda: None

    def has_elicitation_clients(self) -> bool:
        """True if at least one elicitation client is currently attached."""
        with acp_guard(
            "ACP has_elicitation_clients raised; falling back to in-proc panel"
        ):
            return self._clients.elicitations.has_clients()
        return False

    def has_ever_had_elicitation_client(self) -> bool:
        """True if any elicitation client has attached during this session."""
        with acp_guard(
            "ACP has_ever_had_elicitation_client raised; falling back to in-proc panel"
        ):
            return self._clients.elicitations.has_ever_attached()
        return False

    def subscribe_elicitation_attach(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register ``callback`` to fire on every elicitation-client attach."""
        with acp_guard(
            "ACP subscribe_elicitation_attach raised; attach notifications disabled"
        ):
            return self._clients.elicitations.subscribe_attach(callback)
        return lambda: None

    def notify_elicitation_attach(self, client: ElicitationClient) -> None:
        """Promote ``client`` from pending to ready and fire elicitation subscribers."""
        with acp_guard(
            "ACP notify_elicitation_attach raised; "
            "parked elicitation shim may miss this attach"
        ):
            self._clients.elicitations.notify_attach(client)

    def elicitation_driver_chain(self) -> list[ElicitationClient]:
        """Elicitation clients in fallback order: driver first, then others.

        Same semantics as :meth:`approver_driver_chain`. On internal
        error, returns an empty list — caller falls back to in-proc
        panel / console.
        """
        with acp_guard(
            "ACP elicitation_driver_chain raised; falling back to in-proc panel"
        ):
            return self._clients.elicitations.driver_chain()
        return []

    def cancel_current_turn(
        self,
        cause: Literal["user_cancel", "limit", "system"] = "user_cancel",
    ) -> None:
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

        ``cause`` populates :attr:`InterruptEvent.source` so the
        transcript records what actually triggered the cancel. The
        default ``"user_cancel"`` covers wire ``session/cancel`` and
        TUI Esc; ``"limit"`` is passed by
        ``ActiveSample.limit_exceeded`` (token / time / cost / message
        limits); ``"system"`` is reserved for eval-shutdown paths.

        Network-reachable: a wire ``session/cancel``, a TUI Esc, or
        the ``on_interrupt`` hook fired from ``sample.interrupt()`` /
        ``sample.limit_exceeded()`` can land at any time, including
        after park. Silently drop — there's no turn scope to cancel
        and no agent loop to re-engage.
        """
        if self._agent_completed:
            return
        # Hard contract: never propagate an exception to the caller.
        # Called from sibling tasks (TUI button, ACP connection
        # handler's ``cancel`` notification) and from the agent task
        # indirectly via ``inspect/cancel_sample``. A bug anywhere
        # below (snapshot mutation, transcript writes that fan out to
        # log writers / hook subscribers, etc.) must degrade to a
        # WARNING log rather than tear down the eval or kill the
        # connection's main loop.
        with acp_guard("ACP cancel_current_turn raised; cancel may be partial"):
            # snapshot_for_cancel mutates the in-flight events (clears
            # pending, sets error/failed) and returns the data we need
            # to populate the InterruptEvent + notify downstream
            # consumers.
            snapshot = self._turn_cancel.snapshot_for_cancel(cause)

            # Deferred import — `inspect_ai.event` circularly
            # references this module via the event union.
            from inspect_ai.event._interrupt import InterruptEvent

            # Append InterruptEvent + the modified in-flight events to
            # the sample's transcript via the captured reference (NOT
            # ``transcript()``). The caller usually runs in a sibling
            # task where the ContextVar would resolve to a default
            # empty Transcript — see the comment on
            # :class:`_TranscriptCapture`. The transcript's
            # per-subscriber loop catches exceptions, but the
            # log-writer slot fires outside that guard — wrap each
            # write defensively so a misbehaving writer doesn't
            # propagate out of this fire-and-forget method.
            tr = self._transcript_capture.transcript()
            with acp_guard("ACP cancel_current_turn: failed to record InterruptEvent"):
                tr._event(
                    InterruptEvent(
                        source=cause,
                        interrupted=snapshot.kind,
                        interrupted_tool_call_id=snapshot.interrupted_tool_call_id,
                        interrupted_model_event_id=snapshot.interrupted_model_event_id,
                    )
                )
            # Notify log writers / hook subscribers about the cleared
            # pending flag — without ``_event_updated``, downstream
            # consumers buffer the original pending event and never
            # see the cancellation.
            for ev in snapshot.cancelled_events:
                with acp_guard(
                    "ACP cancel_current_turn: failed to notify event update"
                ):
                    tr._event_updated(ev)

            # Drive the cancel through the bound channel: the agent's
            # ``with ch.turn_scope():`` raises :exc:`AgentInterrupted`,
            # which react catches, drains, and recovers from.
            if self._ref is not None:
                from inspect_ai.agent._channel import Cancel as _ChannelCancel

                self._ref.interrupt(_ChannelCancel(reason=cause))

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

        Hard contract: ``yield`` always runs even if our bookkeeping
        raises. The wrapped tool call must execute regardless of
        whether ACP tracking succeeds — a tracking bug must NOT abort
        the agent's tool call.
        """
        with acp_guard(
            "ACP track_tool_call: register failed; continuing without tracking"
        ):
            self._turn_cancel._in_flight_tool_calls.append(tool_call_id)
            if event is not None:
                self._turn_cancel._in_flight_tool_events[tool_call_id] = event
        try:
            yield
        finally:
            with acp_guard(
                "ACP track_tool_call: cleanup failed; in-flight list may be stale"
            ):
                try:
                    self._turn_cancel._in_flight_tool_calls.remove(tool_call_id)
                except ValueError:
                    pass
                self._turn_cancel._in_flight_tool_events.pop(tool_call_id, None)

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

        Hard contract: ``yield`` always runs even if our bookkeeping
        raises. The wrapped model generation must execute regardless
        of whether ACP tracking succeeds.
        """
        prev = self._turn_cancel._active_model_event
        with acp_guard(
            "ACP track_model_event: register failed; continuing without tracking"
        ):
            self._turn_cancel._active_model_event = event
        try:
            yield
        finally:
            with acp_guard(
                "ACP track_model_event: restore failed; active event may be stale"
            ):
                self._turn_cancel._active_model_event = prev
