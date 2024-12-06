import asyncio

from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

from .._approval import Approval, ApprovalDecision
from .._approver import Approver
from .._registry import approver
from .console import console_approval
from .panel import ApprovalInputPanel


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
        from inspect_ai._display.core.active import task_screen

        # try to use the input panel ui (fall back to console if its not available)
        try:
            panel = task_screen().input_panel("Approvals", ApprovalInputPanel)

            panel.activate()
            await asyncio.sleep(3)
            panel.close()

            return Approval(
                decision="approve",
                explanation="Human operator approved tool call.",
            )

        # fall back to console
        except NotImplementedError:
            with task_screen().input_screen(width=None) as console:
                return console_approval(console, message, view, choices)

    return approve
