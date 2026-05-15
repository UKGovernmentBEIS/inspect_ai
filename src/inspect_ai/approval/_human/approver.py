from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

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
