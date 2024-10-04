from typing import Literal, Protocol

from pydantic import BaseModel

from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall

from ._approval import Approval


class ApproverToolView(BaseModel):
    type: Literal["text", "markdown"]
    content: str


class Approver(Protocol):
    """Protocol for approvers."""

    async def __call__(
        self,
        tool_call: ToolCall,
        tool_view: ApproverToolView,
        state: TaskState | None = None,
    ) -> Approval:
        """
        Approve or reject a tool call.

        Args:
            tool_call (ToolCall): The tool call to be approved.
            tool_view (ApproverToolView): A summary of the tool call and its state and context in markdown format.
            state (state | None): The current task state, if available.

        Returns:
            Approval: An Approval object containing the decision and explanation.
        """
        ...
