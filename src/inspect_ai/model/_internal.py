import base64
import json
import re
from typing import NamedTuple, cast

from pydantic import JsonValue

CONTENT_INTERNAL_TAG = "content-internal"


class ContentWithInternal(NamedTuple):
    """A text block and the internal value associated with it."""

    text: str
    internal: JsonValue | None


def content_internal_tag(internal: JsonValue) -> str:
    return f"<{CONTENT_INTERNAL_TAG}>{base64.b64encode(json.dumps(internal).encode('utf-8')).decode('utf-8')}</{CONTENT_INTERNAL_TAG}>"


def _content_internal_pattern(tag: str) -> re.Pattern[str]:
    escaped_tag = re.escape(tag)
    return re.compile(rf"<{escaped_tag}>(.*?)</{escaped_tag}>", re.DOTALL)


def _decode_content_internal(match: re.Match[str]) -> JsonValue:
    return cast(
        JsonValue,
        json.loads(base64.b64decode(match.group(1)).decode("utf-8")),
    )


def parse_content_with_internal_blocks(
    content: str, tag: str
) -> list[ContentWithInternal]:
    """Extract all internal values while preserving their text block association.

    Multiple capsules are emitted by bridge serializers immediately after the
    text block they describe. Any text following the final capsule is returned
    as an additional block without internal data.

    Args:
        content: Text that may contain base64-encoded JSON capsules.
        tag: Name of the capsule tag.

    Returns:
        The parsed text blocks in their original order.

    Raises:
        json.JSONDecodeError: If a capsule does not contain valid JSON.
        UnicodeDecodeError: If a capsule does not contain valid UTF-8.
    """
    pattern = _content_internal_pattern(tag)
    matches = list(pattern.finditer(content))
    if not matches:
        return [ContentWithInternal(text=content, internal=None)]

    blocks: list[ContentWithInternal] = []
    cursor = 0
    for match in matches:
        blocks.append(
            ContentWithInternal(
                text=content[cursor : match.start()].strip(),
                internal=_decode_content_internal(match),
            )
        )
        cursor = match.end()

    if trailing_text := content[cursor:].strip():
        blocks.append(ContentWithInternal(text=trailing_text, internal=None))

    return blocks


def parse_content_with_internal(content: str, tag: str) -> ContentWithInternal:
    """
    Extracts and removes a smuggled <internal>...</internal> tag from the content string, if present.

    Note:
        This OpenAI model does not natively use `.internal`. However, in bridge
        scenarios—where output from a model that does use `.internal` is routed
        through this code—such a tag may be present and should be handled.
        Use this helper only for a single provider content block, where at most
        one capsule can be emitted. Callers handling a flattened string of
        multiple text blocks must use `parse_content_with_internal_blocks()`.

    Args:
        content: The input string, possibly containing an <internal> tag with
        base64-encoded JSON.
        tag: The name of the tag for internal data (e.g. <internal>)

    Returns:
        tuple[str, JsonValue | None]:
            - The content string with the <internal>...</internal> tag removed (if present), otherwise the original string.
            - The decoded and parsed internal value (if present), otherwise None.

    Raises:
        json.JSONDecodeError: If the content of the <internal> tag is not valid JSON after decoding.
        UnicodeDecodeError: If the content of the <internal> tag is not valid UTF-8 after base64 decoding.
        ValueError: If more than one internal capsule is present.
    """
    pattern = _content_internal_pattern(tag)
    matches = list(pattern.finditer(content))
    if len(matches) > 1:
        raise ValueError(
            f"Content contains multiple <{tag}> capsules; "
            "use parse_content_with_internal_blocks()"
        )
    if not matches:
        return ContentWithInternal(text=content, internal=None)

    match = matches[0]
    text = f"{content[: match.start()]}{content[match.end() :]}".strip()
    return ContentWithInternal(
        text=text,
        internal=_decode_content_internal(match),
    )
