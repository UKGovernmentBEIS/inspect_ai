import textwrap
from datetime import date, datetime, time
from typing import Any

from inspect_ai._util.content import (
    ContentAudio,
    ContentData,
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
    ContentVideo,
)
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.model._chat_message import ChatMessage

# the maximum length of summary inputs
MAX_TEXT_LENGTH = 5120


def thin_input(inputs: str | list[ChatMessage]) -> str | list[ChatMessage]:
    # Clean the input of any images or documents
    if isinstance(inputs, list):
        input: list[ChatMessage] = []
        for message in inputs:
            if not isinstance(message.content, str):
                filtered_content: list[
                    ContentText
                    | ContentReasoning
                    | ContentToolUse
                    | ContentImage
                    | ContentAudio
                    | ContentVideo
                    | ContentData
                    | ContentDocument
                ] = []
                for content in message.content:
                    if content.type == "text":
                        truncated_input = truncate_text(content.text)
                        if content.text != truncated_input:
                            truncated_content = ContentText(
                                text=truncated_input,
                                citations=content.citations,
                                refusal=content.refusal,
                            )
                            filtered_content.append(truncated_content)
                        else:
                            filtered_content.append(content)
                    else:
                        filtered_content.append(
                            ContentText(text=f"({content.type.capitalize()})")
                        )
                message.content = filtered_content
                input.append(message)
            else:
                message.content = truncate_text(message.content)
                input.append(message)
        return input
    else:
        return truncate_text(inputs)


def truncate_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Truncate text to a maximum length, appending as ellipsis if truncated."""
    if len(text) > max_length:
        return text[:max_length] + "...\n(content truncated)"
    return text


def thin_text(text: str) -> str:
    return textwrap.shorten(text, width=1024, placeholder="...")


def thin_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    thinned: dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, int | float | bool | date | time | datetime):
            thinned[key] = value
        elif isinstance(value, str):
            thinned[key] = thin_text(value)
        else:
            size = len(to_json_str_safe(value))
            if size <= 1024:
                thinned[key] = value
            else:
                thinned[key] = "Key removed from summary (> 1k)"
    return thinned
