"""Per-connection ACP method handler.

One :class:`_ConnectionHandler` per accepted socket connection.
Implements the ACP ``Agent`` role (``initialize`` / ``new_session`` /
``load_session`` / ``prompt`` / ``cancel``) plus the non-standard
``inspect/*`` action methods. Per-connection state (synthetic control
sessionId, bound target sessionId, picker target snapshot, capability
flags) lives in :class:`_ConnectionState` so two concurrent clients can
pick different target sessions independently.

asyncio anchor — this module is **asyncio-bound** at the
``acp.Connection`` boundary. See ``design/acp/agent-acp.md`` "asyncio /
anyio boundary" for the rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal

from acp.connection import Connection
from acp.exceptions import RequestError
from acp.meta import CLIENT_METHODS, PROTOCOL_VERSION
from acp.schema import (
    AgentCapabilities,
    AgentMessageChunk,
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
from pydantic import BaseModel, Field
from shortuuid import uuid

from inspect_ai.agent._acp._picker import (
    PICKER_META_KEY,
    _PickerTarget,
    build_picker_notification,
    list_picker_targets,
    resolve_selection,
)
from inspect_ai.agent._acp._session_router import Forwarders
from inspect_ai.model._chat_message import ChatMessageUser

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

# Clients whose ``client_info.name`` matches this allowlist
# (case-insensitive) are treated as plan-rendering — the forwarder
# substitutes ``AgentPlanUpdate`` for ``update_plan`` / ``todo_write``
# tool-call notifications. Clients with first-class ``Plan`` UI:
# - Zed (live plan panel + completed-plan snapshot in chat history)
# - Toad (sidebar plan widget with status icons + priority pills)
# Other clients can opt in explicitly via the ``_meta`` key below.
PLAN_RENDERING_CLIENTS = frozenset({"zed", "toad"})

# Capability flags consumed from ``clientCapabilities._meta``. Standard
# ACP extensibility pattern (``_meta`` is reserved for arbitrary vendor
# metadata; clients who don't recognize the keys ignore them).
PLAN_RENDERING_META_KEY = "inspect.plan_rendering"
RAW_EVENTS_META_KEY = "inspect.raw_events"


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
    picker_targets: list[_PickerTarget]


@dataclass(frozen=True)
class Bound:
    """Connection is bound to a target session; forwarding is active.

    ``wire_session_id`` is what the client sees. ``target_session_id``
    is the internal ``_LiveAcpSession.session_id`` we forward to. In
    the auto-bind / direct-load paths these are equal; on the picker
    selection path the wire id is the synthetic control id and the
    target id is the chosen sample — the design contract is that the
    client's sessionId stays stable across a picker rebind.
    """

    wire_session_id: str
    target_session_id: str


# Tagged union of the connection's binding mode. Replaces three
# independent nullable fields (``wire_session_id``,
# ``target_session_id``, ``picker_targets``) with one variant whose
# valid combinations are typed.
BindingMode = Unbound | PickerMode | Bound


@dataclass
class _ConnectionState:
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
    raw_events_enabled: bool = False

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


class _ConnectionHandler:
    """Per-connection method handler. Plays the ACP ``Agent`` role."""

    def __init__(self) -> None:
        self.connection: Connection | None = None
        self.state = _ConnectionState()
        # Per-bind outbound forwarder. ``None`` until the connection
        # binds to a target. Each bind constructs a fresh instance —
        # per-bind state (notably the plan-tool stash) cannot leak
        # across rebinds because the object itself is destroyed.
        self._forwarders: Forwarders | None = None

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
        ``raw_events_enabled``) so the per-connection forwarder can
        switch behavior per client.
        """
        # Capture client-capability flags. Two sources:
        # - ``client_info.name`` against the plan-rendering allowlist
        #   (case-insensitive) — known editors with first-class Plan UI.
        # - ``clientCapabilities._meta`` for explicit per-client opt-in
        #   keys (``inspect.plan_rendering``, ``inspect.raw_events``).
        # Either source flips the flag on; both default off.
        name = client_info.name.lower() if client_info is not None else ""
        meta: dict[str, Any] = {}
        if client_capabilities is not None and client_capabilities.field_meta:
            meta = client_capabilities.field_meta
        self.state.client_renders_plan = name in PLAN_RENDERING_CLIENTS or bool(
            meta.get(PLAN_RENDERING_META_KEY)
        )
        self.state.raw_events_enabled = bool(meta.get(RAW_EVENTS_META_KEY))

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
        self.state.binding = Bound(
            wire_session_id=match.session_id, target_session_id=match.session_id
        )
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
            case Bound(target_session_id=target_id):
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
                text = _translate_prompt_blocks(prompt)
                msg = ChatMessageUser(content=text, source="operator")
                target.submit_user_message(msg)
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
            case Bound(wire_session_id=wire, target_session_id=target_id):
                if session_id != wire:
                    return None
                target = _find_live_session(target_id)
                if target is None:
                    # Bound target has already finished; nothing to cancel.
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
        :meth:`inspect_new_session` accepts. Clients that already know
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
                    "sessionId": t.session_id,
                    "task": t.task,
                    "sampleId": t.sample_id,
                    "epoch": t.epoch,
                    "agentName": t.agent_name,
                    "startedAt": t.started_at,
                    "totalTokens": t.total_tokens,
                    "target": f"{t.task}/{t.sample_id}/{t.epoch}",
                }
                for t in targets
            ]
        }

    async def inspect_new_session(
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

        Distinct from ``session/cancel``, which interrupts the current
        turn but lets the agent loop recover. This method is terminal:
        the sample finishes.
        """
        bound = self._require_bound(session_id, "inspect/cancel_sample")
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

        bound = self._require_bound(session_id, "inspect/cancel_tool_call")
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
        client diagnostics (``"inspect/cancel_sample called before
        binding"`` rather than a generic message).
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
        self, targets: list[_PickerTarget]
    ) -> NewSessionResponse:
        """Mint a control sessionId, snapshot targets, push picker payload."""
        # Tear down any previous binding's forwarders before entering
        # picker mode. Without this, a connection that auto-bound to a
        # single target, then sees a second target appear, then calls
        # newSession again would keep the prior target's forwarder
        # running with the new picker control sessionId — live events
        # from that target would leak to the client during picker
        # selection.
        await self._stop_forwarders()
        control_id = uuid()
        # Snapshot the target list so that the numeric selection (1, 2,
        # ...) resolves against the exact list the client was shown. A
        # fresh enumeration at selection time could disagree if a
        # sample finished or a new one started in between.
        self.state.binding = PickerMode(
            wire_session_id=control_id, picker_targets=list(targets)
        )
        notif = build_picker_notification(control_id, targets)
        await self._send_session_update(notif)
        return NewSessionResponse(session_id=control_id)

    async def _auto_bind(self, target: _PickerTarget) -> NewSessionResponse:
        """Skip the picker for the single-target case; bind immediately.

        On the auto-bind path the wire sessionId IS the target's id
        (it's what we hand back in the NewSessionResponse), so the
        client and server agree on the same id.
        """
        self.state.binding = Bound(
            wire_session_id=target.session_id, target_session_id=target.session_id
        )
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
        self.state.binding = Bound(
            wire_session_id=picker.wire_session_id,
            target_session_id=target.session_id,
        )
        await self._notify_binding(target)
        await self._start_forwarders(target.session_id)
        return PromptResponse(stop_reason="end_turn")

    async def _notify_binding(self, target: _PickerTarget) -> None:
        """Push a confirmation `session/update` carrying the bound target.

        The notification's sessionId is the connection's
        ``wire_session_id`` (NOT necessarily the target's id) so the
        client sees updates on the session id they already know. Target
        details live in the structured ``_meta`` payload.
        """
        wire = self.state.wire_session_id
        assert wire is not None
        notif = build_picker_notification(wire, [target])
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
        # Keep the structured target list under the same _meta key for
        # consistency with the picker flow.
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
    # ApproverClient implementation
    # ------------------------------------------------------------------

    async def request_permission(
        self, request: RequestPermissionRequest
    ) -> RequestPermissionResponse:
        """Send ``session/request_permission`` to this client and await response.

        Implements the :class:`ApproverClient` protocol. The
        ``_LiveAcpSession`` registers this handler when the connection
        binds (via :class:`Forwarders`); the configured
        ``human_approver`` calls this method (via the
        ``approval/_human/acp.py`` race orchestrator) when a tool
        needs approval.

        Raises :class:`ConnectionError` if the connection is missing
        (race with disconnect during binding) so the race orchestrator
        treats this as a losing entrant. Any other exception (transport
        failure, malformed response) also propagates so the
        orchestrator can drop us from the race.
        """
        if self.connection is None:
            raise ConnectionError("approver client connection is not attached")
        payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
        raw = await self.connection.send_request("session/request_permission", payload)
        return RequestPermissionResponse.model_validate(raw)

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
        5. Construct a fresh :class:`Forwarders` and start it (per-bind
           plan-tool stash and forwarder runtime live entirely there).
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
        self._forwarders = Forwarders(self.state, self.connection, self)
        await self._forwarders.start(target, target_session_id)

    async def _stop_forwarders(self) -> None:
        """Tear down the current bind's forwarders, if any. Idempotent."""
        if self._forwarders is not None:
            await self._forwarders.stop()
            self._forwarders = None


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
    placeholder text — full multi-modal translation lands in Phase 13.
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


def _find_live_session(session_id: str) -> "AcpSession | None":
    """Look up a live :class:`AcpSession` by sessionId.

    Walks :func:`inspect_ai.log._samples.active_samples` for a sample
    whose ``acp_session.session_id`` matches. Returns ``None`` if
    nothing matches (the underlying sample has finished and torn down
    its session).
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


# ---------------------------------------------------------------------------
# `inspect/*` action methods — Pydantic param models + dispatch wrapper
# ---------------------------------------------------------------------------
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

    Inspect-aware clients (the TUI, editors that already know which
    sample to attach to) pass the ``task/sample_id/epoch`` triple
    directly to skip the picker. The standard ACP ``session/new``
    pydantic schema (``NewSessionRequest``) doesn't allow extra
    top-level fields so this lives as a separate inspect-namespace
    method with its own model.
    """

    cwd: str
    mcp_servers: Any = Field(default=None, alias="mcpServers")
    target: str
    """``task/sample_id/epoch`` direct-bind spec — slash-delimited."""


class _ListSessionsParams(BaseModel):
    """Pydantic param model for ``inspect/list_sessions`` (no params)."""


def _wrap_action_handler(func: Any, model: type[BaseModel]) -> Any:
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
        # models like :class:`_ListSessionsParams`. Coerce to an empty
        # dict so handlers that take no required params accept the
        # omitted form transparently. Handlers with required fields
        # still surface a clean validation error on the missing keys.
        if params is None:
            params = {}
        request = model.model_validate(params)
        kwargs = {
            field_name: getattr(request, field_name)
            for field_name in model.model_fields
        }
        return await func(**kwargs)

    return wrapper


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
