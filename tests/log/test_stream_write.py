import io
import json

from inspect_ai._util.json import to_json_safe
from inspect_ai.log._recorders._stream_write import (
    write_json_array_field,
    write_json_field,
    write_json_object_field,
)
from inspect_ai.model._chat_message import ChatMessageUser


async def test_streamed_fields_match_monolithic_serialization() -> None:
    events = [{"event": "info", "data": f"payload {i} " * 20} for i in range(257)]
    attachments = {f"hash{i}": f"content {i} " * 30 for i in range(7)}
    buf = io.BytesIO()
    buf.write(b"{")
    write_json_field(buf, "id", "s1")
    write_json_field(buf, "epoch", 1, comma=True)
    await write_json_array_field(buf, "events", events, comma=True, chunk_size=100)
    await write_json_object_field(
        buf, "attachments", attachments, comma=True, chunk_size=3
    )
    buf.write(b"}")

    expected = {"id": "s1", "epoch": 1, "events": events, "attachments": attachments}
    assert json.loads(buf.getvalue()) == json.loads(to_json_safe(expected, indent=None))


async def test_streamed_empty_collections() -> None:
    buf = io.BytesIO()
    buf.write(b"{")
    write_json_field(buf, "id", "s1")
    await write_json_array_field(buf, "events", [], comma=True)
    await write_json_object_field(buf, "attachments", {}, comma=True)
    buf.write(b"}")
    assert json.loads(buf.getvalue()) == {"id": "s1", "events": [], "attachments": {}}


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
