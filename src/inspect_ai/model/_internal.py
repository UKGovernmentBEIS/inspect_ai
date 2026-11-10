import base64
import binascii
import json
import re

from pydantic import JsonValue

CONTENT_INTERNAL_TAG = "content-internal"


def content_internal_tag(internal: JsonValue) -> str:
    return f"<{CONTENT_INTERNAL_TAG}>{base64.b64encode(json.dumps(internal).encode('utf-8')).decode('utf-8')}</{CONTENT_INTERNAL_TAG}>"


class _NotInternal(Exception):
    """A tag body that is not internal state written by `content_internal_tag`."""


def _decode_internal(encoded: str) -> JsonValue:
    try:
        decoded: JsonValue = json.loads(
            base64.b64decode(encoded, validate=True).decode("utf-8")
        )
    except (binascii.Error, ValueError) as ex:
        raise _NotInternal() from ex
    return decoded


def parse_content_with_internal(content: str, tag: str) -> tuple[str, JsonValue | None]:
    """
    Extracts and removes a smuggled <internal>...</internal> tag from the content string, if present.

    Note:
        This OpenAI model does not natively use `.internal`. However, in bridge
        scenarios—where output from a model that does use `.internal` is routed
        through this code—such a tag may be present and should be handled.

        Only a tag whose body is base64-encoded UTF-8 JSON (the form
        `content_internal_tag` writes) is internal state. Any other tag is
        literal text (e.g. a model or user quoting the marker) and is left in
        the content unchanged.

    Args:
        content: The input string, possibly containing an <internal> tag with
        base64-encoded JSON.
        tag: The name of the tag for internal data (e.g. <internal>)

    Returns:
        tuple[str, JsonValue | None]:
            - The content string with the decoded <internal>...</internal> tags removed (if present), otherwise the original string.
            - The first decoded internal value (if present), otherwise None.
    """
    decoded: list[JsonValue] = []

    def remove_internal(match: re.Match[str]) -> str:
        try:
            decoded.append(_decode_internal(match.group(1)))
        except _NotInternal:
            return match.group(0)
        return ""

    stripped = re.sub(
        rf"<{tag}>(.*?)</{tag}>", remove_internal, content, flags=re.DOTALL
    )
    return (stripped.strip(), decoded[0]) if decoded else (content, None)
