"""Agent Client Protocol transport foundation.

This module defines the ACP transport contract — the ``AcpTransport``
:class:`typing.Protocol` plus the supporting ``ApproverClient``
Protocol and the ``acp_session()`` / ``current_acp_transport()``
factory + accessor. The two implementations live in sibling files:

- :mod:`.transport_noop` — :class:`NoOpAcpTransport`, the null object
  used as the default ContextVar value and as the shadow installed
  when ``acp_session()`` is opened inside an already-active session
  (sub-agent case).
- :mod:`.transport_live` — :class:`LiveAcpTransport`, the active
  implementation. Owns the in-process pub/sub bus, approver registry,
  transcript snapshot, and in-flight tracking. Acts as a *producer* on
  the agent's :class:`~inspect_ai.agent.AgentChannel`:
  ``submit_user_message`` forwards via ``ref.post``,
  ``cancel_current_turn`` via ``ref.interrupt``.
"""

from __future__ import annotations

import contextlib
import math
from contextvars import ContextVar
from dataclasses import dataclass
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Callable,
    Literal,
    Protocol,
    Sequence,
    runtime_checkable,
)

from anyio.streams.memory import MemoryObjectReceiveStream

from inspect_ai.model._chat_message import ChatMessageUser

if TYPE_CHECKING:
    from acp.schema import (
        AcceptElicitationResponse,
        CancelElicitationResponse,
        DeclineElicitationResponse,
        ElicitationSchema,
        RequestPermissionRequest,
        RequestPermissionResponse,
    )

    from inspect_ai.agent._channel import AgentChannel, AgentRef
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.event._tool import ToolEvent

    ElicitationResponse = (
        AcceptElicitationResponse
        | DeclineElicitationResponse
        | CancelElicitationResponse
    )


@dataclass(frozen=True)
class ElicitationRequest:
    """All fields the standard ACP ``elicitation/create`` wire payload needs.

    The installed ``acp.schema`` (0.10) splits these across two
    Pydantic types — ``CreateFormElicitationRequest`` carries
    ``message`` + ``mode``; ``ElicitationFormSessionMode`` carries
    ``sessionId`` + ``toolCallId`` + ``requestedSchema`` — but on the
    wire it's one flat object. This Inspect-side container carries the
    full set so ``ConnectionHandler.request_elicitation`` can perform
    target-session validation, ``wire_session_id`` rewriting, and emit
    the standard ACP wire shape in one place. No protocol divergence:
    the wire JSON we serialize is spec-conformant ``elicitation/create``
    that any compliant 0.10 client renders.
    """

    message: str
    session_id: str
    requested_schema: "ElicitationSchema"
    tool_call_id: str | None = None


# Loose heterogeneous payload — early tests publish dicts; the live
# router publishes ``acp.SessionNotification`` Pydantic instances. The
# bus does not narrow; subscribers narrow with ``isinstance`` as needed.
AcpUpdate = Any

# Unbounded subscriber buffer (matches the hooks-system pattern at
# ``hooks/_hooks.py:697``). Dropping ACP updates would manifest as
# missing events in client UIs (gaps in transcripts, missing tool-call
# rows, lost interrupt notifications), which is worse than the bounded
# growth risk — subscribers whose receive halves are closed are pruned
# from the fan-out list on the next publish via ``BrokenResourceError``,
# and a runaway subscriber would be capped in practice by the agent's
# event rate over a sample's duration.
_SUBSCRIBER_BUFFER_SIZE: float = math.inf

# Sentinel session_id for the no-op variant so callers never need
# isinstance guards.
_NOOP_SESSION_ID = "noop"


@runtime_checkable
class ApproverClient(Protocol):
    """A client capable of handling ``session/request_permission``.

    An attached ACP client that can render an approval prompt for the
    user and return their decision. ``LiveAcpTransport`` keeps a registry
    of these so the ``human_approver`` can route tool-approval prompts
    through ACP when at least one client is attached, falling back to
    the in-proc panel / console flow when none are.

    Implementations: ``ConnectionHandler`` in ``connection.py`` (wraps
    ``conn.send_request("session/request_permission", ...)``); tests
    pass small stubs to exercise the driver-fallback semantics
    without a real socket.
    """

    async def request_permission(
        self, request: "RequestPermissionRequest"
    ) -> "RequestPermissionResponse":
        """Send the request to the underlying client and await the response.

        Raises (typically :class:`ConnectionError`) if the client
        disconnected before responding — the driver-fallback loop in
        ``approval/_human/acp.py`` treats that as a fallback signal
        and tries the next client in the chain.
        """
        ...

    async def drain_notifications(self) -> None:
        """Wait until pending ``session/update`` notifications have been sent.

        Called by the approval shim immediately before
        :meth:`request_permission` so the operator sees the model's
        accompanying ``agent_message_chunk`` (the "why" the agent
        gave) BEFORE the approval card appears. Without this
        barrier, the request can race the bus-buffered notifications
        to the wire: the request goes via ``conn.send_request``
        directly on the calling task, while notifications flow
        through the per-connection forwarder task that drains the
        in-process pub/sub bus — and the request can win the race,
        leaving the operator deciding with no model-narration
        context visible.

        Implementations must return promptly when there's nothing
        to drain (forwarder caught up, or no forwarder running).
        Stubs in tests can no-op. Cancellation propagates.
        """
        ...


