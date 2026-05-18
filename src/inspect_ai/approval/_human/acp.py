"""ACP routing for human tool-call approval prompts.

When one or more ACP clients are attached to the running sample
(e.g. Zed connected via ``inspect acp --stdio``), the
``human_approver`` routes its prompts through ACP's
``session/request_permission`` rather than opening the in-proc
Textual panel. When no clients are attached, this module's entry
point returns ``None`` and the caller (``human_approver``) falls
through to the existing panel / console flow — no behavior change
in the no-client case.

Single-driver semantics: the request is sent to ONE client at a
time — the driver, which is the client whose ``session/prompt``
most recently landed on this session (fallback: first-attached
when no prompt has been sent yet). If the driver's request raises
(typically ``ConnectionError`` on mid-prompt disconnect), the shim
falls through to the next attached client in attach order. ACP has
no protocol-level cancel for outbound requests, so broadcasting
would leave losing editors with a stale permission card forever
(whatever they later click is silently discarded). Routing to one
driver means the operator only sees the prompt on the client
they're actually using; others observe via the normal event
stream.

Wait-forever: no timeout. The human at the editor is the source
of truth; default-deny on timeout would be surprising and matches
the in-proc human approver's blocking behavior.

Option round-trip: each ``PermissionOption.optionId`` is the
literal :data:`ApprovalDecision` string (``"approve"``,
``"reject"``, etc.) so the response maps back losslessly.

asyncio boundary note
=====================

This module is intentionally **asyncio-bound** (not anyio). It
awaits asyncio futures returned by ``conn.send_request`` (the
``acp`` library is asyncio-only). Cancellation catches use
``anyio.get_cancelled_exc_class()`` so they're backend-agnostic
even though the orchestration is asyncio.
"""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING, Any, cast

import anyio
from acp.schema import (
    PermissionOption,
    PermissionOptionKind,
    RequestPermissionRequest,
    RequestPermissionResponse,
    ToolCallUpdate,
)

from inspect_ai.agent._acp._guards import acp_guard
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallView,
    substitute_tool_call_content,
)

from .._approval import Approval, ApprovalDecision

if TYPE_CHECKING:
    from acp.schema import ContentToolCallContent

    from inspect_ai.agent._acp.session import ApproverClient

logger = getLogger(__name__)


# Stable mapping from the configured ``human_approver`` choices to
# ACP ``PermissionOptionKind``. The kind is a hint to the client
# about how to visually present the option (typically the
# allow/reject color treatment); the actual decision routes via
# ``optionId``. Mappings here are best-effort semantic neighbors —
# ACP's kinds are binary allow/deny variants and Inspect's
# ``terminate`` / ``escalate`` / ``modify`` don't have perfect ACP
# counterparts.
_KIND_BY_DECISION: dict[ApprovalDecision, PermissionOptionKind] = {
    "approve": "allow_once",
    "modify": "allow_once",  # "approve with modification"
    "reject": "reject_once",
    "terminate": "reject_always",  # strongest reject — also stops the eval
    "escalate": "reject_once",  # no real ACP equivalent
}

# Display labels for each decision. Editors render these as the
# button text on the permission card.
_LABEL_BY_DECISION: dict[ApprovalDecision, str] = {
    "approve": "Approve",
    "modify": "Modify",
    "reject": "Reject",
    "terminate": "Terminate",
    "escalate": "Escalate",
}


def _options_from_choices(choices: list[ApprovalDecision]) -> list[PermissionOption]:
    """Build ACP permission options from the approver's configured choices.

    ``optionId`` is the literal decision string so the response
    round-trips back to an :class:`ApprovalDecision` without a
    lookup table. ``name`` is the human-readable button label.
    """
    return [
        PermissionOption(
            option_id=choice,
            name=_LABEL_BY_DECISION.get(choice, choice.capitalize()),
            kind=_KIND_BY_DECISION.get(choice, "reject_once"),
        )
        for choice in choices
    ]


