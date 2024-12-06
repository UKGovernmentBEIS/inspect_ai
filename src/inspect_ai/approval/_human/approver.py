from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

from .._approval import Approval, ApprovalDecision
from .._approver import Approver
from .._registry import approver
from .console import console_approval
from .panel import panel_approval


@approver(name="human")
def human_approver(
    choices: list[ApprovalDecision] = ["approve", "reject", "terminate"],
) -> Approver:
    """Interactive human approver.

    Returns:
       Approver: Interactive human approver.
    """

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        state: TaskState | None = None,
    ) -> Approval:
        # try to use the panel approval (available in fullscreen display)
        try:
            return await panel_approval(message, call, view, state, choices)

        # fallback to plain console approval (available in all displays)
        except NotImplementedError:
            return console_approval(message, view, choices)

    return approve
