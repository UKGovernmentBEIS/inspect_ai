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
    # Clean the input of any images or documents. Messages are copied rather
    # than mutated in place -- callers (e.g. EvalSampleSummary.thin_data) pass
    # message objects shared with the full EvalSample, which must remain intact.
    if isinstance(inputs, list):
        input: list[ChatMessage] = []
        for message in inputs:
            if not isinstance(message.content, str):
                changed = False
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
                            changed = True
                        else:
                            filtered_content.append(content)
                    else:
                        filtered_content.append(
                            ContentText(text=f"({content.type.capitalize()})")
                        )
                        changed = True
                if changed:
                    input.append(
                        message.model_copy(update={"content": filtered_content})
                    )
                else:
                    input.append(message)
            else:
                truncated_text = truncate_text(message.content)
                if truncated_text != message.content:
                    input.append(message.model_copy(update={"content": truncated_text}))
                else:
                    input.append(message)
        return input
    else:
        return truncate_text(inputs)


def thin_target(target: str | list[str]) -> str | list[str]:
    """Thin the target by truncating if necessary."""
    if isinstance(target, list):
        return [truncate_text(t) for t in target]
    else:
        return truncate_text(target)


def truncate_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Truncate text to a maximum length, appending as ellipsis if truncated."""
    if len(text) > max_length:
        return text[:max_length] + "...\n(content truncated)"
    return text


# the width thin_text shortens to, and the input slice it considers.
# textwrap.shorten collapses whitespace across its ENTIRE input before
# truncating, so without the slice a transcript-sized string costs O(len)
# in CPU and allocation *per call*. Only ~the first THIN_TEXT_WIDTH
# characters of collapsed text can survive, so an 8x slice changes the
# result only for pathological mostly-whitespace strings (which lose
# their tail without the "..." placeholder — acceptable for a summary).
THIN_TEXT_WIDTH = 1024
THIN_TEXT_SCAN = THIN_TEXT_WIDTH * 8


def thin_text(text: str) -> str:
    return textwrap.shorten(
        text[:THIN_TEXT_SCAN], width=THIN_TEXT_WIDTH, placeholder="..."
    )


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
