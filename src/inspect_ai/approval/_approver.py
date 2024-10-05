from typing import Literal, Protocol

from pydantic import BaseModel, Field

from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall

from ._approval import Approval


class ApproverContent(BaseModel):
    type: Literal["text", "markdown"]
    content: str


class ApproverToolView(BaseModel):
    context: ApproverContent | None = Field(default=None)
    call: ApproverContent | None = Field(default=None)


class Approver(Protocol):
    """Protocol for approvers."""

    async def __call__(
        self,
        content: str,
        call: ToolCall,
        view: ApproverToolView | None = None,
        state: TaskState | None = None,
    ) -> Approval:
        """
        Approve or reject a tool call.

        Args:
            content (str): Content genreated by the model along with the tool call.
            call (ToolCall): The tool call to be approved.
            view (ApproverToolView): Custom rendering of tool context and call.
            state (state | None): The current task state, if available.

        Returns:
            Approval: An Approval object containing the decision and explanation.
        """
        ...
