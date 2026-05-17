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
from shortuuid import uuid

from inspect_ai.agent._acp.inspect_ext import (
    INSPECT_CANCEL_SAMPLE_METHOD,
    INSPECT_CANCEL_TOOL_CALL_METHOD,
    PICKER_META_KEY,
    build_picker_notification,
    detect_capabilities,
    picker_target_meta_dict,
)
from inspect_ai.agent._acp.picker import (
    PickerTarget,
    list_picker_targets,
    resolve_selection,
)
from inspect_ai.agent._acp.session_router import Forwarders
from inspect_ai.model._chat_message import ChatMessageUser

if TYPE_CHECKING:
    from inspect_ai.agent._acp.session import AcpSession
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
    is the internal ``LiveAcpSession.session_id`` we forward to. In
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
        # Capture client-capability flags. See ``detect_capabilities``
        # for the allowlist + ``_meta`` opt-in logic.
        (
            self.state.client_renders_plan,
            self.state.raw_events_enabled,
        ) = detect_capabilities(client_info, client_capabilities)

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
        # Binding-confirmation notification, title, and replay events
        # are deferred until after the response writes — same rationale
        # as ``_auto_bind`` (avoid clients dropping updates for a
        # sessionId they haven't yet seen).
        #
        # Any prior bind's forwarders are torn down SYNCHRONOUSLY here
        # before mutating ``state.binding`` — see ``_auto_bind`` for
        # the cross-stream pollution this prevents.
        await self._stop_forwarders()
        expected = Bound(
            wire_session_id=match.session_id, target_session_id=match.session_id
        )
        self.state.binding = expected
        self._schedule_after_response(lambda: self._post_bind_setup(match, expected))
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
                    **picker_target_meta_dict(t),
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
        # Defer notification until after the NewSessionResponse has been
        # written to the wire — Zed (and likely other clients) drop
        # session/update notifications for a sessionId they haven't yet
        # seen in a newSession/loadSession response.
        self._schedule_after_response(lambda: self._send_session_update(notif))
        return NewSessionResponse(session_id=control_id)

    async def _auto_bind(self, target: PickerTarget) -> NewSessionResponse:
        """Skip the picker for the single-target case; bind immediately.

        On the auto-bind path the wire sessionId IS the target's id
        (it's what we hand back in the NewSessionResponse), so the
        client and server agree on the same id.

        The binding-confirmation notification, session_info title, and
        replay-on-attach events all flow as ``session/update`` for
        this sessionId — they're deferred until after the response
        writes so clients (Zed etc.) don't drop them as references to
        a sessionId they don't yet know.

        Any prior bind's forwarders are torn down SYNCHRONOUSLY here
        before mutating ``state.binding``. Without that, the old
        forwarder would keep publishing under the new
        ``wire_session_id`` (read at notification time by
        ``Forwarders._rewrite_session_id``) during the gap before
        ``_post_bind_setup`` runs, leaking the old target's events as
        if they came from the new session.
        """
        await self._stop_forwarders()
        expected = Bound(
            wire_session_id=target.session_id, target_session_id=target.session_id
        )
        self.state.binding = expected
        self._schedule_after_response(lambda: self._post_bind_setup(target, expected))
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
        #
        # Same synchronous-stop-before-bind + guarded-setup pattern as
        # ``_auto_bind`` / ``load_session``. Picker selection runs as
        # an ACP request handler — ACP dispatches each request as its
        # own asyncio task, so a concurrent ``session/load`` /
        # ``session/new`` on the same connection CAN interleave during
        # our ``_notify_binding`` / ``_start_forwarders`` awaits.
        # Without the guard, the older selection handler could attach
        # forwarders for the picked target after the newer bind is
        # already current. We pass ``expected`` through
        # ``_post_bind_setup`` so each await rechecks ``state.binding``.
        await self._stop_forwarders()
        expected = Bound(
            wire_session_id=picker.wire_session_id,
            target_session_id=target.session_id,
        )
        self.state.binding = expected
        await self._post_bind_setup(target, expected)
        return PromptResponse(stop_reason="end_turn")

    async def _notify_binding(self, target: PickerTarget) -> None:
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
        notif.field_meta[PICKER_META_KEY] = [picker_target_meta_dict(target)]
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
        ``LiveAcpSession`` registers this handler when the connection
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

    async def _start_forwarders(
        self,
        target_session_id: str,
        expected: Bound | None = None,
    ) -> None:
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

        **Rebind race guard.** If ``expected`` is provided, recheck
        ``state.binding == expected`` after each await. If a rebind
        landed in the gap, bail out — the newer bind will start its
        own forwarders. Without this, a stale setup could attach
        forwarders for an old target after a newer bind is already
        current, leaking old events under the new wire id.

        **All production call sites pass ``expected``** (via
        ``_post_bind_setup``). ACP dispatches each request as its own
        asyncio task, so even handlers that look synchronous (picker
        selection, ``load_session``) can interleave with concurrent
        bind requests during their awaits. ``expected=None`` is
        retained on the parameter only for composability — leave the
        guard on in real code.

        ``expected`` is also threaded into ``Forwarders.start`` so the
        guard covers the replay phases inside it (which yield and
        re-read ``state.wire_session_id``). Without that, a rebind
        during the raw-replay yield would cause subsequent semantic
        replay to construct notifications under the NEW wire id for
        the OLD target — true cross-stream pollution.
        """
        await self._stop_forwarders()
        if expected is not None and self.state.binding != expected:
            return

        target = _find_live_session(target_session_id)
        if target is None:
            return

        await self._send_session_info_title(target_session_id)
        if expected is not None and self.state.binding != expected:
            return

        target = _find_live_session(target_session_id)
        if target is None:
            return
        assert self.connection is not None
        forwarders = Forwarders(self.state, self.connection, self)
        # Final pre-start check after the second target lookup.
        if expected is not None and self.state.binding != expected:
            return
        self._forwarders = forwarders
        await forwarders.start(target, target_session_id, expected=expected)
        # Post-start check: even with ``expected`` threaded into
        # ``Forwarders.start`` (which prevents cross-stream replay
        # emits + skips live task startup if stale), this final check
        # catches edge cases where the binding flipped between
        # ``start`` returning and us reading ``state.binding``. Tear
        # down only if ``self._forwarders`` is still ours — a
        # concurrent rebind may have already replaced it.
        if expected is not None and self.state.binding != expected:
            if self._forwarders is forwarders:
                self._forwarders = None
            await forwarders.stop()

    async def _stop_forwarders(self) -> None:
        """Tear down the current bind's forwarders, if any. Idempotent."""
        if self._forwarders is not None:
            await self._forwarders.stop()
            self._forwarders = None

    async def _post_bind_setup(self, target: PickerTarget, expected: Bound) -> None:
        """Post-response binding work: confirmation notification + forwarders.

        Shared body for the three bind paths:

        - ``newSession`` auto-bind and ``loadSession``: set
          ``state.binding`` inline and SCHEDULE this to run after the
          response so clients (Zed etc.) don't drop notifications
          referencing a sessionId they haven't seen yet. See
          ``_schedule_after_response`` for the mechanism.
        - Picker selection (``_handle_picker_selection``): responds to
          ``session/prompt`` after the client already knows the wire
          sessionId, so this runs INLINE — no defer needed. The guard
          is still required because ACP dispatches each request as
          its own asyncio task, and a concurrent ``session/load`` /
          ``session/new`` can interleave during our awaits.

        **Rebind race guard.** A client that rebinds (a second
        ``session/load`` or another ``session/new``) before the
        deferred task runs would otherwise see the stale task send a
        confirmation for the old target *under the new wire sessionId*
        (since ``_notify_binding`` reads ``state.wire_session_id`` at
        call time), and then ``_start_forwarders`` would tear down the
        newer bind's forwarders and replace them with the stale
        target's. We capture the expected ``Bound`` at schedule time
        and no-op if it no longer matches. ``Bound`` is a frozen
        dataclass so equality is value-based.

        Re-checked AFTER the notify yield as well — ``_notify_binding``
        awaits ``_send_session_update``, opening a second race window
        before forwarders start. ``expected`` is also passed into
        ``_start_forwarders`` so the per-await-point guard applies to
        the multi-step forwarder startup (stop / title-send / replay)
        as well.
        """
        if self.state.binding != expected:
            return
        await self._notify_binding(target)
        if self.state.binding != expected:
            return
        await self._start_forwarders(target.session_id, expected=expected)

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

    async def shutdown(self) -> None:
        """Connection-close cleanup: cancel deferred sends, stop forwarders.

        Called from the server's ``_on_connection`` finally block after
        ``conn.main_loop`` returns. Deferred post-response sends are
        cancelled (the writer is about to close, so any pending write
        would either fail or race the close); forwarders are then
        torn down via the existing per-bind shutdown path.
        """
        for task in list(self._pending_after_response):
            task.cancel()
        if self._pending_after_response:
            await asyncio.gather(*self._pending_after_response, return_exceptions=True)
        await self._stop_forwarders()


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