@runtime_checkable
class ElicitationClient(Protocol):
    """A client capable of handling ``elicitation/create``.

    An attached ACP client that can render a structured-form request
    (``ask_user``) to the user and return their submission. The
    Phase 6 ``acp_handler`` routes elicitation prompts through ACP
    when at least one client is attached AND that client advertised
    the ``elicitation.form`` capability during ``initialize``,
    falling back to the in-proc panel / console flow otherwise.

    Implementations: ``ConnectionHandler`` in ``connection.py`` (wraps
    ``conn.send_request("elicitation/create", ...)``); tests pass
    small stubs to exercise the driver-fallback semantics without a
    real socket.
    """

    async def request_elicitation(
        self, request: ElicitationRequest
    ) -> "ElicitationResponse":
        """Send the elicitation request and await the response.

        Raises (typically :class:`ConnectionError`) if the client
        disconnected before responding — the driver-fallback loop in
        ``_input/acp.py`` treats that as a fallback signal and tries
        the next client in the chain. Also raises if the implementation
        is bound to a target session other than ``request.session_id``;
        the shim treats that the same way (try the next client).
        """
        ...

    async def drain_notifications(self) -> None:
        """Wait until pending ``session/update`` notifications have been sent.

        Called by the elicitation shim immediately before
        :meth:`request_elicitation` so the operator sees the model's
        accompanying ``agent_message_chunk`` (the contextual "why"
        the agent is asking) BEFORE the form appears. Same rationale
        as :meth:`ApproverClient.drain_notifications`.

        Implementations must return promptly when there's nothing to
        drain. Stubs in tests can no-op. Cancellation propagates.
        """
        ...


