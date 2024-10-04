from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall

from ._approver import Approval, Approver
from ._registry import approver


@approver(name="auto")
def auto_approver() -> Approver:
    """Auto approver.

    Automatically approves all tool calls.

    Returns:
       Approver: Auto approver.
    """

    async def approve(
        tool_call: ToolCall, tool_view: str, state: TaskState | None = None
    ) -> Approval:
        return Approval(decision="approve")

    return approve