def _approval_from_response(
    response: RequestPermissionResponse,
    choices: list[ApprovalDecision],
) -> Approval:
    """Map a client's response back to an :class:`Approval`.

    ``outcome.cancelled`` → ``Approval(decision="reject", explanation=...)``.
    ``outcome.selected`` with a recognized ``optionId`` →
    ``Approval(decision=<that decision>)``.
    ``outcome.selected`` with an unrecognized ``optionId`` → reject
    with an explanation noting the unknown id; defensive against a
    misbehaving client (or a client that synthesized its own option).
    """
    outcome = response.outcome
    # The discriminator is ``outcome.outcome`` ("selected" | "cancelled").
    if outcome.outcome == "cancelled":
        return Approval(
            decision="reject",
            explanation="ACP client cancelled the permission request.",
        )
    option_id = outcome.option_id  # AllowedOutcome
    if option_id in choices:
        # Safe cast: option_id is one of the literal-string members.
        decision: ApprovalDecision = option_id  # type: ignore[assignment]
        return Approval(decision=decision)
    return Approval(
        decision="reject",
        explanation=(
            f"ACP client returned an unknown optionId {option_id!r}; "
            f"valid options were {choices!r}."
        ),
    )


def _assistant_message_block(message: str) -> "ContentToolCallContent | None":
    """Wrap the assistant's accompanying message as a content block.

    The in-proc panel renders the model's text under an
    ``**Assistant**`` header before the view (see
    ``render_tool_approval`` in ``approval/_human/util.py``). Without
    this, the editor sees only the tool call shape and misses the
    "why" the agent gave — under-contextualized for a real approval
    decision. Mirror the in-proc layout in markdown so the editor's
    card renders the same heading + body the panel does.

    Returns ``None`` for an empty / whitespace-only message so we
    don't pad the request with an empty block.
    """
    from acp.schema import ContentToolCallContent, TextContentBlock

    trimmed = message.strip()
    if not trimmed:
        return None
    return ContentToolCallContent(
        type="content",
        content=TextContentBlock(type="text", text=f"**Assistant**\n\n{trimmed}"),
    )


def _build_request(
    *,
    session_id: str,
    message: str,
    call: ToolCall,
    view: ToolCallView,
    choices: list[ApprovalDecision],
) -> RequestPermissionRequest:
    """Construct the ACP request body from Inspect's approval inputs.

    The ``tool_call`` field carries the same rich-content shape we
    already send for live tools: a descriptive title (``bash ls -la``
    rather than just ``bash``), the tool's ``ToolCallView`` content
    as inline markdown, ``raw_input`` for the debug view. Reuses
    :func:`inspect_ai.agent._acp.tool_content.descriptive_title` and
    :func:`content_blocks_from_view` so the approval prompt and the
    live tool-call rendering stay visually consistent in editors.

    Content layout (matches the in-proc panel via
    ``approval/_human/util.py:render_tool_approval``):

    1. **Assistant message** — the model's text accompanying the
       tool call (the "why"). Prepended so the operator sees it
       above the view, same order as the in-proc panel.
    2. **View context** (if any) — current tool state from a
       previous step.
    3. **View call** — what the agent wants to do next.

    The view halves are passed through ``substitute_tool_call_content``
    first so any ``{{param}}`` placeholders in a custom viewer
    resolve to actual argument values — matches the panel's
    rendering and prevents the editor card from showing literal
    ``{{command}}`` / ``{{path}}`` placeholders.
    """
    # Deferred imports to avoid an import cycle through
    # ``inspect_ai.agent._acp.tool_content`` → ``inspect_ai.log._transcript``
    # (which the approval module is loaded too early to participate
    # in at registry-init time). Routing through ACP only fires at
    # actual approval time, so the deferral has no perf cost.
    from inspect_ai.agent._acp.tool_content import (
        content_blocks_from_view,
        descriptive_title,
    )

    title = descriptive_title(call.function, call.arguments)

    # Substitute {{param}} placeholders in the view so the editor
    # sees concrete values, not template syntax. Mirrors
    # render_tool_approval's pre-render step.
    arguments = call.arguments or {}
    substituted_context = (
        substitute_tool_call_content(view.context, arguments)
        if view.context is not None
        else None
    )
    substituted_call = (
        substitute_tool_call_content(view.call, arguments)
        if view.call is not None
        else None
    )

    content_blocks: list[Any] = []
    # 1. Assistant message — prepended so the operator sees the
    # model's reasoning above the tool-call view, matching the
    # in-proc panel's ordering.
    msg_block = _assistant_message_block(message)
    if msg_block is not None:
        content_blocks.append(msg_block)
    # 2. View context (if any).
    if substituted_context is not None:
        from_ctx = content_blocks_from_view(substituted_context)
        if from_ctx:
            content_blocks.extend(from_ctx)
    # 3. View call.
    if substituted_call is not None:
        from_call = content_blocks_from_view(substituted_call)
        if from_call:
            content_blocks.extend(from_call)

    tool_call = ToolCallUpdate(
        tool_call_id=call.id,
        title=title,
        status="pending",
        raw_input=call.arguments,
        # ToolCallUpdate.content is typed as a union including
        # FileEditToolCallContent / TerminalToolCallContent; we
        # only build ContentToolCallContent entries (text blocks
        # wrapping the view's markdown). Cast widens for the schema
        # without changing runtime shape.
        content=cast(Any, content_blocks or None),
    )
    return RequestPermissionRequest(
        session_id=session_id,
        tool_call=tool_call,
        options=_options_from_choices(choices),
    )


