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
    from inspect_ai.tool._tool_call import ToolCallContent

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


def _format_view_content_as_markdown(
    view_content: "ToolCallContent",
) -> "ToolCallContent":
    """Bake title heading + format hint into the markdown text.

    The result has ``format="markdown"`` and ``content`` that
    includes a bold title heading (if ``view_content.title`` is set)
    and — for non-markdown source — a fenced code block around the
    body so whitespace / indentation are preserved by any markdown
    renderer.

    This is what lets the inline approval section (in the TUI) and
    any other ACP client (Zed etc.) render the same visual structure
    as the in-proc ``ApprovalPanel``'s ``render_tool_approval``
    output (bold per-half titles, code fencing for plain text)
    without needing any non-standard ``_meta`` markers on the wire.
    """
    from inspect_ai.tool._tool_call import ToolCallContent

    parts: list[str] = []
    if view_content.title:
        parts.append(f"**{view_content.title}**")
        parts.append("")  # blank line between heading and body
    if view_content.format == "markdown":
        parts.append(view_content.content)
    else:
        # Fence plain text so the renderer treats it as preformatted
        # (preserves indentation; avoids markdown reinterpretation).
        # Pick a fence longer than any backtick run in the content so
        # text containing literal ``` (e.g. a viewer dumping help
        # output, or a tool printing markdown source) doesn't break
        # out of the fence and render as live markdown.
        fence = _safe_code_fence(view_content.content)
        parts.append(fence)
        parts.append(view_content.content)
        parts.append(fence)
    return ToolCallContent(
        title=None,
        format="markdown",
        content="\n".join(parts),
    )


def _safe_code_fence(content: str) -> str:
    """Return a backtick fence longer than any backtick run in ``content``.

    CommonMark / GFM rule: a fenced code block opened with N
    backticks closes at the next line whose fence has at least N
    backticks. Pick ``max_run + 1`` so the close fence we emit
    can't be matched by anything embedded in the content.

    Minimum length 3 — keeps standard plaintext (no backticks at
    all) wrapped in the familiar ``` fence.
    """
    max_run = 0
    cur_run = 0
    for ch in content:
        if ch == "`":
            cur_run += 1
            if cur_run > max_run:
                max_run = cur_run
        else:
            cur_run = 0
    return "`" * max(3, max_run + 1)


def _separator_block() -> "ContentToolCallContent":
    """A ``---`` markdown horizontal-rule block.

    Inserted between ``view.context`` and ``view.call`` when both
    are present so the rendered card mirrors the in-proc panel's
    ``Rule(characters="․")`` separator (``render_tool_approval`` in
    ``approval/_human/util.py``). Any markdown renderer draws this
    as a horizontal line; no protocol extension required.

    Body is just ``"---"`` — no surrounding newlines. Each
    ``ContentToolCallContent`` block is rendered as its own
    structural unit by every ACP client we target (each goes into
    a separate widget on our TUI, a separate Markdown block in
    Zed), so the rule is already on a line by itself. Leading /
    trailing newlines here would render as redundant blank rows
    on top of the inline section's per-block margin, doubling the
    vertical gap around the divider.
    """
    from acp.schema import ContentToolCallContent, TextContentBlock

    return ContentToolCallContent(
        type="content",
        content=TextContentBlock(type="text", text="---"),
    )


