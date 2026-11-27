import base64
import binascii
import json
import re
from typing import Iterator, NamedTuple

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


class ContentWithInternal(NamedTuple):
    """A text block and the internal value associated with it."""

    text: str
    internal: JsonValue | None


class _InternalMatch(NamedTuple):
    start: int
    end: int
    internal: JsonValue


def _content_internal_matches(content: str, tag: str) -> Iterator[_InternalMatch]:
    escaped_tag = re.escape(tag)
    pattern = re.compile(
        rf"(?P<outer><)?<{escaped_tag}>(?P<payload>[A-Za-z0-9+/=\s]*)</{escaped_tag}>(?(outer)>)"
    )
    for match in pattern.finditer(content):
        try:
            internal = decode_internal(match.group("payload"))
        except NotInternal:
            continue
        yield _InternalMatch(start=match.start(), end=match.end(), internal=internal)


def parse_content_with_internal_blocks(
    content: str, tag: str
) -> list[ContentWithInternal]:
    """Extract every internal value with its associated text block.

    Single-wrapped markers and the double-wrapped form emitted by older bridge
    serializers are supported. Only markers accepted by `decode_internal` are
    state; quoted or invalid markers remain literal text.

    Bridge serializers emit a marker immediately after the text it describes.
    Text after the final marker becomes a block without internal data. Newlines
    at marker boundaries are removed; other whitespace, including indentation,
    is retained. If no marker carries internal state, the input is unchanged.

    Args:
        content: Text that may contain base64-encoded JSON markers.
        tag: Name of the internal state tag.

    Returns:
        The parsed text blocks in their original order.
    """
    blocks: list[ContentWithInternal] = []
    cursor = 0
    for match in _content_internal_matches(content, tag):
        blocks.append(
            ContentWithInternal(
                text=content[cursor : match.start].strip("\n"),
                internal=match.internal,
            )
        )
        cursor = match.end

    if not blocks:
        return [ContentWithInternal(text=content, internal=None)]
    if trailing_text := content[cursor:].strip("\n"):
        blocks.append(ContentWithInternal(text=trailing_text, internal=None))
    return blocks


def parse_content_with_internal(content: str, tag: str) -> ContentWithInternal:
    """Extract one internal state marker, leaving other markers as literal text.

    Only markers accepted by `decode_internal` are state. Quoted opening tags
    cannot consume a later state marker. Single- and double-wrapped markers
    are supported. Callers reading flattened text with several state markers
    must use `parse_content_with_internal_blocks` to retain their association.

    Args:
        content: Text that may contain a base64-encoded JSON marker.
        tag: Name of the internal state tag.

    Returns:
        The text with the state marker removed and its decoded internal value,
        or the original text and None if no marker carries internal state.

    Raises:
        ValueError: More than one internal state marker is present.
    """
    matches = list(_content_internal_matches(content, tag))
    if len(matches) > 1:
        raise ValueError(
            f"Content contains multiple <{tag}> capsules; "
            "use parse_content_with_internal_blocks()"
        )
    if not matches:
        return ContentWithInternal(text=content, internal=None)
    match = matches[0]
    return ContentWithInternal(
        text=f"{content[: match.start]}{content[match.end :]}".strip(),
        internal=match.internal,
    )
