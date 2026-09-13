import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from logging import getLogger

from inspect_ai._util.format import format_function_call
from inspect_ai._util.logger import warn_once
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallContent,
    ToolCallView,
    ToolCallViewer,
)
from inspect_ai.util._limit import suspend_token_limit, suspend_turn_limit

from ._policy import ReviewPolicy, policy_reviewer
from ._review import Review
from ._reviewer import Reviewer

logger = getLogger(__name__)


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

    if viewer:
        try:
            view = viewer(call)
            if not view.call:
                view.call = _default_tool_call_viewer(call).call
        except Exception as ex:
            warn_once(
                logger,
                f"Error in viewer for tool '{call.function}': {ex}. "
                "Falling back to default rendering.",
            )
            view = _default_tool_call_viewer(call)
    else:
        view = _default_tool_call_viewer(call)

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


def _default_tool_call_viewer(call: ToolCall) -> ToolCallView:
    return ToolCallView(
        call=ToolCallContent(
            format="markdown",
            content="```python\n"
            + format_function_call(call.function, call.arguments)
            + "\n```\n",
        )
    )


_tool_reviewer: ContextVar[Reviewer | None] = ContextVar("tool_reviewer", default=None)
