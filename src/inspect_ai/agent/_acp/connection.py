"""Per-connection ACP method handler.

One :class:`ConnectionHandler` per accepted socket connection.
Implements the ACP ``Agent`` role (``initialize`` / ``new_session`` /
``load_session`` / ``prompt`` / ``cancel``) plus the non-standard
``inspect/*`` action methods. Per-connection state (synthetic control
sessionId, bound target sessionId, picker target snapshot, capability
flags) lives in :class:`ConnectionState` so two concurrent clients can
pick different target sessions independently.

asyncio anchor — this module is **asyncio-bound** at the
``acp.Connection`` boundary. See ``design/acp/agent-acp.md`` "asyncio /
anyio boundary" for the rationale.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal

from acp.connection import Connection
from acp.exceptions import RequestError
from acp.meta import CLIENT_METHODS, PROTOCOL_VERSION
from acp.schema import (
    AcceptElicitationResponse,
    AgentCapabilities,
    AgentMessageChunk,
    CancelElicitationResponse,
    DeclineElicitationResponse,
    Implementation,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PromptResponse,
    RequestPermissionRequest,
    RequestPermissionResponse,
    SessionCapabilities,
    SessionInfoUpdate,
    SessionNotification,
    TextContentBlock,
)
from shortuuid import uuid

from inspect_ai.agent._acp.inspect_ext import (
    INSPECT_CANCEL_SAMPLE_METHOD,
    INSPECT_CANCEL_TOOL_CALL_METHOD,
    INTERACTIVE_META_KEY,
    PICKER_META_KEY,
    build_picker_notification,
    detect_capabilities,
    picker_target_meta_dict,
    sample_listing_meta_dict,
)
from inspect_ai.agent._acp.picker import (
    PickerTarget,
    SampleListing,
    list_all_samples,
    list_picker_targets,
    resolve_selection,
)
from inspect_ai.agent._acp.session_router import Forwarders
from inspect_ai.model._chat_message import ChatMessageUser

if TYPE_CHECKING:
    from inspect_ai.agent._acp.transport import (
        AcpTransport,
        ElicitationRequest,
        ElicitationResponse,
    )
    from inspect_ai.log._samples import ActiveSample

logger = getLogger(__name__)

# Version banner included in InitializeResponse. The eval is the
# server in the ACP relationship.
_AGENT_NAME = "inspect-ai"
_AGENT_VERSION = "0.10"

# JSON-RPC method name for the picker confirmation / target list
# notification sent on `session/update`.
_SESSION_UPDATE_METHOD = CLIENT_METHODS["session_update"]


@dataclass(frozen=True)
class Unbound:
    """Initial connection state — no ``session/new`` or ``session/load`` yet."""


@dataclass(frozen=True)
class PickerMode:
    """Multi-target picker is shown; awaiting client's selection.

    The synthetic ``wire_session_id`` was minted at ``session/new`` and
    is what the client sees as its sessionId. ``picker_targets`` is the
    snapshot taken at picker-push time — numeric selections (``"1"``,
    ``"2"``) resolve against this list, not a fresh enumeration, so a
    sample starting / finishing / reordering between the push and the
    selection prompt doesn't shift the meaning of the indices.
    """

    wire_session_id: str
    picker_targets: list[PickerTarget]


@dataclass(frozen=True)
class Bound:
    """Connection is bound to a target session; forwarding is active.

    ``wire_session_id`` is what the client sees. ``target_session_id``
    is the internal ``LiveAcpTransport.session_id`` we forward to. In
    the auto-bind / direct-load paths these are equal; on the picker
    selection path the wire id is the synthetic control id and the
    target id is the chosen sample — the design contract is that the
    client's sessionId stays stable across a picker rebind.

    ``interactive`` is the bind-time snapshot of the target's
    :attr:`AcpTransport.is_interactive`: True when the bound session had
    a live agent turn loop the client can drive (``session/prompt`` /
    ``session/cancel``), False for an observe-only bind (custom solver
    or other channel-less sample). Fixed for the binding's lifetime —
    if the sample later becomes drivable the client reconnects (see the
    "fixed for v1" decision in ``design/acp/agent-acp.md``).
    """

    wire_session_id: str
    target_session_id: str
    interactive: bool = True


# Tagged union of the connection's binding mode. Replaces three
# independent nullable fields (``wire_session_id``,
# ``target_session_id``, ``picker_targets``) with one variant whose
# valid combinations are typed.
BindingMode = Unbound | PickerMode | Bound


@dataclass
class ConnectionState:
    """Per-connection routing state.

    ``binding`` is a tagged union of :class:`Unbound`,
    :class:`PickerMode`, :class:`Bound`. Dispatch sites use ``match``
    on it so the type system enforces the three legal combinations
    that used to be policed by ad-hoc null checks. Transitions are
    "assign a new variant," not "mutate fields."

    Validation: every incoming ``session/prompt`` and
    ``session/cancel`` must carry the same sessionId as the
    connection's ``wire_session_id`` — mismatches are rejected
    rather than silently re-routed.
    """

    binding: BindingMode = field(default_factory=Unbound)

    # Client-capability flags, decided at initialize() time and frozen
    # for the connection lifetime. The forwarder consults these to
    # decide whether to substitute AgentPlanUpdate for plan-tool
    # notifications and whether to also forward raw transcript events.
    client_renders_plan: bool = False
    # Raw-event subscription: ``None`` means the client did not opt in;
    # otherwise a frozenset of event-type names (possibly including the
    # ``"*"`` glob via :data:`inspect_ext.RAW_EVENTS_GLOB`) the
    # forwarder filters against. Decoded by
    # :func:`inspect_ext.detect_capabilities`.
    raw_events_subscription: frozenset[str] | None = None
    # True if the client advertised ``elicitation.form`` in
    # ``initialize`` (per ACP 0.10+ ``ClientCapabilities.elicitation
    # .form``). Gates whether ``Forwarders.start`` attaches us to the
    # session's elicitation-client registry — clients without this
    # capability never receive ``elicitation/create`` requests.
    client_supports_elicitation_form: bool = False

    @property
    def wire_session_id(self) -> str | None:
        """Convenience accessor: the client-facing sessionId, or None if unbound.

        Returns ``binding.wire_session_id`` when bound or in picker
        mode; ``None`` when unbound. Used by read-only callers
        (forwarders, title-send, replay) so they don't need to ``match``
        on the binding for a single common-case lookup.
        """
        if isinstance(self.binding, (PickerMode, Bound)):
            return self.binding.wire_session_id
        return None


class ConnectionHandler:
    """Per-connection method handler. Plays the ACP ``Agent`` role."""

    def __init__(self) -> None:
        self.connection: Connection | None = None
        self.state = ConnectionState()
        # Per-bind outbound forwarder. ``None`` until the connection
        # binds to a target. Each bind constructs a fresh instance —
        # per-bind state (notably the plan-tool stash) cannot leak
        # across rebinds because the object itself is destroyed.
        self._forwarders: Forwarders | None = None
        # Tasks scheduled via ``_schedule_after_response`` to fire a
        # notification once the in-progress RPC response has been
        # written to the wire. Tracked so they're not garbage-collected
        # before they run and so connection close can cancel them.
        self._pending_after_response: set[asyncio.Task[None]] = set()
        # Bind serialization. ACP dispatches each request as its own
        # asyncio task, so two ``session/new`` / ``session/load`` calls
        # on the same connection can race. The lock serializes the
        # bind sequences (stop old → mutate state → notify → start
        # new) so they can't interleave. Held by bind handlers and by
        # the deferred ``_post_bind_setup``. The ``_bind_generation``
        # int discriminates between binds — a deferred setup compares
        # its captured value against the current counter and no-ops if
        # the bind has been superseded. INVARIANT: no handler awaits
        # anything under the lock that calls back into the deferred
        # setup path, so re-entrant lock acquisition cannot occur.
        self._bind_lock: asyncio.Lock = asyncio.Lock()
        self._bind_generation: int = 0

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

        Also captures client-capability flags (``client_renders_plan``,
        ``raw_events_subscription``, ``client_supports_elicitation_form``)
        so the per-connection forwarder can switch behavior per client.
        """
        # Capture client-capability flags. See ``detect_capabilities``
        # for the allowlist + ``_meta`` opt-in logic.
        (
            self.state.client_renders_plan,
            self.state.raw_events_subscription,
        ) = detect_capabilities(client_info, client_capabilities)

        # Elicitation/form capability — frozen for the connection lifetime.
        # The presence of ``ElicitationFormCapabilities`` (an empty marker
        # type) under ``elicitation.form`` signals the client can render an
        # ``elicitation/create`` form locally and return the user's answer.
        self.state.client_supports_elicitation_form = (
            client_capabilities is not None
            and getattr(client_capabilities, "elicitation", None) is not None
            and getattr(client_capabilities.elicitation, "form", None) is not None
        )

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
        mcp_servers: Any = None,  # unused — we don't host MCP servers
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

        Resolves against *all* attachable samples (not just drivable
        ones), so a client that learned an observe-only sessionId from
        ``inspect/list_samples`` can attach to watch it. The bind records
        whether the target is interactive; write paths gate on it.
        """
        resolved = _resolve_attachable_target_by_id(session_id)
        if resolved is None:
            raise RequestError.invalid_params(
                {
                    "reason": "unknown session_id",
                    "session_id": session_id,
                    "hint": "call session/new for the picker flow",
                }
            )
        match, interactive = resolved
        # On a successful load the wire sessionId IS the target's id
        # (the client passed it in, we matched it, no rebind happens).
        # Binding-confirmation notification, title, and replay events
        # are deferred until after the response writes — same rationale
        # as ``_auto_bind`` (avoid clients dropping updates for a
        # sessionId they haven't yet seen).
        #
        # Hold ``_bind_lock`` while we tear down old forwarders, bump
        # the generation, and assign ``state.binding``. The deferred
        # ``_post_bind_setup`` re-acquires the lock; if another bind
        # ran in between (newer generation), it no-ops cleanly.
        async with self._bind_lock:
            await self._stop_forwarders()
            self._bind_generation += 1
            gen = self._bind_generation
            self.state.binding = Bound(
                wire_session_id=match.session_id,
                target_session_id=match.session_id,
                interactive=interactive,
            )
        self._schedule_after_response(lambda: self._post_bind_setup(match, gen))
        return LoadSessionResponse()

    async def prompt(
        self,
        prompt: list[Any],
        session_id: str,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> PromptResponse:
        """Handle a prompt request. Selection in control mode; forward otherwise."""
        match self.state.binding:
            case Unbound():
                raise RequestError.invalid_request(
                    {
                        "reason": (
                            "session/prompt called before session/new or session/load"
                        )
                    }
                )
            case PickerMode(wire_session_id=wire) | Bound(wire_session_id=wire):
                # Reject if the prompt names a different sessionId than
                # the one this connection is currently keyed to. Blocks
                # cross-session prompts on a misbehaving / confused
                # client.
                if session_id != wire:
                    raise RequestError.invalid_params(
                        {
                            "reason": (
                                "session_id does not match this connection's session"
                            ),
                            "session_id": session_id,
                            "expected": wire,
                        }
                    )

        match self.state.binding:
            case PickerMode():
                # Picker selection — first prompt in control mode
                # resolves to a target and rebinds the connection.
                return await self._handle_picker_selection(prompt)
            case Bound(target_session_id=target_id, interactive=interactive):
                # Observe-only bind: this connection attached to a sample
                # with no agent turn loop to drive (a custom solver, or
                # any sample bound while non-interactive). Interactivity
                # is fixed for the binding's lifetime (the "fixed for v1"
                # decision) — turn-loop input is rejected here regardless
                # of the target's current live state. The client can
                # still observe the stream and issue lifecycle controls
                # (``inspect/cancel_sample`` / ``inspect/cancel_tool_call``).
                if not interactive:
                    raise RequestError.invalid_request(
                        {
                            "reason": (
                                "session is not interactive (no agent turn loop bound)"
                            ),
                            "target_session_id": target_id,
                        }
                    )
                # Bound mode. Forward to the bound target session's
                # submit_user_message. Translates ACP content blocks to
                # a ChatMessageUser; only text blocks are honored fully
                # today (other variants degrade to placeholder text —
                # see ``_translate_prompt_blocks``).
                target = _find_live_session(target_id)
                if target is None:
                    # The underlying ActiveSample finished after we
                    # bound but before this prompt arrived. Surface a
                    # clear error so the client can drop the binding
                    # and reconnect.
                    raise RequestError.internal_error(
                        {
                            "reason": "bound session no longer active",
                            "target_session_id": target_id,
                        }
                    )
                if not target.is_interactive:
                    # The target's transport is alive but has no bound
                    # agent loop to receive this prompt. Two states
                    # collapse here:
                    #
                    # - ``agent_completed`` — react() has exited and
                    #   the transport is parked for the scoring window;
                    # - no bound channel — react() between consecutive
                    #   invocations (the inter-react gap in the same
                    #   sample), or a non-channel custom agent.
                    #
                    # Pre-fix, the message was silently discarded by
                    # ``LiveAcpTransport.submit_user_message``'s
                    # ``_ref is None`` guard. Surface a real error so
                    # the client (TUI / editor) can drop the binding
                    # instead of pretending it landed. Detail the
                    # specific sub-state so clients can render a
                    # tailored message.
                    reason = (
                        "session is scoring"
                        if target.agent_completed
                        else "session not currently attachable"
                    )
                    raise RequestError.invalid_request(
                        {
                            "reason": reason,
                            "target_session_id": target_id,
                        }
                    )
                text = _translate_prompt_blocks(prompt)
                msg = ChatMessageUser(content=text, source="operator")
                target.submit_user_message(msg)
                # Promote ourselves to the active driver across every
                # client registry we belong to (approver, elicitation,
                # future additions) — the operator just typed here, so
                # this is where they're paying attention. Silently
                # no-ops in any registry where we aren't (or no longer
                # are) a registered client. See the registry's
                # docstring for the single-driver semantics.
                target.mark_active_session_client(self)
                return PromptResponse(stop_reason="end_turn")
            case _:
                # Unreachable: the outer match above already raised on
                # Unbound. Kept so mypy sees an exhaustive return.
                raise RequestError.invalid_request(
                    {"reason": "connection in unknown state"}
                )

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        """Forward cancel notifications to the bound target session.

        Notifications can't return errors, so any mismatch (wrong wire
        sessionId, bound target gone, unbound connection) is silently
        dropped — the alternative of routing it through anyway risks
        cross-session interference.
        """
        match self.state.binding:
            case Bound(
                wire_session_id=wire,
                target_session_id=target_id,
                interactive=interactive,
            ):
                if session_id != wire:
                    return None
                if not interactive:
                    # Observe-only bind — session/cancel targets the turn
                    # loop, which this connection can't drive. Fixed for
                    # the binding's lifetime; silently drop (notifications
                    # can't return errors).
                    return None
                target = _find_live_session(target_id)
                if target is None:
                    # Bound target has already finished; nothing to cancel.
                    return None
                if not target.is_interactive:
                    # No bound agent loop right now (post-agent scoring
                    # window, or between consecutive react() invocations
                    # in the same sample). Recording an InterruptEvent
                    # here would falsely suggest an active turn was
                    # interrupted; flipping ``interrupt_pending`` would
                    # leave the TUI / Inspect-aware clients showing a
                    # prompt-mode indicator forever since no agent will
                    # consume the resolution. Notifications can't return
                    # errors, so silently drop.
                    return None
                target.cancel_current_turn()
            case PickerMode() | Unbound():
                # Picker mode or unbound — a cancel here is meaningless;
                # silently drop.
                return None
        return None

    # ------------------------------------------------------------------
    # `inspect/*` action methods (non-standard ACP extension)
    # ------------------------------------------------------------------

    async def inspect_list_sessions(self) -> dict[str, Any]:
        """Enumerate attachable sessions for Inspect-aware clients.

        Returns the same per-target shape that ``session/new``'s picker
        notification carries under ``_meta[PICKER_META_KEY]``, plus a
        convenience ``target`` field with the slash-delimited spec that
        :meth:`inspect_attach` accepts. Clients that already know
        the protocol can use this to skip the round-trip through
        ``session/new`` + picker notification + ``_meta`` parsing.

        No params, no auth, no binding required — discovery is the
        prerequisite for binding. Empty list when no samples have
        claimed an ACP session yet.
        """
        targets = list_picker_targets()
        return {
            "sessions": [
                {
                    **picker_target_meta_dict(t),
                    "target": f"{t.task}/{t.sample_id}/{t.epoch}",
                }
                for t in targets
            ]
        }

    async def inspect_list_samples(self) -> dict[str, Any]:
        """Enumerate ALL active samples — ACP-claimed and not.

        Superset of :meth:`inspect_list_sessions`: includes samples
        whose agent has not claimed ACP (no ``before_turn`` call yet,
        or no ACP-aware scaffold). ACP-claimed entries carry the live
        ``sessionId``; non-claimed entries set ``sessionId`` to
        ``None``. The Inspect TUI consumes this so non-ACP samples
        appear in the picker as dimmed + unselectable-on-attach rows
        — the operator sees "the eval is running but I can't drive it"
        rather than an empty picker.

        Standard ACP clients (Zed et al.) continue to use
        ``inspect/list_sessions`` (or the in-channel picker via
        ``session/new``) which stays filtered to attachable targets.
        """
        listings = list_all_samples()
        return {"samples": [sample_listing_meta_dict(listing) for listing in listings]}

    async def inspect_attach(
        self,
        cwd: str,  # unused but kept for shape parity with session/new
        target: str,
        mcp_servers: Any = None,  # unused — we don't host MCP servers
    ) -> NewSessionResponse:
        """Bind directly to ``target`` without going through the picker.

        ``target`` is a ``task/sample_id/epoch`` slash-delimited string.
        If it matches an active sample, bind immediately (same auto-bind
        path used by ``session/new`` when there's exactly one running
        sample). On miss, raise ``invalid_params`` with the list of
        available targets so the client can show a helpful diagnostic —
        never silently fall through to the picker, which would mask an
        explicit-but-stale ask.

        Resolves against *all* attachable samples (drivable and
        observe-only), so a client can direct-attach to a custom-solver
        sample to watch it. The bind records whether the target is
        interactive.

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
        resolved = _resolve_attachable_target_by_spec(task, sample_id, epoch)
        if resolved is None:
            # Diagnostic lists every attachable sample (drivable or
            # observe-only) so an explicit-but-stale ask gets an accurate
            # "did you mean" set.
            available = [
                f"{listing.task}/{listing.sample_id}/{listing.epoch}"
                for listing in list_all_samples()
                if listing.session_id is not None
            ]
            raise RequestError.invalid_params(
                {
                    "reason": "no active session matches the requested target",
                    "requested": target,
                    "available": available,
                }
            )
        match, interactive = resolved
        return await self._auto_bind(match, interactive=interactive)

    async def cancel_sample(
        self,
        session_id: str,
        action: Literal["score", "error"],
    ) -> dict[str, Any]:
        """Terminate the bound sample via :meth:`ActiveSample.interrupt`.

        ``action`` selects the post-cancel outcome:

        - ``"score"`` — run the scorer on whatever work landed.
        - ``"error"`` — mark the sample errored. Gated to mirror the
          in-proc ``--display full`` TUI's
          ``cancel_with_error.display = not sample.fails_on_error``
          rule: rejected whenever ``ActiveSample.fails_on_error`` is
          ``True`` (which collapses ``True`` / ``None`` /
          fractional / integer-count configs together — the sample
          will surface an error of its own accord, so a manual
          ``error`` action would just race the auto-fail).

        Distinct from ``session/cancel``, which interrupts the current
        turn but lets the agent loop recover. This method is terminal:
        the sample finishes.
        """
        bound = self._require_bound(session_id, INSPECT_CANCEL_SAMPLE_METHOD)
        sample = _find_active_sample(bound.target_session_id)
        if sample is None:
            raise RequestError.internal_error(
                {
                    "reason": "bound sample no longer active",
                    "target_session_id": bound.target_session_id,
                }
            )
        if action == "error" and sample.fails_on_error:
            raise RequestError.invalid_params(
                {
                    "reason": (
                        "action='error' not permitted when sample is "
                        "configured to fail on errors "
                        "(fails_on_error=True — use action='score')"
                    )
                }
            )
        # ``sample.interrupt(action)`` fires the registered
        # ``on_interrupt`` hook before the task-group cancel — for an
        # ACP-bound sample that routes to
        # ``LiveAcpTransport.cancel_current_turn``, which clears
        # in-flight ``ModelEvent.pending=True`` (otherwise anyio's
        # hard cancel bypasses the normal completion paths and the
        # TUI's assistant chip spins past the scoring chips). The
        # coupling lives on ``ActiveSample`` so timeouts and limit
        # exceededs get the same cleanup, not just ACP cancels.
        sample.interrupt(action)
        return {}

    async def cancel_tool_call(
        self,
        session_id: str,
        tool_call_id: str,
    ) -> dict[str, Any]:
        """Cancel a pending tool call by id.

        Walks the full sample transcript for a matching pending
        ``ToolEvent`` (superset of the TUI which only handles top-level
        tools). The found event's ``_cancel_fn`` — set by the tool
        dispatcher at ``_call_tools.py`` — is invoked, triggering the
        per-tool task-group cancel.

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
        propagates upward through the enclosing sub-agent's run — see
        the dedicated integration test for the observed propagation
        contract.
        """
        # Avoid module-level circular import.
        from inspect_ai.event._tool import ToolEvent

        bound = self._require_bound(session_id, INSPECT_CANCEL_TOOL_CALL_METHOD)
        sample = _find_active_sample(bound.target_session_id)
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

    def _require_bound(self, session_id: str, method_name: str) -> Bound:
        """Validate the connection is Bound and the wire sessionId matches.

        Used by ``inspect/*`` action methods that only make sense
        post-bind. Raises ``invalid_request`` if unbound (the connection
        hasn't completed ``session/new`` / ``session/load``), or
        ``invalid_params`` if the client's sessionId doesn't match the
        bound wire id.

        ``method_name`` is woven into the error reason for clearer
        client diagnostics (the method name appears in the message
        rather than a generic "method called before binding").
        """
        if not isinstance(self.state.binding, Bound):
            raise RequestError.invalid_request(
                {
                    "reason": (
                        f"{method_name} called before binding "
                        "(connection has no target session)"
                    )
                }
            )
        bound = self.state.binding
        if session_id != bound.wire_session_id:
            raise RequestError.invalid_params(
                {
                    "reason": "session_id does not match this connection's session",
                    "session_id": session_id,
                    "expected": bound.wire_session_id,
                }
            )
        return bound

    async def _enter_picker_mode(
        self, targets: list[PickerTarget]
    ) -> NewSessionResponse:
        """Mint a control sessionId, snapshot targets, push picker payload.

        Holds ``_bind_lock`` while tearing down any prior bind's
        forwarders + bumping the generation + assigning the picker
        state. The generation bump invalidates any in-flight deferred
        ``_post_bind_setup`` from a previous bind. Without this, a
        connection that auto-bound to a single target, then sees a
        second target appear, then calls newSession again, would keep
        the prior target's forwarder running during picker selection.
        """
        async with self._bind_lock:
            await self._stop_forwarders()
            self._bind_generation += 1
            gen = self._bind_generation
            control_id = uuid()
            # Snapshot the target list so the numeric selection (1, 2,
            # ...) resolves against the exact list the client was shown.
            # A fresh enumeration at selection time could disagree if
            # a sample finished or a new one started in between.
            self.state.binding = PickerMode(
                wire_session_id=control_id, picker_targets=list(targets)
            )
        notif = build_picker_notification(control_id, targets)
        # Defer notification until after the NewSessionResponse has
        # been written to the wire — Zed (and likely other clients)
        # drop session/update notifications for a sessionId they
        # haven't yet seen in a newSession/loadSession response.
        # Guarded by generation so a concurrent bind that landed
        # before this fires drops the now-stale picker payload.
        self._schedule_after_response(
            lambda: self._send_notification_if_current(notif, gen)
        )
        return NewSessionResponse(session_id=control_id)

    async def _auto_bind(
        self, target: PickerTarget, *, interactive: bool = True
    ) -> NewSessionResponse:
        """Skip the picker for the single-target case; bind immediately.

        On the auto-bind path the wire sessionId IS the target's id
        (it's what we hand back in the NewSessionResponse), so the
        client and server agree on the same id.

        ``interactive`` records whether the bound target had a live agent
        turn loop. The ``session/new`` single-target path and picker
        always pass drivable targets (default True); ``inspect/attach``
        passes the resolved flag so observe-only binds are marked.

        The binding-confirmation notification, session_info title, and
        replay-on-attach events all flow as ``session/update`` for
        this sessionId — they're deferred until after the response
        writes so clients (Zed etc.) don't drop them as references to
        a sessionId they don't yet know.

        Holds ``_bind_lock`` while tearing down any prior bind's
        forwarders + bumping the generation + assigning
        ``state.binding``. The captured generation flows to the
        deferred ``_post_bind_setup``, which will no-op if a newer
        bind landed in the meantime.
        """
        async with self._bind_lock:
            await self._stop_forwarders()
            self._bind_generation += 1
            gen = self._bind_generation
            self.state.binding = Bound(
                wire_session_id=target.session_id,
                target_session_id=target.session_id,
                interactive=interactive,
            )
        self._schedule_after_response(lambda: self._post_bind_setup(target, gen))
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
           binding would attach to a sessionId no agent owns; the
           prompt/cancel forwarding would have nowhere to forward.
           Fall through to redisplay in that case.

        On any miss (bad selection OR stale target), we redisplay and
        re-snapshot so the next numeric pick refers to the redisplayed
        list.
        """
        # Caller (``prompt``) guarantees we're in picker mode.
        assert isinstance(self.state.binding, PickerMode)
        picker = self.state.binding
        selection_text = _prompt_text(prompt_blocks)
        target = resolve_selection(selection_text, picker.picker_targets)

        if target is not None:
            # Confirm the resolved target is still live before binding.
            fresh_targets = list_picker_targets()
            still_active = any(t.session_id == target.session_id for t in fresh_targets)
            if not still_active:
                target = None  # Fall through to the redisplay path.

        if target is None:
            # Redisplay with a fresh enumeration. Re-snapshot too so
            # the client's next numeric pick maps onto the new list.
            #
            # Hold ``_bind_lock`` for the state mutation + send so a
            # concurrent ``session/load`` / ``session/new`` can't slip
            # in between (it would tear down the binding we're about
            # to overwrite, leaking forwarders). Bail if a concurrent
            # bind has already taken us out of this picker session —
            # the user's intent has changed; the redisplay is stale.
            async with self._bind_lock:
                if (
                    not isinstance(self.state.binding, PickerMode)
                    or self.state.binding.wire_session_id != picker.wire_session_id
                ):
                    return PromptResponse(stop_reason="end_turn")
                fresh_targets = list_picker_targets()
                self.state.binding = PickerMode(
                    wire_session_id=picker.wire_session_id,
                    picker_targets=list(fresh_targets),
                )
                notif = build_picker_notification(picker.wire_session_id, fresh_targets)
                await self._send_session_update(notif)
            return PromptResponse(stop_reason="end_turn")

        # Rebind: switch to Bound while keeping the wire sessionId.
        # Design contract: client's sessionId is stable across a picker
        # rebind, so all subsequent outbound notifications continue to
        # use wire_session_id.
        #
        # Holds ``_bind_lock`` for the entire rebind + setup sequence.
        # ACP dispatches each request as its own asyncio task, so a
        # concurrent ``session/load`` / ``session/new`` on the same
        # connection could otherwise interleave. The lock serializes
        # the whole tail: stop old → bump gen → assign Bound → notify
        # → start forwarders. ``_post_bind_setup_locked`` is the
        # variant that assumes the lock is already held (the lock-
        # acquiring ``_post_bind_setup`` would deadlock here since
        # ``asyncio.Lock`` is non-reentrant).
        #
        # Same-session check inside the lock: if a concurrent
        # ``session/load`` / ``session/new`` flipped the binding away
        # from this picker session between selection resolution and
        # our lock acquisition, the user's intent has moved on. Bail
        # rather than clobber the newer binding with our stale
        # ``picker.wire_session_id``.
        async with self._bind_lock:
            if (
                not isinstance(self.state.binding, PickerMode)
                or self.state.binding.wire_session_id != picker.wire_session_id
            ):
                return PromptResponse(stop_reason="end_turn")
            await self._stop_forwarders()
            self._bind_generation += 1
            self.state.binding = Bound(
                wire_session_id=picker.wire_session_id,
                target_session_id=target.session_id,
            )
            await self._post_bind_setup_locked(target)
        return PromptResponse(stop_reason="end_turn")

    async def _notify_binding(self, target: PickerTarget) -> None:
        """Push a confirmation `session/update` carrying the bound target.

        The notification's sessionId is the connection's
        ``wire_session_id`` (NOT necessarily the target's id) so the
        client sees updates on the session id they already know. Target
        details live in the structured ``_meta`` payload, including the
        ``inspect.interactive`` flag so Inspect-aware clients render the
        observe-only state (disabled composer) from the bind onward.
        """
        wire = self.state.wire_session_id
        assert wire is not None
        # Interactivity is the bind-time snapshot on the Bound state.
        # Default True for the (not expected here) non-Bound case so the
        # historical drivable wording/behavior is the fallback.
        interactive = (
            self.state.binding.interactive
            if isinstance(self.state.binding, Bound)
            else True
        )
        notif = build_picker_notification(wire, [target])
        # Override the visible text so it reads as a confirmation
        # rather than a "pick one" prompt. We built this notification
        # from build_picker_notification which always returns an
        # AgentMessageChunk with a TextContentBlock — assert for mypy.
        # "Observing" vs "Bound to" tells text-only editor clients
        # whether they can drive the session.
        assert isinstance(notif.update, AgentMessageChunk)
        verb = "Bound to" if interactive else "Observing"
        notif.update.content = TextContentBlock(
            type="text",
            text=(
                f"{verb} {target.task} / sample {target.sample_id} / "
                f"epoch {target.epoch} [{target.session_id}]."
            ),
        )
        # Keep the structured target list under the same _meta key for
        # consistency with the picker flow; add the interactivity flag so
        # Inspect-aware clients gate their composer on it.
        assert notif.field_meta is not None
        notif.field_meta[PICKER_META_KEY] = [picker_target_meta_dict(target)]
        notif.field_meta[INTERACTIVE_META_KEY] = interactive
        await self._send_session_update(notif)

    async def _send_session_update(self, notification: Any) -> None:
        """Send a session/update notification over the connection."""
        if self.connection is None:
            # Defensive — this only happens in tests that construct the
            # handler without going through _on_connection.
            logger.warning(
                "Dropped session/update notification: connection not attached"
            )
            return
        payload = notification.model_dump(mode="json", by_alias=True, exclude_none=True)
        await self.connection.send_notification(_SESSION_UPDATE_METHOD, payload)

    async def _send_session_info_title(self, target_session_id: str) -> None:
        """Send a SessionInfoUpdate carrying the bound target's title.

        The title format is ``"<task> / <sample_id> / epoch <n>"`` —
        editor clients (Zed etc.) surface this in their session UI so
        the human sees what they're attached to without inferring it
        from a transcript scroll.

        Sent once on each bind. The ACP schema treats ``title=null`` as
        a *destructive* clear, so we never emit None here — if we can't
        resolve the active sample (rare; would mean the sample finished
        between bind and forwarder startup) we just skip.

        Uses the connection's ``wire_session_id`` (not the target id)
        so the notification matches the client's view of the session
        identity — same convention as live forwarding.
        """
        sample = _find_active_sample(target_session_id)
        if sample is None:
            return
        if self.state.wire_session_id is None:
            return
        title = f"{sample.task} / {sample.sample.id} / epoch {sample.epoch}"
        notif = SessionNotification(
            session_id=self.state.wire_session_id,
            update=SessionInfoUpdate(
                session_update="session_info_update",
                title=title,
            ),
        )
        await self._send_session_update(notif)

    # ------------------------------------------------------------------
    # ApproverClient / ElicitationClient implementation
    # ------------------------------------------------------------------

    async def request_permission(
        self, request: RequestPermissionRequest
    ) -> RequestPermissionResponse:
        """Send ``session/request_permission`` to this client and await response.

        Implements the :class:`ApproverClient` protocol. The
        ``LiveAcpTransport`` registers this handler when the connection
        binds (via :class:`Forwarders`); the configured
        ``human_approver`` calls this method (via the
        ``approval/_human/acp.py`` driver-fallback chain) when a tool
        needs approval.

        Two binding checks gate the actual send:

        - Connection still attached. If not (race with disconnect
          during binding), raise :class:`ConnectionError`.
        - Connection is ``Bound`` AND its ``target_session_id``
          matches the request's ``sessionId``. Covers the race where
          the connection unbinds or rebinds to a different target
          between the approval shim snapshotting the driver chain
          and this method being called.

        The outbound payload's ``sessionId`` is rewritten to the
        connection's ``wire_session_id``. In auto-bind /
        direct-loadSession this is a no-op (wire == target); in
        picker mode the wire is a synthetic control id minted at
        ``session/new`` and the client would otherwise reject the
        prompt as cross-session traffic. Mirrors
        ``Forwarders._rewrite_session_id`` in ``session_router.py``.

        Any exception (binding mismatch, transport failure, malformed
        response) propagates so the approval shim's driver-fallback
        loop drops us and tries the next client.
        """
        if self.connection is None:
            raise ConnectionError("approver client connection is not attached")
        binding = self.state.binding
        if not isinstance(binding, Bound):
            raise ConnectionError(
                "approver client is not bound to a target session "
                f"(current binding: {type(binding).__name__})"
            )
        if binding.target_session_id != request.session_id:
            raise ConnectionError(
                "approver client target mismatch: bound to "
                f"{binding.target_session_id!r}, request is for "
                f"{request.session_id!r}"
            )
        # Rewrite session_id → wire_session_id so the client receives
        # the session id it actually knows. Skip the copy when they
        # already match (auto-bind / direct-loadSession fast-path).
        if binding.wire_session_id != request.session_id:
            request = request.model_copy(update={"session_id": binding.wire_session_id})
        payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
        raw = await self.connection.send_request("session/request_permission", payload)
        return RequestPermissionResponse.model_validate(raw)

    async def drain_notifications(self) -> None:
        """Wait until pending ``session/update`` notifications have been sent.

        Implements the :class:`ApproverClient` and :class:`ElicitationClient`
        drain barrier by delegating to the per-bind :class:`Forwarders`.
        Safe no-op when there's no active binding (pre-bind,
        post-disconnect, between picker rebinds) — there's no
        forwarder to drain.

        Called by the approval / elicitation shim immediately before
        :meth:`request_permission` / :meth:`request_elicitation` so
        the operator's connection delivers the model's accompanying
        ``agent_message_chunk`` BEFORE the request card lands. See
        ``Forwarders.drain`` for the ordering rationale.
        """
        if self._forwarders is None:
            return
        await self._forwarders.drain()

    async def request_elicitation(
        self, request: "ElicitationRequest"
    ) -> "ElicitationResponse":
        """Send ``elicitation/create`` to this client and await response.

        Implements the :class:`ElicitationClient` protocol. The
        ``LiveAcpTransport`` registers this handler when the connection
        binds AND the peer advertised ``elicitation.form`` capability;
        the Phase 6 ``acp_handler`` calls this method (via the
        ``_input/acp.py`` driver-fallback chain) when ``ask_user`` is
        invoked.

        Mirrors :meth:`request_permission`:

        - Connection still attached. If not, raise :class:`ConnectionError`.
        - Connection is ``Bound`` AND its ``target_session_id`` matches
          ``request.session_id``. Covers the race where the connection
          unbinds or rebinds to a different target between the shim
          snapshotting the driver chain and this method being called.

        The outbound payload's ``sessionId`` is rewritten to the
        connection's ``wire_session_id``. In auto-bind /
        direct-loadSession this is a no-op (wire == target); in picker
        mode the wire is a synthetic control id minted at
        ``session/new`` and the client would otherwise reject the
        prompt as cross-session traffic.

        The wire payload is the standard ACP ``elicitation/create``
        shape — ``{message, mode: "form", sessionId, toolCallId?,
        requestedSchema}`` — assembled here from the
        :class:`ElicitationRequest` fields. ``acp.schema`` 0.10 models
        this shape across two Pydantic classes; we serialize directly
        rather than wrestle with their split. Returns the parsed ACP
        response union (``Accept | Decline | Cancel``); mapping to
        :class:`InputResult` happens in the Phase 6 consumer.

        Any exception (binding mismatch, transport failure, malformed
        response) propagates so the elicitation shim's driver-fallback
        loop drops us and tries the next client.
        """
        if self.connection is None:
            raise ConnectionError("elicitation client connection is not attached")
        binding = self.state.binding
        if not isinstance(binding, Bound):
            raise ConnectionError(
                "elicitation client is not bound to a target session "
                f"(current binding: {type(binding).__name__})"
            )
        if binding.target_session_id != request.session_id:
            raise ConnectionError(
                "elicitation client target mismatch: bound to "
                f"{binding.target_session_id!r}, request is for "
                f"{request.session_id!r}"
            )
        # Build the flat wire payload directly. acp.schema 0.10 splits
        # the message/mode pair (CreateFormElicitationRequest) from the
        # session scope (ElicitationFormSessionMode); on the wire it's
        # one merged object, so we emit the canonical shape ourselves.
        payload: dict[str, Any] = {
            "message": request.message,
            "mode": "form",
            "sessionId": binding.wire_session_id,
            "requestedSchema": request.requested_schema.model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
        }
        if request.tool_call_id is not None:
            payload["toolCallId"] = request.tool_call_id
        raw = await self.connection.send_request("elicitation/create", payload)
        return _parse_elicitation_response(raw)

    # ------------------------------------------------------------------
    # Bind / unbind orchestration
    # ------------------------------------------------------------------

    async def _start_forwarders(self, target_session_id: str) -> None:
        """Bind this connection to a target session and start forwarding.

        Sequence:

        1. Tear down any prior bind (idempotent first-bind no-op).
        2. Resolve the target. No-op if it disappeared.
        3. Send the editor-facing session title so the UI is framed
           BEFORE any conversation events arrive.
        4. Re-verify the target is still alive. The title-send await
           is the one yield point between the initial lookup and the
           forwarder attach; if the agent task exited the session
           during it, attach() would create an orphan never-EOF
           subscriber.
        5. Construct a fresh :class:`Forwarders` (capturing the wire
           sessionId at construction so live forwarding can't be
           cross-streamed by a later state mutation) and start it.

        Callers MUST hold ``_bind_lock`` — invoked from
        ``_post_bind_setup_locked``. The lock serializes bind
        sequences, so no inline rebind-race checks are needed within
        this method.
        """
        await self._stop_forwarders()

        target = _find_live_session(target_session_id)
        if target is None:
            return

        await self._send_session_info_title(target_session_id)

        target = _find_live_session(target_session_id)
        if target is None:
            return
        assert self.connection is not None
        wire = self.state.wire_session_id
        assert wire is not None
        self._forwarders = Forwarders(
            self.state,
            self.connection,
            self,
            self if self.state.client_supports_elicitation_form else None,
            target_session_id=target_session_id,
            wire_session_id=wire,
        )
        await self._forwarders.start(target)

    async def _stop_forwarders(self, *, graceful: bool = False) -> None:
        """Tear down the current bind's forwarders, if any. Idempotent.

        ``graceful=True`` is passed through to :meth:`Forwarders.stop`
        from :meth:`shutdown` when the server is winding down — gives
        the semantic forwarder a chance to send
        ``inspect/session_ended`` before the connection is closed.
        All other callers (rebind, picker re-entry, post-prompt
        cleanup) pass ``False`` so the teardown is immediate.

        **Reentrancy guard**: take the local reference and clear
        ``self._forwarders`` BEFORE awaiting ``forwarders.stop`` so
        concurrent callers (e.g. ``AcpServer.stop`` racing the
        per-connection ``_on_connection`` finally block when the
        peer also closed) see ``None`` and no-op rather than
        re-entering ``Forwarders.stop`` on the same instance.
        Without this, the second caller would proceed past the
        ``self._semantic_task is not None`` guard inside
        ``Forwarders.stop``, suspend on its own await, and the first
        caller's completion would nullify ``self._semantic_task`` —
        producing ``AttributeError: 'NoneType' object has no
        attribute 'done'`` when the second caller resumed past its
        await and checked the task again.
        """
        forwarders = self._forwarders
        if forwarders is None:
            return
        self._forwarders = None
        await forwarders.stop(graceful=graceful)

    async def _post_bind_setup(self, target: PickerTarget, gen: int) -> None:
        """Deferred post-response binding work: acquires lock, checks generation.

        Used by the ``newSession`` auto-bind and ``loadSession``
        deferred paths — both set ``state.binding`` and increment
        ``_bind_generation`` inside ``_bind_lock``, then schedule this
        to run after the response writes (so clients like Zed don't
        drop notifications referencing a sessionId they haven't yet
        seen — see ``_schedule_after_response``).

        Acquires ``_bind_lock`` and verifies the captured generation
        still matches the current one. If a newer bind has landed,
        no-ops cleanly. Otherwise delegates to ``_post_bind_setup_locked``
        which performs notify + start under the held lock — no
        interleaving with other binds is possible.

        Picker selection uses ``_post_bind_setup_locked`` directly
        because it already holds ``_bind_lock`` for its whole handler
        body (acquiring twice would deadlock — ``asyncio.Lock`` is
        non-reentrant).
        """
        async with self._bind_lock:
            if gen != self._bind_generation:
                return
            await self._post_bind_setup_locked(target)

    async def _post_bind_setup_locked(self, target: PickerTarget) -> None:
        """Notify + start forwarders. Caller MUST hold ``_bind_lock``.

        Used directly by ``_handle_picker_selection`` (which holds the
        lock for its whole body, so the deferred / locked split
        avoids re-entry) and via ``_post_bind_setup`` for the
        deferred newSession / loadSession paths.

        After forwarders are up we promote ourselves to the active
        driver across every registry we belong to (approver,
        elicitation), THEN wake any parked dispatch shims via the
        per-domain ``notify_*_attach`` calls. Every path through here
        (``session/load``, ``session/new`` auto-bind, picker
        selection) is a deliberate "this client is now driving"
        signal, parallel to the ``session/prompt`` promotion at the
        bound-mode prompt handler.

        Ordering matters: promote-then-notify ensures a parked shim
        re-snapshots a driver chain that already has THIS connection
        at position 0, so the re-issued request routes here rather
        than to a stale first-attached client. The notifications fire
        ONLY here (not from the registries' ``attach`` calls), so
        subscribers wake after replay completes and the forwarder is
        live — no race where the operator sees a request card before
        the conversation context replays.

        Silently no-ops if the live session disappeared between
        ``_start_forwarders`` and now (e.g. sample finished); also
        no-ops if we aren't a registered client in a given registry,
        which can happen if forwarder startup raised partway through
        OR if a registry's per-domain capability gate excluded us
        (no ``elicitation.form`` capability, etc.).
        """
        await self._notify_binding(target)
        await self._start_forwarders(target.session_id)
        live = _find_live_session(target.session_id)
        if live is not None:
            live.mark_active_session_client(self)
            live.notify_approver_attach(self)
            if self.state.client_supports_elicitation_form:
                live.notify_elicitation_attach(self)

    async def _send_notification_if_current(self, notification: Any, gen: int) -> None:
        """Send a ``session/update`` only if the bind generation still matches.

        Used for deferred picker notifications (and similar) that
        were captured at a specific bind generation and would be
        stale if a newer bind had landed in the meantime. Sending
        the stale notification would route old picker state to a
        connection that has moved on to a different binding.
        """
        async with self._bind_lock:
            if gen != self._bind_generation:
                return
            await self._send_session_update(notification)

    def _schedule_after_response(
        self, factory: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Schedule work to run after the in-progress RPC response writes.

        The ACP framework's ``_run_request`` writes the response only
        after the handler returns. Notifications sent inline from a
        handler therefore land on the wire BEFORE the response — Zed
        (and likely other clients) discard such notifications because
        the sessionId they reference is not yet known to the client.

        This helper schedules ``factory()`` on the event loop with a
        leading ``sleep(0)`` so the framework's in-flight
        ``_sender.send(response)`` enqueues onto the writer first; the
        sender's internal FIFO queue then guarantees the response is
        flushed before any notification we enqueue here.

        Takes a **factory** (not a pre-created coroutine) so the
        coroutine is only constructed if/when the task survives the
        initial yield. If ``shutdown`` cancels the task during
        ``sleep(0)``, no coroutine exists to leak as
        ``RuntimeWarning: coroutine ... was never awaited``.

        Tasks are tracked in ``_pending_after_response`` so they're not
        garbage-collected before they run; a done callback discards
        them and logs any exception.
        """

        async def _run() -> None:
            await asyncio.sleep(0)
            await factory()

        task = asyncio.create_task(_run())
        self._pending_after_response.add(task)
        task.add_done_callback(self._on_after_response_done)

    def _on_after_response_done(self, task: asyncio.Task[None]) -> None:
        self._pending_after_response.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.exception("Deferred post-response send failed", exc_info=exc)

    async def shutdown(self, *, graceful: bool = False) -> None:
        """Connection-close cleanup: cancel deferred sends, stop forwarders.

        Called from two paths:

        - The server's ``_on_connection`` finally block (after
          ``conn.main_loop`` returns on peer disconnect) — uses the
          default ``graceful=False``. The peer is gone; there's
          nothing to send to.
        - :meth:`AcpServer.stop` (end-of-eval teardown) — passes
          ``graceful=True`` so the semantic forwarder can finish
          sending ``inspect/session_ended`` while the connection is
          still alive. Without this the client never sees the
          lifecycle pill flip to ``complete`` on eval end (the
          forwarder's send hits ``ConnectionError("Connection
          closed")`` because :meth:`AcpServer.stop` previously called
          ``conn.close()`` before this path got a chance to run).

        Deferred post-response sends are always cancelled — the
        writer is about to close, so any pending write would either
        fail or race the close.
        """
        for task in list(self._pending_after_response):
            task.cancel()
        if self._pending_after_response:
            await asyncio.gather(*self._pending_after_response, return_exceptions=True)
        await self._stop_forwarders(graceful=graceful)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


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

    :class:`TextContentBlock` is supported fully. Other ACP content
    variants (image / audio / resource / embedded-resource) lower to
    placeholder text — full multi-modal translation is a follow-on.
    We log a warning on first sight of a non-text block per connection
    so users notice without flooding logs.
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
            "fully translated today. Multi-modal support is a future "
            "phase."
        )
    return "".join(parts)


