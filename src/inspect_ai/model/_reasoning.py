import re
from typing import NamedTuple


class ContentWithReasoning(NamedTuple):
    content: str
    reasoning: str
    signature: str | None = None
    redacted: bool = False


def parse_content_with_reasoning(content: str) -> ContentWithReasoning | None:
    """
    Looks for and extracts <think/> tags into reasoning text.

    If the result is non-None, the returned `ContentWithReasoning` named tuple will have:
    - `reasoning`: the text inside the <think> tag
    - `content`: the input content with the <think> tag and its contents fully removed
    - `signature` and `redacted`: values from the <think> tag attributes, if present

    In other words, `content` is the original input minus the <think> tag and its contents.
    """
    # Match <think> tag with optional attributes anywhere in the string
    pattern = (
        r'<think(?:\s+signature="([^"]*)")?(?:\s+redacted="(true)")?\s*>(.*?)</think>'
    )
    match = re.search(pattern, content, re.DOTALL)

    if match:
        signature = match.group(1)  # This will be None if not present
        redacted_value = match.group(2)  # This will be "true" or None
        reasoning = match.group(3).strip()
        # Remove the matched <think>...</think> from the input
        start, end = match.span()
        content_text = (content[:start] + content[end:]).strip()

        return ContentWithReasoning(
            content=content_text,
            reasoning=reasoning,
            signature=signature,
            redacted=redacted_value == "true",
        )
    else:
        return None
