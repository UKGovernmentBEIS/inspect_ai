"""ACP routing for human tool-call approval prompts.

When one or more ACP clients are attached to the running sample
(e.g. Zed connected via ``inspect acp --stdio``), the
``human_approver`` routes its prompts through ACP's
``session/request_permission`` rather than opening the in-proc
Textual panel. When no clients are attached, this module's entry
point returns ``None`` and the caller (``human_approver``) falls
through to the existing panel / console flow — no behavior change
in the no-client case.

Multi-client semantics: broadcast the request to all attached
clients; first non-exception response wins; losing clients'
in-flight tasks are handed to a background drain (ACP has no
protocol-level cancel for outbound requests, so the losing
editors keep showing their permission card until the user clicks
something or the connection drops — only our own pending-request
state is cleaned up). If every client raises (typically
``ConnectionError`` on disconnect mid-prompt), return ``None`` so
the in-proc flow takes over.

Wait-forever: no timeout. The human at the editor is the source
of truth; default-deny on timeout would be surprising and matches
the in-proc human approver's blocking behavior.

Option round-trip: each ``PermissionOption.optionId`` is the
literal :data:`ApprovalDecision` string (``"approve"``,
``"reject"``, etc.) so the response maps back losslessly.

asyncio boundary note
=====================

This module is intentionally **asyncio-bound** (not anyio). The
race awaits asyncio futures returned by ``conn.send_request``
(the ``acp`` library is asyncio-only). The drain-losers pattern
relies on ``asyncio.create_task`` for loose task spawning that
intentionally outlives the race's scope — anyio's structured
concurrency actively prevents this; a migration would require
plumbing a long-lived session-scoped background task group through
to here. The "drain instead of cancel" semantic is what's clean
in asyncio; anyio would be more code, not less. Cancellation
catches use ``anyio.get_cancelled_exc_class()`` so they're
backend-agnostic even though the orchestration is asyncio.
"""

from __future__ import annotations

import asyncio
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


async def _drain_losing_response(task: asyncio.Task[Any]) -> None:
    """Background drain for a loser's in-flight permission request.

    ACP has no protocol-level cancel for outbound requests (no
    ``$/cancelRequest``-style primitive on
    ``session/request_permission``). The losing client's editor keeps
    showing the permission card until the user clicks something or
    disconnects — we can't dismiss it remotely. What we CAN do is
    ensure our own pending-request state is cleaned up by awaiting
    the response (or exception) without blocking the winning
    approval.

    Discards the response. Logs unexpected failures at debug — the
    common cases (disconnect, eventual late click) aren't notable.
    """
    try:
        await task
    except (anyio.get_cancelled_exc_class(), Exception) as exc:
        logger.debug("losing ACP approval request drained: %s", exc)


async def _race_first_response(
    clients: list[ApproverClient],
    request: RequestPermissionRequest,
    choices: list[ApprovalDecision],
) -> Approval | None:
    """Broadcast ``request`` to ``clients``; return first non-error response.

    Uses ``asyncio.wait(..., return_when=FIRST_COMPLETED)`` so a
    successful response from any client immediately wins.

    Losing-client semantics: ACP has no cancel-outbound-request
    primitive, so we can't dismiss the permission card on the
    losing editor. Their card stays open until the user clicks
    something or the connection drops. To avoid a zombie
    pending-request in our own connection state, the in-flight
    losing tasks are handed to a background drain (which awaits
    each loser and discards the response). The race orchestrator
    returns immediately with the winner's decision.

    If every task finishes with an exception (typically
    ``ConnectionError`` from disconnect), returns ``None`` so the
    caller falls back to the in-proc panel / console flow.
    """
    if not clients:
        return None

    tasks = [
        asyncio.create_task(
            client.request_permission(request),
            name=f"acp-approval-{i}",
        )
        for i, client in enumerate(clients)
    ]
    # Track ALL spawned per-client tasks so the finally below can
    # hand any survivors to the background drain — including the
    # case where this race itself is cancelled by the caller (e.g.
    # sample cancellation during a pending approval). Without this
    # finally, a cancelled race leaves per-client tasks orphaned;
    # they'd either fire as "unhandled task exception" if they
    # later raised, or linger forever if the client just never
    # responded.
    try:
        while tasks:
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                exc = task.exception()
                if exc is None:
                    # First success wins. Drain the remaining tasks in
                    # the background — see _drain_losing_response for
                    # why we can't actually cancel the remote requests.
                    response = task.result()
                    for other in pending:
                        asyncio.create_task(
                            _drain_losing_response(other),
                            name="acp-approval-drain",
                        )
                    # Hand-off complete — clear ``tasks`` so the
                    # ``finally`` below doesn't redundantly spawn a
                    # second drain for the same ``pending`` tasks
                    # (legal but produces duplicate debug logs).
                    tasks = []
                    return _approval_from_response(response, choices)
                # Exception — log and keep racing the survivors.
                logger.debug("ACP approval request failed for one client: %s", exc)
            tasks = list(pending)
        return None
    finally:
        # Hand any still-running per-client tasks to the background
        # drain. Covers two cases:
        # 1. Caller cancelled us mid-wait — ``tasks`` and the
        #    iteration's ``pending`` set still contain live tasks.
        # 2. An unexpected exception inside the loop bypassed the
        #    winner-path drain — same survivors.
        # Calling create_task here is safe even during cancellation
        # propagation: the new drain tasks attach to the running
        # loop, not to our cancelled scope. Each drain itself
        # tolerates CancelledError (see _drain_losing_response).
        for task in tasks:
            if not task.done():
                asyncio.create_task(
                    _drain_losing_response(task),
                    name="acp-approval-drain-on-cancel",
                )


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
        return await _race_first_response(session.approver_clients(), request, choices)
    return None