def _find_live_session(session_id: str) -> "AcpTransport | None":
    """Look up a live :class:`AcpTransport` by sessionId.

    Walks :func:`inspect_ai.log._samples.active_samples` for a sample
    whose ``acp_session.session_id`` matches. Returns ``None`` if
    nothing matches (the underlying sample has finished and torn down
    its session).
    """
    from inspect_ai.log._samples import active_samples

    for sample in active_samples():
        sess = sample.acp_transport
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
        sess = sample.acp_transport
        if sess is not None and sess.session_id == session_id:
            return sample
    return None


def _picker_target_from_listing(listing: SampleListing) -> PickerTarget:
    """Build a :class:`PickerTarget` from an attachable :class:`SampleListing`.

    Callers must pass a listing with a non-``None`` ``session_id`` (an
    attachable sample). Used by the observe-only bind paths so a
    channel-less sample can be bound the same way a drivable one is —
    the resulting target feeds the binding-confirmation ``_meta`` and
    title exactly as a picker target would.
    """
    assert listing.session_id is not None
    return PickerTarget(
        session_id=listing.session_id,
        task=listing.task,
        sample_id=listing.sample_id,
        epoch=listing.epoch,
        agent_name=listing.agent_name,
        started_at=listing.started_at,
        total_messages=listing.total_messages,
        total_tokens=listing.total_tokens,
        fails_on_error=listing.fails_on_error,
    )


