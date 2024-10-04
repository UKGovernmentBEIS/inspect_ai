from typing import Protocol

from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall

from ._approval import Approval


class Approver(Protocol):
    """Protocol for approvers."""

    async def __call__(
        self, tool_call: ToolCall, tool_view: str, state: TaskState | None = None
    ) -> Approval:
        """
        Approve or reject a tool call.

        Args:
            tool_call (ToolCall): The tool call to be approved.
            tool_view (str): A summary of the tool call and its state and context in markdown format.
            state (state | None): The current task state, if available.

        Returns:
            Approval: An Approval object containing the decision and explanation.
        """
        ...
