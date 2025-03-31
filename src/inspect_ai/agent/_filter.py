from typing import Awaitable, Callable

from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)

MessageFilter = Callable[[list[ChatMessage]], Awaitable[list[ChatMessage]]]
"""Filter messages sent to or received from agent handoffs."""


async def remove_tools(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Remove tool calls from messages.

    Removes all instances of `ChatMessageTool` as well as the `tool_calls`
    field from `ChatMessageAssistant`.

    Args:
       messages: Messages to remove tool calls from.

    Returns:
       Messages without tool calls.
    """
    filtered: list[ChatMessage] = []
    for message in messages:
        if isinstance(message, ChatMessageTool):
            continue
        if isinstance(message, ChatMessageAssistant):
            message = message.model_copy(update=dict(tool_calls=None))
        filtered.append(message)

    return filtered


async def last_message(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Remove all but the last message.

    Args:
       messages: Target messages.

    Returns:
       List containing only the last message from the input list.

    """
    return messages[-1:]
