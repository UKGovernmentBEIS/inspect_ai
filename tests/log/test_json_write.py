"""Tests for the json_write incremental JSON field writers."""

import io
import json

import pytest

from inspect_ai._util.json import to_json_safe
from inspect_ai.log._recorders.json_write import (
    DEFAULT_JSON_CHUNK_SIZE,
    write_events_data_field,
    write_json_array_field,
    write_json_field,
    write_json_object_field,
)
from inspect_ai.model._chat_message import ChatMessageUser

_HOSTILE = 'héllo 🎉 日本語 "quoted"'
"""Multi-byte content plus an embedded quote, to pin the encode/escape split.

Field names are escaped via ``json.dumps``, while mapping keys and values
are serialized by ``to_json_safe`` inside the chunk byte splice; a refactor
to e.g. ``f'"{name}"'.encode()`` breaks on exactly this content.
"""


@pytest.mark.parametrize(
    "n_items",
    [
        0,
        1,
        DEFAULT_JSON_CHUNK_SIZE - 1,
        DEFAULT_JSON_CHUNK_SIZE,
        DEFAULT_JSON_CHUNK_SIZE + 1,
        2 * DEFAULT_JSON_CHUNK_SIZE,
    ],
)
async def test_streamed_fields_match_monolithic_serialization(n_items: int) -> None:
    events = [
        {"event": "info", "data": f"payload {i} {_HOSTILE}"} for i in range(n_items)
    ]
    attachments = {
        f"hash{i} {_HOSTILE}": f"content {i} {_HOSTILE}" for i in range(n_items)
    }
    buf = io.BytesIO()
    buf.write(b"{")
    write_json_field(buf, "id", "s1")
    write_json_field(buf, _HOSTILE, "hostile-field-name", comma=True)
    await write_json_array_field(buf, "events", events, comma=True)
    await write_json_object_field(buf, "attachments", attachments, comma=True)
    buf.write(b"}")

    expected = {
        "id": "s1",
        _HOSTILE: "hostile-field-name",
        "events": events,
        "attachments": attachments,
    }
    assert json.loads(buf.getvalue()) == json.loads(to_json_safe(expected, indent=None))


async def test_streamed_array_serializes_pydantic_values() -> None:
    # events_data message pools hold ChatMessage models, not plain dicts
    messages = [ChatMessageUser(content=f"msg {i}") for i in range(5)]
    buf = io.BytesIO()
    buf.write(b"{")
    await write_json_array_field(buf, "messages", messages, chunk_size=2)
    buf.write(b"}")
    assert json.loads(buf.getvalue()) == json.loads(
        to_json_safe({"messages": messages}, indent=None)
    )


async def test_streamed_events_data_matches_monolithic_serialization() -> None:
    events_data = {
        "messages": [ChatMessageUser(content=f"msg {i}") for i in range(5)],
        "calls": [{"request": {"messages": [f"call {i}"]}} for i in range(3)],
    }
    buf = io.BytesIO()
    buf.write(b'{"id":"s1"')
    await write_events_data_field(buf, events_data, comma=True, chunk_size=2)
    buf.write(b"}")

    expected = b'{"id":"s1","events_data":' + to_json_safe(events_data, indent=None)
    assert buf.getvalue() == expected + b"}"


async def test_streamed_events_data_writes_every_pool() -> None:
    # a pool added to EventsData must not be silently dropped: events keep
    # positional refs into it, so a dropped pool corrupts reads
    events_data = {"messages": [], "calls": [], "futures": [{"x": 1}]}
    buf = io.BytesIO()
    buf.write(b"{")
    await write_events_data_field(buf, events_data)
    buf.write(b"}")
    assert json.loads(buf.getvalue()) == {
        "events_data": {"messages": [], "calls": [], "futures": [{"x": 1}]}
    }