def _resolve_attachable_target_by_id(
    session_id: str,
) -> tuple[PickerTarget, bool] | None:
    """Resolve a bindable target by sessionId — interactive or observe-only.

    Two-tier: try the interactive :func:`list_picker_targets` first
    (drivable sessions — the pre-existing path, unchanged); on miss,
    fall back to :func:`list_all_samples` (which also surfaces
    observe-only attachable samples — see Phase 2). Returns
    ``(target, interactive)`` or ``None`` when nothing attachable
    matches (unknown id, noop, or finalized).
    """
    for target in list_picker_targets():
        if target.session_id == session_id:
            return target, True
    for listing in list_all_samples():
        if listing.session_id is not None and listing.session_id == session_id:
            return _picker_target_from_listing(listing), listing.interactive
    return None


def _resolve_attachable_target_by_spec(
    task: str, sample_id: str, epoch: int
) -> tuple[PickerTarget, bool] | None:
    """Resolve a bindable target by ``task/sample_id/epoch`` slash-spec.

    Sibling of :func:`_resolve_attachable_target_by_id` for the
    ``inspect/attach`` direct-bind path. Same two-tier resolution:
    interactive picker targets first, then observe-only attachable
    samples.
    """
    for target in list_picker_targets():
        if (
            target.task == task
            and target.sample_id == sample_id
            and target.epoch == epoch
        ):
            return target, True
    for listing in list_all_samples():
        if (
            listing.session_id is not None
            and listing.task == task
            and listing.sample_id == sample_id
            and listing.epoch == epoch
        ):
            return _picker_target_from_listing(listing), listing.interactive
    return None


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


def _parse_elicitation_response(raw: Any) -> "ElicitationResponse":
    """Parse an ``elicitation/create`` response into its tagged variant.

    The three response classes (``Accept``, ``Decline``, ``Cancel``)
    are separate Pydantic models discriminated on the ``action``
    field. Dispatch explicitly rather than relying on a Union
    TypeAdapter so a malformed / unexpected payload surfaces a clear
    error at the wire boundary rather than a generic validation
    failure deep inside the dispatch shim.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            f"elicitation/create response must be a dict, got {type(raw).__name__}"
        )
    action = raw.get("action")
    if action == "accept":
        return AcceptElicitationResponse.model_validate(raw)
    if action == "decline":
        return DeclineElicitationResponse.model_validate(raw)
    if action == "cancel":
        return CancelElicitationResponse.model_validate(raw)
    raise ValueError(f"elicitation/create response has unknown action: {action!r}")