@runtime_checkable
class AcpTransport(Protocol):
    """Per-sample ACP transport facade.

    Owns the ACP-specific machinery the wire protocol needs:
    in-process pub/sub bus, approver-client registry, transcript
    capture/replay, and the producer-side hooks that drive the agent's
    :class:`~inspect_ai.agent.AgentChannel` (``submit_user_message`` →
    ``ref.post``, ``cancel_current_turn`` → ``ref.interrupt``). The
    cancellation primitive lives on the channel; this transport is one
    *producer* on it.
    """

    @property
    def session_id(self) -> str:
        """Opaque identifier for this session.

        Stable for the lifetime of a live session; returns the sentinel
        ``"noop"`` for the no-op variant so callers never need
        ``isinstance`` guards before logging or correlating.
        """
        ...

    async def __aenter__(self) -> "AcpTransport":
        """Enter the session scope.

        Returns ``self``. The session is installed in the ACP
        ContextVar by the ``acp_session()`` factory immediately before
        this is called; consumers can call :func:`current_acp_transport`
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

    def submit_user_message(self, msg: ChatMessageUser) -> None:
        """Queue a user message for the next turn or after-cancel drain.

        Called by transports (TUI, sockets) when an ACP client sends
        ``session/prompt``.
        """
        ...

    def cancel_current_turn(
        self,
        cause: Literal["user_cancel", "limit", "system"] = "user_cancel",
    ) -> None:
        """Cancel the current turn and record an :class:`InterruptEvent`.

        Snapshots :data:`_active_model_event` and the current
        in-flight tool calls (via :meth:`track_tool_call`) to populate
        the event's ``interrupted`` / id fields. Fire-and-forget — never
        raises on the caller's side.

        ``cause`` populates :attr:`InterruptEvent.source` AND the
        per-event cancel sentinel (``ModelEvent.error`` /
        ``ToolCallError.message``) so provenance is consistent across
        the sample-level interrupt record and the in-flight events it
        terminates. Default ``"user_cancel"`` covers wire
        ``session/cancel`` and TUI Esc; ``"limit"`` is the sample-level
        limit path (token / time / cost / messages); ``"system"`` is
        reserved for eval-shutdown paths.
        """
        ...

    def subscribe_transcript_events(
        self, callback: Callable[[Any], None]
    ) -> Callable[[], None]:
        """Register a sync callback fired on every transcript event.

        Used by the raw-event forwarder to stream Inspect-native
        events out to opt-in clients. Wraps the underlying
        ``Transcript._subscribe`` so callers don't reach into private
        session state. Returns an idempotent unsubscribe
        callable (calling it removes the subscriber; safe to call
        multiple times).

        The callback fires in the producer's task context, BEFORE the
        log writer's attachment-extraction step — so consumers see
        events with their full inline payloads.

        Subscribers on the no-op session are silently dropped — the
        returned unsubscribe callable is a no-op.
        """
        ...

    def transcript_events_snapshot(self) -> Sequence[Any]:
        """Snapshot the captured transcript's event list.

        Used by the replay-on-attach path to push recent transcript
        history to a late-joining client before live
        forwarding starts. Returns an empty sequence for the no-op
        session (nothing to replay).
        """
        ...

    @property
    def interrupt_pending(self) -> bool:
        """True while an interrupt is open and not yet resolved.

        Set by :meth:`cancel_current_turn`; cleared by the next
        :meth:`submit_user_message`. Modal-prompt clients observe
        this via :meth:`subscribe_interrupted` /
        :meth:`subscribe_prompt_resolved`.
        """
        ...

    @property
    def agent_completed(self) -> bool:
        """True after the agent's react loop has exited (split-phase park).

        ``LiveAcpTransport.__aexit__`` parks the session for the scoring
        window when bound to an ``ActiveSample`` — the router + pubsub
        stay attached so scoring events still reach clients, but the
        agent loop is gone. Connection handlers read this to reject
        late ``session/prompt`` requests (no consumer to drain the
        queue) and the TUI uses it to disable the composer during
        scoring. False for unbound sessions; the NoOp session is
        always False since it has no lifecycle.
        """
        ...

    def subscribe_interrupted(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback fired on every :meth:`cancel_current_turn`.

        Used by modal-prompt clients (in-proc TUI; Inspect-aware ACP
        clients via the connection handler's
        ``inspect/prompt_resolved`` wiring) to auto-enter prompt
        mode regardless of who triggered the cancel. Returns an
        idempotent unsubscribe callable. No-op session returns a
        no-op unsubscribe.
        """
        ...

    def subscribe_prompt_resolved(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback fired when an open interrupt is resolved.

        Fires when :meth:`submit_user_message` lands while
        :attr:`interrupt_pending` is True. Used by modal-prompt
        clients to auto-exit their prompt UI when a sibling client
        provides the resumption text. Returns an idempotent
        unsubscribe callable. No-op session returns a no-op
        unsubscribe.
        """
        ...

    def attach_approver_client(self, client: ApproverClient) -> Callable[[], None]:
        """Register an ACP client capable of handling approval prompts.

        When the configured ``human_approver`` is reached and at least
        one client is attached, the approval prompt is routed via ACP
        ``session/request_permission`` to a single driver (the client
        whose ``session/prompt`` most recently landed, or
        first-attached when no prompt has been sent on this session).
        Other attached clients observe via the normal event stream
        and don't receive the request. When no clients are attached,
        the existing in-proc panel / console flow runs unchanged.

        Returns an idempotent unsubscribe callable. No-op session
        returns a no-op unsubscribe (no clients can attach).

        Attaching the same client object twice is not supported —
        each connection is its own approver-client instance.
        """
        ...

    def has_approver_clients(self) -> bool:
        """True if at least one :class:`ApproverClient` is currently attached.

        Cheap predicate used by the human-approver to decide whether
        to route via ACP. No-op session always returns False.
        """
        ...

    def has_ever_had_approver_client(self) -> bool:
        """True if any approver client has attached during this session.

        One-way bit: flips True on first attach and never resets.
        Used by the approval shim to distinguish "no operator ever
        connected" from "operator attached then disconnected
        mid-approval". No-op session always returns False.
        """
        ...

    def subscribe_approver_attach(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register ``callback`` to fire on :meth:`notify_approver_attach`.

        Used by the approval shim to park until a fresh client is
        fully ready after the current driver chain exhausts. Returns
        an idempotent unsubscribe callable. No-op session returns a
        no-op unsubscribe.
        """
        ...

    def notify_approver_attach(self, client: ApproverClient) -> None:
        """Promote ``client`` from pending to ready and fire subscribers.

        Decoupled from :meth:`attach_approver_client` (which runs
        before replay and registers as pending) so subscribers wake
        only after replay completes AND the connection has promoted
        itself via :meth:`mark_active_session_client`. Half-bound
        clients are invisible to :meth:`approver_driver_chain` until
        this notification fires. The connection handler invokes this
        from its post-bind setup. No-op session does nothing.
        """
        ...

    def mark_active_session_client(self, client: object) -> None:
        """Promote ``client`` as the active driver across every registry it belongs to.

        Called by the connection handler after a ``session/prompt``
        forwards to this session — the strongest signal that this
        client is the operator's current surface. The next
        ``session/request_permission`` (and the next
        ``elicitation/create``) will route to this client first; if
        it raises (typically ``ConnectionError`` on mid-prompt
        disconnect), the dispatch shim falls through to the next
        attached client.

        Fans out to every client-driver registry on the session
        (approver, elicitation, future additions). Each registry's
        promotion silently no-ops when the client isn't in its
        lists, so this is safe to call unconditionally. No-op
        session does nothing.
        """
        ...

    def approver_driver_chain(self) -> list[ApproverClient]:
        """Approver clients in fallback order: driver first, then others.

        The driver is the client whose ``session/prompt`` most
        recently landed; subsequent entries are the remaining
        attached clients in attach order. Returns a snapshot copy
        so iteration is stable against concurrent attach/detach.
        """
        ...

    def attach_elicitation_client(
        self, client: "ElicitationClient"
    ) -> Callable[[], None]:
        """Register an ACP client capable of handling ``elicitation/create``.

        Same single-driver-with-fallback semantics as
        :meth:`attach_approver_client`. The connection handler gates
        the call on the client's advertised ``elicitation.form``
        capability; clients without that capability are never
        attached here. Returns an idempotent unsubscribe callable.
        No-op session returns a no-op unsubscribe.
        """
        ...

    def has_elicitation_clients(self) -> bool:
        """True if at least one :class:`ElicitationClient` is currently attached.

        Cheap predicate used by the Phase 6 elicitation shim to
        decide whether to route via ACP. No-op session always
        returns False.
        """
        ...

    def has_ever_had_elicitation_client(self) -> bool:
        """True if any elicitation client has attached during this session.

        One-way bit; same semantics as
        :meth:`has_ever_had_approver_client`.
        """
        ...

    def subscribe_elicitation_attach(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register ``callback`` to fire on :meth:`notify_elicitation_attach`.

        Same semantics as :meth:`subscribe_approver_attach`. No-op
        session returns a no-op unsubscribe.
        """
        ...

    def notify_elicitation_attach(self, client: "ElicitationClient") -> None:
        """Promote ``client`` from pending to ready and fire subscribers.

        Same semantics as :meth:`notify_approver_attach`. The
        connection handler invokes this from its post-bind setup
        when the client advertised elicitation form capability.
        """
        ...

    def elicitation_driver_chain(self) -> list["ElicitationClient"]:
        """Elicitation clients in fallback order: driver first, then others.

        Same semantics as :meth:`approver_driver_chain`.
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

    def maybe_bind(self, channel: "AgentChannel", ref: "AgentRef") -> bool:
        """First-binder-wins channel attachment.

        Called by the agent runtime when it opens a new
        :class:`inspect_ai.agent.AgentChannel` (rebindable per top-level
        :func:`react <inspect_ai.agent.react>` invocation in the sample,
        ignored on nested sub-agent opens). Returns True iff this call
        accepted the binding — the caller uses that to know whether to
        :meth:`unbind` on exit.

        Implementations may use ``channel`` to subscribe to channel
        events (e.g. :meth:`AgentChannel.subscribe_drained` so the
        transport learns when its queued :class:`UserMessage` items
        reach the consumer); ``ref`` is the producer-side handle used
        for posting and interrupting.
        """
        ...

    def unbind(self, ref: "AgentRef") -> None:
        """Clear the bound :class:`AgentRef` if it matches ``ref``.

        Identity match: an :meth:`unbind` call from a sub-agent whose
        :meth:`maybe_bind` was rejected silently no-ops.
        """
        ...

    @property
    def ref(self) -> "AgentRef | None":
        """Currently-bound :class:`AgentRef`, or ``None``.

        Producers (:meth:`submit_user_message`, :meth:`cancel_current_turn`)
        consult this to route into the agent's channel when one is bound.
        """
        ...

    @property
    def is_interactive(self) -> bool:
        """True iff this transport has a bound channel and isn't shutting down.

        The *interactivity* axis: can a client drive the agent turn loop
        (send ``session/prompt``, ``session/cancel``)? Requires a bound
        :class:`~inspect_ai.agent._channel.AgentChannel` (set via
        :meth:`maybe_bind`) and a still-live agent loop.

        Pre-binding window (sample started, agent loop not yet inside
        ``agent_channel()``) and post-agent window (loop exited,
        scoring underway) both return False — the turn loop can't be
        driven. Distinct from :attr:`is_attachable`: a sample running a
        custom solver that never binds a channel is *attachable*
        (observable) but not *interactive*.
        """
        ...

    @property
    def is_attachable(self) -> bool:
        """True iff a client may attach to this transport at all.

        The broad gate: True from ``__aenter__`` until :meth:`finalize`,
        regardless of channel binding — so observe-only clients can
        attach to any running sample (custom solvers, pre-bind window,
        scoring window) and receive its event stream. Drivable
        (interactive) attach additionally requires :attr:`is_interactive`.

        Returns False for the no-op session and after the transport has
        finalized (router detached, sample done).
        """
        ...


# NoOpAcpTransport is imported at module bottom (after the Protocol
# definitions it depends on) to keep the load order coherent: importing
# ``session_noop`` triggers a re-import of this module while it's still
# loading, and that re-import only needs the symbols defined above.
from inspect_ai.agent._acp.transport_noop import NoOpAcpTransport  # noqa: E402

_NOOP_SINGLETON: AcpTransport = NoOpAcpTransport()

_acp_var: ContextVar[AcpTransport] = ContextVar("_acp_session", default=_NOOP_SINGLETON)

# Sticky "a Live session is active somewhere upstream" flag,
# inherited like any ContextVar by spawned child tasks. The first
# ``acp_session()`` entry in a context chain flips this to True; every
# subsequent ``acp_session()`` block in that chain — at any nesting
# depth — sees True and installs a NoOp shadow.
#
# Reading the immediate parent's session shape via ``_acp_var`` is not
# sufficient on its own. A sub-agent installs a NoOp shadow into
# ``_acp_var``, so a sub-sub-agent that consulted the parent alone
# would see a NoOp, conclude "no live session here", and install a
# second Live session — overwriting ``ActiveSample.acp_transport`` and
# double-registering the event router. This separate flag breaks that
# false symmetry.
_acp_live_active: ContextVar[bool] = ContextVar("_acp_live_active", default=False)


@contextlib.asynccontextmanager
async def acp_session() -> AsyncIterator[AcpTransport]:
    """Open an ACP session for the enclosing scope.

    The first ``acp_session()`` entry in a context chain installs a
    real ``LiveAcpTransport``. Every nested ``acp_session()`` block —
    sub-agents invoked via handoff / ``as_tool`` / dispatch, at any
    depth — installs a no-op shadow instead, so nested code can call
    ``current_acp_transport().submit_user_message(...)`` /
    ``cancel_current_turn()`` without accidentally driving the
    top-level session.

    Usage::

        async with acp_session() as acp:
            ...
    """
    if _acp_live_active.get():
        # Upstream already owns the live session — shadow regardless
        # of how deep we are. ``_acp_var`` still gets the shadow so
        # ``current_acp_transport()`` inside this scope returns it
        # rather than leaking the upstream Live one.
        install: AcpTransport = NoOpAcpTransport()
        token_var = _acp_var.set(install)
        try:
            async with install:
                yield install
        finally:
            _acp_var.reset(token_var)
    else:
        # Deferred import: ``session_live`` imports from this module,
        # so importing it at module load would create a fragile cycle.
        # Importing here means the factory is the only path that
        # materializes the live impl; tests that import it directly
        # take care of their own ordering.
        from inspect_ai.agent._acp.transport_live import LiveAcpTransport

        # First entry — become the live session and mark the chain
        # so all descendants shadow.
        install = LiveAcpTransport()
        token_live = _acp_live_active.set(True)
        token_var = _acp_var.set(install)
        try:
            async with install:
                yield install
        finally:
            _acp_var.reset(token_var)
            _acp_live_active.reset(token_live)


def current_acp_transport() -> AcpTransport:
    """Return the currently active ACP session without entering a scope.

    Returns the no-op singleton when no ACP session is active. Safe to
    call from anywhere; never blocks; never raises.

    Resolution order: (1) the ``_acp_var`` ContextVar (set by an
    :func:`acp_session` entry on an ancestor task); (2) the active
    sample's :attr:`ActiveSample.acp_transport` field, if any (lets test
    fixtures attach a session by direct assignment without going through
    the async context manager); (3) the no-op singleton.
    """
    var_session = _acp_var.get()
    if var_session is _NOOP_SINGLETON:
        # Local import to avoid load-order cycle.
        from inspect_ai.log._samples import sample_active

        sample = sample_active()
        if sample is not None and sample.acp_transport is not None:
            return sample.acp_transport
    return var_session
