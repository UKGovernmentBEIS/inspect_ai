import base64
import binascii
import json
import re

from pydantic import JsonValue

from inspect_ai._util.content import ContentBase
from inspect_ai._util.json import exceeds_max_depth

CONTENT_INTERNAL_TAG = "content-internal"

MAX_INTERNAL_DEPTH = 100
"""Maximum nesting depth of internal state decoded from a marker.

pydantic validates `internal` to a depth of ~255, but serializing it inside a
message, model call or log fails a few levels short of that, so a deeper
marker would crash the sample after it was read. Provider internal state is
far shallower.
"""


def content_internal_tag(internal: JsonValue) -> str:
    return f"<{CONTENT_INTERNAL_TAG}>{base64.b64encode(json.dumps(internal).encode('utf-8')).decode('utf-8')}</{CONTENT_INTERNAL_TAG}>"


class NotInternal(Exception):
    """A marker that is not internal state written by Inspect, so is literal text."""


def decode_internal(encoded: str) -> JsonValue:
    """Decode the internal state carried by a marker (`content_internal_tag`, `<think internal>`).

    Every marker family decodes through this so they share one rule: a marker is
    internal state only if its body is base64-encoded UTF-8 JSON, nested at most
    `MAX_INTERNAL_DEPTH` deep, that is valid as a content object's `internal`.
    Anything else (e.g. a model quoting a marker) raises `NotInternal`, and the
    caller leaves the whole marker in the text unchanged.

    Raises:
        NotInternal: The marker does not carry internal state.
    """
    try:
        decoded: JsonValue = json.loads(
            base64.b64decode("".join(encoded.split()), validate=True).decode("utf-8")
        )
        if exceeds_max_depth(decoded, MAX_INTERNAL_DEPTH):
            raise ValueError(f"nested deeper than {MAX_INTERNAL_DEPTH}")
        return ContentBase(internal=decoded).internal
    except (binascii.Error, ValueError, TypeError, RecursionError) as ex:
        raise NotInternal() from ex


def parse_content_with_internal(content: str, tag: str) -> tuple[str, JsonValue | None]:
    """
    Extracts and removes a smuggled <internal>...</internal> tag from the content string, if present.

    Note:
        This OpenAI model does not natively use `.internal`. However, in bridge
        scenarios—where output from a model that does use `.internal` is routed
        through this code—such a tag may be present and should be handled.

        Only a tag whose body `decode_internal` accepts (the form
        `content_internal_tag` writes) is internal state. Any other tag is
        literal text (e.g. a model or user quoting the marker) and is left in
        the content unchanged. A body may hold only base64 characters, so a
        quoted opening marker does not extend to the closing marker of a
        tag after it. A quoted tag whose body happens to be base64-encoded
        JSON can't be told apart from internal state and is read as such.

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
            decoded.append(decode_internal(match.group(1)))
        except NotInternal:
            return match.group(0)
        return ""

    stripped = re.sub(rf"<{tag}>([A-Za-z0-9+/=\s]*)</{tag}>", remove_internal, content)
    return (stripped.strip(), decoded[0]) if decoded else (content, None)
