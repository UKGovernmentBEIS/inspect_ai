import json
import re
from logging import getLogger
from typing import Annotated, Any, Literal, NamedTuple, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from inspect_ai._util.content import (
    ContentReasoning,
)

logger = getLogger(__name__)


class ReasoningCapsule(NamedTuple):
    reasoning: str
    signature: str | None = None
    redacted: bool = False
    summary: str | None = None


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
            ),
        )
    else:
        return content, None


def _parse_attr(attrs_str: str, name: str) -> str | None:
    """Extract attribute value from attributes string."""
    match = re.search(rf'{name}="([^"]*)"', attrs_str)
    return match.group(1) if match else None


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

    inner = ""
    if reasoning.summary is not None:
        inner = f"<summary>{reasoning.summary}</summary>\n"
    inner = f"{inner}{reasoning.reasoning}"

    return f"<think{attribs}>\n{inner}\n</think>"


OPENROUTER_REASONING_DETAILS_SIGNATURE = "reasoning-details://"


class ReasoningDetailBase(BaseModel):
    id: str | None = Field(default=None)
    format: str | None = Field(default=None)
    index: int | None = Field(default=None)


class ReasoningDetailSummary(ReasoningDetailBase):
    type: Literal["reasoning.summary"]
    summary: str


class ReasoningDetailEncrypted(ReasoningDetailBase):
    type: Literal["reasoning.encrypted"]
    data: str


class ReasoningDetailText(ReasoningDetailBase):
    type: Literal["reasoning.text"]
    text: str
    signature: str | None = Field(default=None)


ReasoningDetail = Annotated[
    Union[ReasoningDetailSummary, ReasoningDetailEncrypted, ReasoningDetailText],
    Field(discriminator="type"),
]


# openrouter uses reasoning_details
# https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#responses-api-shape
def openrouter_reasoning_details_to_reasoning(
    reasoning_details: list[dict[str, Any]],
) -> ContentReasoning:
    # store the full data structure in the signature for replay
    details_json = json.dumps(reasoning_details)
    signature = f"{OPENROUTER_REASONING_DETAILS_SIGNATURE}{details_json}"

    # attempt to parse out the details
    try:
        adapter = TypeAdapter(list[ReasoningDetail])
        details = adapter.validate_python(reasoning_details)
    except ValidationError as ex:
        logger.warning(
            f"Error parsing OpenRouter reasoning details: {ex}\n\n{details_json}"
        )
        return ContentReasoning(reasoning=details_json, signature=signature)

    # collect reasoning fields from details
    reasoning: str | None = None
    summary: str | None = None
    redacted: bool = False
    for detail in details:
        match detail.type:
            case "reasoning.summary":
                summary = detail.summary
            case "reasoning.text":
                reasoning = detail.text
            case "reasoning.encrypted":
                reasoning = detail.data
                redacted = True

    # resolve reasoning
    if reasoning is None:
        # summary becomes reasoning if there is no reasoning
        if summary is not None:
            reasoning = summary
            summary = None
        # otherwise this an unepxected state
        else:
            logger.warning(
                f"Error parsing OpenRouter reasoning details: Reasoning content not provided.\n\n{details_json}"
            )
            return ContentReasoning(reasoning=details_json, signature=signature)

    # return reasoning
    return ContentReasoning(
        reasoning=reasoning, summary=summary, redacted=redacted, signature=signature
    )


def reasoning_to_openrouter_reasoning_details(
    content: ContentReasoning,
) -> dict[str, Any] | None:
    if content.signature and content.signature.startswith(
        OPENROUTER_REASONING_DETAILS_SIGNATURE
    ):
        return {
            "reasoning_details": json.loads(
                content.signature.replace(OPENROUTER_REASONING_DETAILS_SIGNATURE, "", 1)
            )
        }

    # default to no handling
    return None
