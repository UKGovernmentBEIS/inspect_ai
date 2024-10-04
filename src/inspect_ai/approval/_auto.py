from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall

from ._approval import Approval, ApprovalDecision
from ._approver import Approver, ApproverToolView
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
        tool_call: ToolCall, tool_view: ApproverToolView, state: TaskState | None = None
    ) -> Approval:
        return Approval(decision=decision)

    return approve
