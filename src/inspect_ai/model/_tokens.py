from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable, Sequence

if TYPE_CHECKING:
    from inspect_ai.tool import ToolInfo

from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentData,
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
    ContentVideo,
)
from inspect_ai.model._chat_message import ChatMessage, ChatMessageAssistant


async def count_tokens(
    message: ChatMessage,
    count_text: Callable[[str], int],
    count_image: Callable[[ContentImage], int],
) -> int:
    def count_content_tokens(content: Content) -> int:
        """Count tokens for a single content item."""
        if isinstance(content, ContentText):
            return count_text(content.text)
        elif isinstance(content, ContentReasoning):
            # Only count summary - reasoning may be encrypted/redacted
            # and replay behavior varies by provider
            if content.summary:
                return count_text(content.summary)
            return 0
        elif isinstance(content, ContentImage):
            return count_image(content)
        elif isinstance(content, ContentAudio):
            return 1000  # Conservative estimate
        elif isinstance(content, ContentVideo):
            return 2000  # Conservative estimate
        elif isinstance(content, ContentDocument):
            return 1000  # Conservative estimate
        elif isinstance(content, ContentToolUse):
            tokens = count_text(content.name)
            tokens += count_text(content.arguments)
            tokens += count_text(content.result)
            return tokens
        elif isinstance(content, ContentData):
            return 0  # Provider-specific, skip
        else:
            return 0

    total_tokens = 0

    # Handle message content
    if isinstance(message.content, str):
        total_tokens += count_text(message.content)
    else:
        for content in message.content:
            total_tokens += count_content_tokens(content)

    # Handle tool calls in assistant messages
    if isinstance(message, ChatMessageAssistant) and message.tool_calls:
        for tool_call in message.tool_calls:
            total_tokens += count_text(tool_call.function)
            args_str = json.dumps(tool_call.arguments)
            total_tokens += count_text(args_str)

    return max(1, total_tokens)


def count_text_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def count_image_tokens(image: ContentImage) -> int:
    if image.detail == "low":
        return 85
    else:  # "high" or "auto"
        return 765
