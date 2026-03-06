import base64
import json
import re

from pydantic import JsonValue

CONTENT_INTERNAL_TAG = "content-internal"


def content_internal_tag(internal: JsonValue) -> str:
    return f"<{CONTENT_INTERNAL_TAG}>{base64.b64encode(json.dumps(internal).encode('utf-8')).decode('utf-8')}</{CONTENT_INTERNAL_TAG}>"


def parse_content_with_internal(content: str, tag: str) -> tuple[str, JsonValue | None]:
    """
    Extracts and removes a smuggled <internal>...</internal> tag from the content string, if present.

    Note:
        This OpenAI model does not natively use `.internal`. However, in bridge
        scenarios—where output from a model that does use `.internal` is routed
        through this code—such a tag may be present and should be handled.

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
    """
    internal_pattern = rf"<{tag}>(.*?)</{tag}>"
    internal_match = re.search(rf"<{tag}>(.*?)</{tag}>", content, re.DOTALL)

    return (
        (
            re.sub(internal_pattern, "", content, flags=re.DOTALL).strip(),
            json.loads(base64.b64decode(internal_match.group(1)).decode("utf-8")),
        )
        if internal_match
        else (content, None)
    )