def _build_request(
    *,
    session_id: str,
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

    Content layout — diverges from the in-proc
    ``ApprovalPanel`` / ``render_tool_approval`` in NOT including
    the model's accompanying message text. That text already streams
    to the client as a normal ``agent_message_chunk`` notification
    and renders as an assistant chip in the conversation immediately
    above the tool-call card (the approval shim's drain barrier
    guarantees it arrives BEFORE the permission request); embedding
    it AGAIN inside the approval card would duplicate the same text
    a few rows apart. The panel needs to be self-contained because
    it's a separate UI surface; the inline approval card lives in
    the transcript flow where the assistant chip is right there.

    1. **View context** (if any) — current tool state from a
       previous step.
    2. **View call** — what the agent wants to do next.

    The view halves are passed through ``substitute_tool_call_content``
    first so any ``{{param}}`` placeholders in a custom viewer
    resolve to actual argument values — prevents the editor card
    from showing literal ``{{command}}`` / ``{{path}}`` placeholders.
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
    # The model's accompanying message (the "why" the agent gave
    # for this tool call) is deliberately NOT included in the
    # approval request. It already flows to the client as a normal
    # ``agent_message_chunk`` notification — rendered as an
    # assistant chip in the conversation stream immediately above
    # the tool-call card. Embedding it again inside the approval
    # card just duplicated the same text a few rows apart. Diverges
    # from the in-proc ``ApprovalPanel`` (which is a separate
    # surface and needs to be self-contained) — see the comment in
    # ``_build_request`` below.
    # 1. View context (if any). Title baked into the markdown via
    # _format_view_content_as_markdown so any renderer shows it as
    # a bold heading.
    context_blocks = (
        content_blocks_from_view(_format_view_content_as_markdown(substituted_context))
        if substituted_context is not None
        else None
    )
    call_blocks = (
        content_blocks_from_view(_format_view_content_as_markdown(substituted_call))
        if substituted_call is not None
        else None
    )
    if context_blocks:
        content_blocks.extend(context_blocks)
    # Markdown rule between context and call mirrors the in-proc
    # panel's Rule separator (render_tool_approval in
    # approval/_human/util.py).
    if context_blocks and call_blocks:
        content_blocks.append(_separator_block())
    if call_blocks:
        content_blocks.extend(call_blocks)

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
        # Drain pending ``session/update`` notifications BEFORE the
        # request goes out, so the operator sees the model's
        # accompanying ``agent_message_chunk`` (the "why" the agent
        # gave) above the approval card rather than AFTER it (or
        # never, if they decide before the chunk arrives).
        # Notifications travel via the in-process pub/sub bus +
        # per-connection forwarder task, while ``request_permission``
        # calls ``conn.send_request`` directly on the agent task —
        # without this barrier the request can win the race to the
        # wire and the operator decides with no narration context.
        # See the ``Forwarders.drain`` docstring for the ordering
        # mechanics.
        #
        # Drain is BEST-EFFORT ordering, NOT a gate on whether the
        # request goes out. If drain itself raises a non-cancel
        # exception (e.g. an unexpected Python-level bug in the
        # statistics() call), log + proceed with the request —
        # otherwise a drain bug would silently skip the driver and
        # route the approval to a fallback client (or to nothing),
        # which is a worse failure mode than slightly-out-of-order
        # notifications.
        try:
            await client.drain_notifications()
        except cancel_exc:
            raise
        except Exception as drain_exc:
            logger.warning(
                "ACP approval drain_notifications failed for client %r; "
                "proceeding with request anyway: %s",
                client,
                drain_exc,
            )
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

    The ``message`` argument (the assistant text accompanying the
    tool call) is accepted for signature parity with the in-proc
    ``panel_approval`` / ``console_approval`` paths, but the ACP
    flow deliberately does NOT forward it on the wire — the same
    text already streams to attached clients as a normal
    ``agent_message_chunk`` notification (rendered as an assistant
    chip in the conversation above the tool-call card). The drain
    barrier in :func:`_request_from_driver_with_fallback` ensures
    the chunk lands BEFORE the permission request so the operator
    sees the "why" above the approval card. See the
    :func:`_build_request` docstring for the full rationale.

    Hard contract: never propagates a non-cancellation exception to
    the caller. This shim runs synchronously inside
    ``human_approver`` on the agent's tool-call execution path; an
    unhandled exception here would crash the tool call (and could
    crash the eval). On any internal error we log a warning and
    return ``None`` so the caller falls back to the in-proc panel.
    ``CancelledError`` propagates naturally via :func:`acp_guard`'s
    BaseException semantics — sample-level cancel still works.
    """
    del message  # accepted for signature parity; see docstring above
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
            call=call,
            view=view,
            choices=choices,
        )
        return await _request_from_driver_with_fallback(
            session.approver_driver_chain(), request, choices
        )
    return None
