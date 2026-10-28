"""Incremental JSON writers for zip log entries."""

import json
from collections.abc import Mapping, Sequence
from typing import Protocol

import anyio.lowlevel

from inspect_ai._util.json import to_json_safe

DEFAULT_JSON_CHUNK_SIZE = 100
"""Items serialized between event-loop checkpoints."""


class BinaryWriteStream(Protocol):
    """Binary sink requiring only write support."""

    def write(self, data: bytes, /) -> int: ...


def write_json_field(
    stream: BinaryWriteStream, name: str, value: object, *, comma: bool = False
) -> None:
    """Write one JSON field, optionally prefixed with a comma."""
    if comma:
        stream.write(b",")
    stream.write(json.dumps(name).encode("utf-8"))
    stream.write(b":")
    stream.write(to_json_safe(value, indent=None))


async def write_json_array_field(
    stream: BinaryWriteStream,
    name: str,
    items: Sequence[object],
    *,
    comma: bool = False,
    chunk_size: int = DEFAULT_JSON_CHUNK_SIZE,
) -> None:
    """Write a JSON array field, yielding between chunks."""
    if comma:
        stream.write(b",")
    stream.write(json.dumps(name).encode("utf-8"))
    stream.write(b":[")
    for start in range(0, len(items), chunk_size):
        if start:
            stream.write(b",")
        stream.write(
            to_json_safe(list(items[start : start + chunk_size]), indent=None)[1:-1]
        )
        await anyio.lowlevel.checkpoint()
    stream.write(b"]")


async def write_json_object_field(
    stream: BinaryWriteStream,
    name: str,
    mapping: Mapping[str, object],
    *,
    comma: bool = False,
    chunk_size: int = DEFAULT_JSON_CHUNK_SIZE,
) -> None:
    """Write an in-memory mapping as a JSON field, yielding between chunks."""
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
    stream: BinaryWriteStream,
    events_data: Mapping[str, object],
    *,
    comma: bool = False,
    chunk_size: int = DEFAULT_JSON_CHUNK_SIZE,
) -> None:
    """Write the events_data field, chunking each pool's array."""
    if comma:
        stream.write(b",")
    stream.write(b'"events_data":{')
    for index, (name, items) in enumerate(events_data.items()):
        # TypedDicts are compatible with Mapping[str, object], requiring narrowing.
        assert isinstance(items, Sequence)
        await write_json_array_field(
            stream, name, items, comma=index > 0, chunk_size=chunk_size
        )
    stream.write(b"}")
