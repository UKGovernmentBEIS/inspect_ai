from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

from ._approval import Approval, ApprovalDecision
from ._approver import Approver
from ._registry import approver


@approver(name="auto")
def auto_approver(decision: ApprovalDecision = "approve") -> Approver:
    """Automatically apply a decision to tool calls.

    Args:
       decision (ApprovalDecision): Decision to apply.

    Returns:
       Approver: Auto approver.
    """

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        state: TaskState | None = None,
    ) -> Approval:
        return Approval(decision=decision, explanation="Automatic decision.")

    return approve
