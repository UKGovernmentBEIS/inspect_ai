import re
from typing import NamedTuple


class ContentWithReasoning(NamedTuple):
    content: str
    reasoning: str


def parse_content_with_reasoning(content: str) -> ContentWithReasoning | None:
    match = re.match(r"\s*<think>(.*?)</think>(.*)", content, re.DOTALL)
    if match:
        return ContentWithReasoning(
            content=match.group(2).strip(), reasoning=match.group(1).strip()
        )
    else:
        return None
