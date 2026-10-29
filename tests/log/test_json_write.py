import io

import pytest

from inspect_ai._util.json import to_json_safe
from inspect_ai.log._recorders.json_write import (
    write_events_data_field,
    write_json_array_field,
    write_json_field,
    write_json_object_field,
)
from inspect_ai.model import ChatMessageUser


@pytest.mark.parametrize("n_items", [0, 3], ids=["empty", "multiple-chunks"])
async def test_streamed_fields_match_monolithic_serialization(n_items: int) -> None:
    content = 'héllo 🎉 日本語 "quoted"'
    events = [{"event": "info", "data": f"{i} {content}"} for i in range(n_items)]
    attachments = {f"hash{i}": f"{i} {content}" for i in range(n_items)}
    events_data = {
        "messages": [ChatMessageUser(content=f"{i} {content}") for i in range(n_items)],
        "calls": [
            {"request": {"messages": [f"{i} {content}"]}} for i in range(n_items)
        ],
    }
    buf = io.BytesIO()
    buf.write(b"{")
    write_json_field(buf, "id", "s1")
    await write_json_array_field(buf, "events", events, comma=True, chunk_size=2)
    await write_json_object_field(
        buf, "attachments", attachments, comma=True, chunk_size=2
    )
    await write_events_data_field(buf, events_data, comma=True, chunk_size=2)
    buf.write(b"}")

    assert buf.getvalue() == to_json_safe(
        {
            "id": "s1",
            "events": events,
            "attachments": attachments,
            "events_data": events_data,
        },
        indent=None,
    )
