"""Incremental JSON writers for zip log entries.

Shared by the live streaming recorder (``buffer_sample_streaming``) and the
filestore recovery writer: one idiom for writing a JSON object entry
field-by-field, so whole-sample payloads never need a single monolithic
jsonable tree + byte blob.
"""

import json
from collections.abc import Mapping, Sequence
from typing import IO, Any

import anyio.lowlevel

from inspect_ai._util.json import to_json_safe

JSON_STREAM_CHUNK = 100
"""Items serialized per chunk when streaming arrays/objects.

Bounds both the transient memory (one chunk's jsonable tree + bytes) and
the time between event-loop checkpoints. A perf knob, not a correctness
knob: any positive value produces identical JSON.
"""


def write_json_field(
    stream: IO[bytes], name: str, value: object, comma: bool = False
) -> None:
    """Write a single JSON field (``"name": value``) to a binary stream.

    Args:
        stream: Writable binary stream.
        name: JSON key.
        value: Value to serialize via ``to_json_safe``.
        comma: If True, prepend a comma separator.
    """
    if comma:
        stream.write(b",")
    stream.write(json.dumps(name).encode("utf-8"))
    stream.write(b":")
    stream.write(to_json_safe(value, indent=None))


async def write_json_array_field(
    stream: IO[bytes],
    name: str,
    items: Sequence[Any],
    *,
    comma: bool = False,
    chunk_size: int = JSON_STREAM_CHUNK,
) -> None:
    """Write ``"name": [...]``, serializing ``items`` in chunks.

    Yields to the event loop between chunks so a large array cannot
    monopolize it. Each chunk is serialized independently; the emitted
    bytes parse identically to a monolithic serialization.
    """
    if comma:
        stream.write(b",")
    stream.write(json.dumps(name).encode("utf-8"))
    stream.write(b":[")
    for start in range(0, len(items), chunk_size):
        if start:
            stream.write(b",")
        # strip the chunk's surrounding [] and splice into the outer array
        stream.write(
            to_json_safe(list(items[start : start + chunk_size]), indent=None)[1:-1]
        )
        await anyio.lowlevel.checkpoint()
    stream.write(b"]")


async def write_json_object_field(
    stream: IO[bytes],
    name: str,
    mapping: Mapping[str, Any],
    *,
    comma: bool = False,
    chunk_size: int = JSON_STREAM_CHUNK,
) -> None:
    """Write ``"name": {...}``, serializing ``mapping`` in item chunks."""
    if comma:
        stream.write(b",")
    stream.write(json.dumps(name).encode("utf-8"))
    stream.write(b":{")
    items = list(mapping.items())
    for start in range(0, len(items), chunk_size):
        if start:
            stream.write(b",")
        stream.write(
            to_json_safe(dict(items[start : start + chunk_size]), indent=None)[1:-1]
        )
        await anyio.lowlevel.checkpoint()
    stream.write(b"}")


async def write_events_data_field(
    stream: IO[bytes],
    events_data: Mapping[str, Any],
    *,
    comma: bool = False,
    chunk_size: int = JSON_STREAM_CHUNK,
) -> None:
    """Write the complete ``"events_data": {...}`` field, one chunked array per pool.

    Iterates the mapping rather than hardcoding pool names so a pool added to
    ``EventsData`` cannot be silently dropped (pool refs are positional, so a
    dropped pool corrupts reads instead of failing cleanly), and so the caller
    never owns the field's inner braces.
    """
    if comma:
        stream.write(b",")
    stream.write(b'"events_data":{')
    for index, (name, items) in enumerate(events_data.items()):
        await write_json_array_field(
            stream, name, items, comma=index > 0, chunk_size=chunk_size
        )
    stream.write(b"}")
