from __future__ import annotations

import json
from typing import Awaitable, Callable

from inspect_ai._util.content import (
    Content,
    ContentAudio,
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
    count_text: Callable[[str], Awaitable[int]],
    count_image: Callable[[ContentImage], Awaitable[int]],
) -> int:
    # Accumulate all text and images to minimize API calls
    text_parts: list[str] = []
    images: list[ContentImage] = []
    fixed_tokens = 0  # For content types with fixed estimates

    def collect_content(content: Content) -> None:
        """Collect text and images from a content item."""
        nonlocal fixed_tokens
        if isinstance(content, ContentText):
            text_parts.append(content.text)
        elif isinstance(content, ContentReasoning):
            # Only count summary - reasoning may be encrypted/redacted
            if content.summary:
                text_parts.append(content.summary)
        elif isinstance(content, ContentImage):
            images.append(content)
        elif isinstance(content, ContentAudio):
            fixed_tokens += 1000  # Conservative estimate
        elif isinstance(content, ContentVideo):
            fixed_tokens += 2000  # Conservative estimate
        elif isinstance(content, ContentDocument):
            fixed_tokens += 1000  # Conservative estimate
        elif isinstance(content, ContentToolUse):
            text_parts.append(content.name)
            text_parts.append(content.arguments)
            text_parts.append(content.result)
            if content.error:
                text_parts.append(content.error)
        # ContentData and unknown types contribute 0 tokens

    # Collect from message content
    if isinstance(message.content, str):
        text_parts.append(message.content)
    else:
        for content in message.content:
            collect_content(content)

    # Collect from tool calls in assistant messages
    if isinstance(message, ChatMessageAssistant) and message.tool_calls:
        for tool_call in message.tool_calls:
            text_parts.append(tool_call.function)
            text_parts.append(json.dumps(tool_call.arguments))

    # Count tokens with single calls
    total_tokens = fixed_tokens

    if text_parts:
        combined_text = "\n".join(text_parts)
        total_tokens += await count_text(combined_text)

    for image in images:
        total_tokens += await count_image(image)

    return max(1, total_tokens)


def count_text_tokens(text: str) -> int:
    # Use tiktoken with o200k_base (200k vocab) for BPE-based token estimation.
    # Most models used for long-horizon agents (Qwen, DeepSeek, Llama 3) have
    # 100k-150k vocabularies, so o200k_base systematically undercounts by ~10%.
    # We add a 10% buffer since undercounting is worse than overcounting when
    # this is used as a trigger for context compaction.
    import tiktoken

    enc = tiktoken.get_encoding("o200k_base")
    token_count = len(enc.encode(text))
    return max(1, int(token_count * 1.1))


def count_image_tokens(image: ContentImage) -> int:
    if image.detail == "low":
        return 85
    else:  # "high" or "auto"
        return 765
