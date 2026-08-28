from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.util._notify import notify

from .._approval import Approval, ApprovalDecision
from .._approver import Approver
from .._registry import approver
from .acp import request_human_approval_via_acp
from .console import console_approval
from .panel import panel_approval


@approver(name="human")
def human_approver(
    choices: list[ApprovalDecision] = ["approve", "reject", "terminate"],
) -> Approver:
    """Interactive human approver.

    Args:
       choices: Choices to present to human.

    Returns:
       Approver: Interactive human approver.
    """

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        # deferred: `log._samples` sits below this module in the import
        # graph and reaching it at module load closes a cycle (approval ->
        # log -> transcript -> approval)
        from inspect_ai.log._samples import awaiting_human

        # Ping the operator out-of-band via Apprise (no-op when no
        # notification target is configured) regardless of which
        # surface ultimately collects the response.
        await notify(message)

        # Mark the sample as waiting on a person for the whole dispatch —
        # around all three surfaces rather than inside any one of them. The
        # sample is stopped on a human either way, and nothing else says so
        # while it waits: `call_tool` records the tool's own event only once
        # the approval resolves, so an unmarked wait reads as a silently idle
        # sample on the control channel. The function name travels with it as
        # the request's one structural detail.
        with awaiting_human("approval", call.function):
            # Phase 14: if ACP clients (Zed via `inspect acp --stdio`,
            # the Phase 15 TUI, etc.) are attached to this sample, route
            # the prompt through ACP `session/request_permission` so the
            # operator can respond in the editor they're working in.
            # Returns None when no clients are attached or when every
            # attached client failed (disconnect, transport error) —
            # both cases fall through to the existing in-proc panel /
            # console flow unchanged.
            acp_result = await request_human_approval_via_acp(
                message=message, call=call, view=view, choices=choices
            )
            if acp_result is not None:
                return acp_result

            # try to use the panel approval (available in fullscreen display)
            try:
                return await panel_approval(message, call, view, history, choices)

            # fallback to plain console approval (available in all displays)
            except NotImplementedError:
                return console_approval(message, view, choices, call.arguments)

    return approve
