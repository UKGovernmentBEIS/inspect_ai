from inspect_ai._util.registry import registry_log_name
from inspect_ai.event._review import ReviewEvent
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

from ._review import Review
from ._reviewer import Reviewer


async def call_reviewer(
    reviewer: Reviewer,
    message: str,
    call: ToolCall,
    result: ChatMessageTool,
    output: ToolResult,
    view: ToolCallView,
    history: list[ChatMessage],
) -> Review:
    review = await reviewer(message, call, result, output, view, history)
    record_review(registry_log_name(reviewer), message, call, review)
    return review


def record_review(
    reviewer_name: str,
    message: str,
    call: ToolCall,
    review: Review,
) -> None:
    from inspect_ai.log._transcript import transcript

    transcript()._event(
        ReviewEvent(
            message=message,
            call=call,
            reviewer=reviewer_name,
            decision=review.decision,
            explanation=review.explanation,
            metadata=review.metadata,
        )
    )
