import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallViewer,
    resolve_tool_call_view,
)
from inspect_ai.util._limit import suspend_token_limit, suspend_turn_limit

from ._policy import ReviewPolicy, policy_reviewer
from ._review import Review
from ._reviewer import Reviewer


async def apply_tool_review(
    message: str,
    call: ToolCall,
    result: ChatMessageTool,
    output: ToolResult,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage],
) -> Review | None:
    """Apply the active review policies to an executed tool call.

    Returns:
        The review, or `None` when no review policies are registered.
    """
    reviewer = _tool_reviewer.get(None)
    if reviewer is None:
        return None

    view = resolve_tool_call_view(call, viewer)

    # reviewers which use model inference (e.g. LLM monitors) shouldn't have
    # that inference charged to the agent's own budget
    with suspend_token_limit(), suspend_turn_limit():
        return await reviewer(message, call, result, output, view, history)


@contextlib.contextmanager
def review(policies: list[ReviewPolicy]) -> Iterator[None]:
    """Context manager to temporarily replace tool review policies.

    Args:
        policies: Review policies to use within the context.
    """
    token = _tool_reviewer.set(policy_reviewer(policies))
    try:
        yield
    finally:
        _tool_reviewer.reset(token)


def init_tool_review(policies: list[ReviewPolicy] | None) -> None:
    if policies:
        _tool_reviewer.set(policy_reviewer(policies))
    else:
        _tool_reviewer.set(None)


def have_tool_review() -> bool:
    return _tool_reviewer.get(None) is not None


_tool_reviewer: ContextVar[Reviewer | None] = ContextVar("tool_reviewer", default=None)
