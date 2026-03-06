from typing import Awaitable, Callable

from inspect_ai._util.content import (
    Content,
    ContentReasoning,
    ContentText,
    ContentToolUse,
)
from inspect_ai._util.format import format_function_call
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)

MessageFilter = Callable[[list[ChatMessage]], Awaitable[list[ChatMessage]]]
"""Filter messages sent to or received from agent handoffs."""


async def content_only(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Remove (or convert) message history to pure content.

    This is the default filter for agent handoffs and is intended to
    present a history that doesn't confound the parent model with
    tools it doesn't have, reasoning traces it didn't create, etc.

    - Removes system messages
    - Removes reasoning traces
    - Removes `internal` attribute on content
    - Converts tool calls to user messages
    - Converts server tool calls to text

    Args:
        messages: Messages to filter.

    Returns:
        Messages with content only.
    """
    filtered: list[ChatMessage] = []
    for message in messages:
        # ignore system messages
        if isinstance(message, ChatMessageSystem):
            continue

        # pass through user messages
        elif isinstance(message, ChatMessageUser):
            filtered.append(message)

        # convert tool messages to user messages
        elif isinstance(message, ChatMessageTool):
            filtered.append(ChatMessageUser(id=message.id, content=message.content))

        # filter assistant content
        else:
            # ensure content block
            if isinstance(message.content, str):
                content: list[Content] = [ContentText(text=message.content)]
            else:
                content = message.content

            # append tool calls as plain content
            tool_calls = "\n".join(
                [
                    format_function_call(call.function, call.arguments)
                    for call in (message.tool_calls or [])
                ]
            )
            if tool_calls:
                content.append(ContentText(text=tool_calls))

            # remove reasoning and internal
            content = [
                c.model_copy(update={"internal": None})
                for c in content
                if not isinstance(c, ContentReasoning)
            ]

            # replace server side tool use with context text
            content = [
                ContentText(text=f"{c.name} {c.arguments}\n\n{c.result}")
                if isinstance(c, ContentToolUse)
                else c
                for c in content
            ]

            # append message with updated content and tool call
            filtered.append(
                message.model_copy(update={"content": content, "tool_calls": None})
            )

    return filtered


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
