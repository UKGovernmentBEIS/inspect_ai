import re
from typing import NamedTuple


class ContentWithReasoning(NamedTuple):
    content: str
    reasoning: str
    signature: str | None = None
    redacted: bool = False


def parse_content_with_reasoning(content: str) -> ContentWithReasoning | None:
    # Match <think> tag with optional attributes
    pattern = r'\s*<think(?:\s+signature="([^"]*)")?(?:\s+redacted="(true)")?\s*>(.*?)</think>(.*)'
    match = re.match(pattern, content, re.DOTALL)

    if match:
        signature = match.group(1)  # This will be None if not present
        redacted_value = match.group(2)  # This will be "true" or None
        reasoning = match.group(3).strip()
        content_text = match.group(4).strip()

        return ContentWithReasoning(
            content=content_text,
            reasoning=reasoning,
            signature=signature,
            redacted=redacted_value == "true",
        )
    else:
        return None