async def _request_from_driver_with_fallback(
    clients_in_order: list[ApproverClient],
    request: RequestPermissionRequest,
    choices: list[ApprovalDecision],
) -> Approval | None:
    """Send ``request`` to the driver; fall through to the next on failure.

    ``clients_in_order`` is the session's driver chain (driver first,
    other attached clients in attach order). Single-driver semantics
    replaced the previous broadcast/race model because ACP has no
    protocol-level cancel for outbound requests — broadcasting left
    losing editors with a stale permission card forever. Routing to
    one client at a time means the operator only sees the prompt on
    the client they're actually using.

    Fallback shape: if the driver's request raises (typically
    ``ConnectionError`` on mid-prompt disconnect, or any other
    transport-level failure), move on to the next client in the
    chain. Cancellation (``CancelledError`` from sample-level cancel)
    propagates to the caller; we don't catch it.

    Returns ``None`` when every client in the chain raised — caller
    falls back to the in-proc panel / console flow.

    "Wait forever for a response" matches the in-proc human approver:
    if the driver is connected but the operator is afk, the eval
    blocks. That's the explicit design decision in the original
    Phase 14 doc; not changed here.
    """
    if not clients_in_order:
        return None
    cancel_exc = anyio.get_cancelled_exc_class()
    for client in clients_in_order:
        try:
            response = await client.request_permission(request)
        except cancel_exc:
            raise
        except Exception as exc:
            # Transport failure or other client-side error. Try the
            # next client in the fallback chain. If this was the
            # only one we'll return None at the end.
            logger.debug(
                "ACP approval request failed for client %r; trying next: %s",
                client,
                exc,
            )
            continue
        return _approval_from_response(response, choices)
    return None


async def request_human_approval_via_acp(
    *,
    message: str,
    call: ToolCall,
    view: ToolCallView,
    choices: list[ApprovalDecision],
) -> Approval | None:
    """Route a human-approval prompt through attached ACP clients.

    Returns:
        - An :class:`Approval` when at least one ACP client responded.
        - ``None`` when no ACP clients are attached, when no live
          ACP session is bound for the current sample, when every
          attached client failed (disconnect, transport error), or
          when an unexpected internal error occurred building or
          racing the request. The caller falls through to the
          existing in-proc panel / console human-approval flow in any
          of those cases.

    The ``message`` argument is the assistant text accompanying the
    tool call (the model's reasoning for what it wants to do). The
    in-proc panel renders it under an ``**Assistant**`` header
    above the view; the ACP request prepends an equivalent
    markdown block so the operator sees the same context.

    Hard contract: never propagates a non-cancellation exception to
    the caller. This shim runs synchronously inside
    ``human_approver`` on the agent's tool-call execution path; an
    unhandled exception here would crash the tool call (and could
    crash the eval). On any internal error we log a warning and
    return ``None`` so the caller falls back to the in-proc panel.
    ``CancelledError`` propagates naturally via :func:`acp_guard`'s
    BaseException semantics — sample-level cancel still works.
    """
    with acp_guard(
        "ACP approval routing raised; falling back to in-proc approval flow"
    ):
        # Deferred import — avoids the registry-init-time cycle through
        # the log subsystem; only fires at actual approval time.
        from inspect_ai.log._samples import sample_active

        sample = sample_active()
        if sample is None or sample.acp_session is None:
            return None
        session = sample.acp_session
        if not session.has_approver_clients():
            return None
        request = _build_request(
            session_id=session.session_id,
            message=message,
            call=call,
            view=view,
            choices=choices,
        )
        return await _request_from_driver_with_fallback(
            session.approver_driver_chain(), request, choices
        )
    return None
