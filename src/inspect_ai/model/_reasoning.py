import base64
import json
import re
from logging import getLogger
from typing import NamedTuple

from pydantic import JsonValue

from inspect_ai._util.content import (
    Content,
    ContentReasoning,
    ContentText,
)
from inspect_ai.model._chat_message import ChatMessage, ChatMessageAssistant

logger = getLogger(__name__)


class ReasoningCapsule(NamedTuple):
    reasoning: str
    signature: str | None = None
    redacted: bool = False
    summary: str | None = None
    internal: JsonValue | None = None


def parse_content_with_reasoning(content: str) -> tuple[str, ReasoningCapsule | None]:
    """
    Looks for and extracts <think/> tags into reasoning text.

    Returns a tuple:
    - The first element is the input content with the <think> tag and its contents fully removed.
    - The second element is a ReasoningCapsule named tuple (or None if no <think> tag is found).
    """
    # Match <think> tag with any attributes
    pattern = r"<think([^>]*)>(.*?)</think>"
    match = re.search(pattern, content, re.DOTALL)

    if match:
        attrs_str = match.group(1)
        reasoning = match.group(2).strip()

        # Parse attributes from opening tag
        signature = _parse_attr(attrs_str, "signature")
        redacted = _parse_attr(attrs_str, "redacted") == "true"
        internal = _parse_internal_attr(attrs_str)

        # Extract nested <summary> tag from content
        reasoning, summary = _parse_summary(reasoning)

        # Remove the matched <think>...</think> from the input
        start, end = match.span()

        return (
            (content[:start] + content[end:]).strip(),
            ReasoningCapsule(
                reasoning=reasoning,
                signature=signature,
                redacted=redacted,
                summary=summary,
                internal=internal,
            ),
        )
    else:
        return content, None


def _parse_attr(attrs_str: str, name: str) -> str | None:
    """Extract attribute value from attributes string."""
    match = re.search(rf'{name}="([^"]*)"', attrs_str)
    return match.group(1) if match else None


def _parse_internal_attr(attrs_str: str) -> JsonValue | None:
    """Extract and JSON-decode the internal attribute value (base64-encoded JSON)."""
    raw = _parse_attr(attrs_str, "internal")
    if raw is None:
        return None
    try:
        decoded = base64.b64decode(raw).decode("utf-8")
        result: JsonValue = json.loads(decoded)
        return result
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None


def _parse_summary(content: str) -> tuple[str, str | None]:
    """Extract <summary> tag from content, returning (remaining_content, summary)."""
    pattern = r"<summary>(.*?)</summary>\s*"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        summary = match.group(1)
        remaining = content[: match.start()] + content[match.end() :]
        return remaining.strip(), summary
    return content, None


def reasoning_to_think_tag(reasoning: "ContentReasoning") -> str:
    """Convert ContentReasoning to a <think> tag string for text-based serialization.

    This is the inverse of parse_content_with_reasoning - it takes a ContentReasoning
    object and produces a <think> tag string that can be embedded in plain text messages
    for agent bridge scenarios.
    """
    attribs = ""
    if reasoning.signature is not None:
        attribs = f'{attribs} signature="{reasoning.signature}"'
    if reasoning.redacted:
        attribs = f'{attribs} redacted="true"'
    if reasoning.internal is not None:
        # Base64 encode the JSON for safe embedding in an attribute
        internal_json = json.dumps(reasoning.internal)
        internal_b64 = base64.b64encode(internal_json.encode("utf-8")).decode("ascii")
        attribs = f'{attribs} internal="{internal_b64}"'

    inner = ""
    if reasoning.summary is not None:
        inner = f"<summary>{reasoning.summary}</summary>\n"
    inner = f"{inner}{reasoning.reasoning}"

    return f"<think{attribs}>\n{inner}\n</think>"


def emulate_reasoning_history(messages: list[ChatMessage]) -> list[ChatMessage]:
    emulated_messages: list[ChatMessage] = []
    for message in messages:
        if isinstance(message, ChatMessageAssistant) and isinstance(
            message.content, list
        ):
            content: list[Content] = []
            for c in message.content:
                if isinstance(c, ContentReasoning):
                    content.append(ContentText(text=reasoning_to_think_tag(c)))
                else:
                    content.append(c)
            message = message.model_copy(update={"content": content})

        emulated_messages.append(message)
    return emulated_messages
