from typing import Protocol

from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

from ._approval import Approval


class Approver(Protocol):
    """Protocol for approvers."""

    async def __call__(
        self,
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        """
        Approve or reject a tool call.

        Args:
            message: Message genreated by the model along with the tool call.
            call: The tool call to be approved.
            view: Custom rendering of tool context and call.
            history: The current conversation history.

        Returns:
            Approval: An Approval object containing the decision and explanation.
        """
        ...
