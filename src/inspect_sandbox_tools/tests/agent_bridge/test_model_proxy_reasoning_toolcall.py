"""Isolate model-proxy Response->SSE conversion for a reasoning + tool-call turn.

The inspect_ai bridge serializes an assistant turn that reasons and then calls a
tool as a Responses ``output`` list of ``[reasoning, function_call]`` (matching
real OpenAI output). The sandboxed agent (opencode) requests ``stream=true``, so
the model proxy must convert that non-streaming ``Response`` into an SSE stream
that still surfaces the trailing ``function_call`` as a tool call.

These tests capture the raw SSE bytes the proxy emits and assert that a strict
streaming client receives the ``function_call`` item (added -> arguments -> done)
even when it is preceded by a ``reasoning`` item that carries only encrypted
content (empty ``content``/``summary``), which is the shape produced for a
redacted / encrypted reasoning turn.
"""

import asyncio
import json
from typing import Any, AsyncGenerator

import pytest
from aiohttp import ClientSession
from inspect_sandbox_tools._agent_bridge.proxy import (
    AsyncHTTPServer,
    model_proxy_server,
)


def _reasoning_then_tool_call_response(
    *,
    reasoning_content: list[dict[str, Any]],
    reasoning_summary: list[dict[str, Any]],
) -> dict[str, Any]:
    """A Responses payload: a reasoning item followed by a function_call."""
    return {
        "id": "resp_reasoning_tool",
        "object": "response",
        "created_at": 1234567890,
        "model": "gpt-5.5",
        "output": [
            {
                "id": "rs_abc123",
                "type": "reasoning",
                "content": reasoning_content,
                "summary": reasoning_summary,
                "encrypted_content": "gAAAAABENCRYPTED_REASONING_BLOB",
            },
            {
                "id": "fc_def456",
                "type": "function_call",
                "call_id": "call_bash_1",
                "name": "bash",
                "arguments": '{"cmd": "ls -la"}',
                "status": "completed",
            },
        ],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 30,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 20},
            "total_tokens": 50,
        },
    }


async def _make_proxy(
    response_payload: dict[str, Any],
) -> AsyncGenerator[tuple[AsyncHTTPServer, str], None]:
    async def mock_bridge_service(
        method: str, json_data: dict[str, Any]
    ) -> dict[str, Any]:
        assert method == "generate_responses"
        return response_payload

    server = await model_proxy_server(
        port=0, call_bridge_model_service_async=mock_bridge_service
    )
    server.server = await asyncio.start_server(
        server._handle_client, server.host, server.port
    )
    port = server.server.sockets[0].getsockname()[1]
    yield server, f"http://127.0.0.1:{port}"
    if server.server:
        server.server.close()
        await server.server.wait_closed()


def _parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse raw SSE text into a list of (event_type, data) tuples."""
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = ""
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if not data_lines:
            continue
        data = json.loads("".join(data_lines))
        events.append((event_type or data.get("type", ""), data))
    return events


async def _stream_responses_raw(base_url: str, payload: dict[str, Any]) -> str:
    async with ClientSession() as session:
        async with session.post(
            f"{base_url}/v1/responses",
            json={"model": "gpt-5.5", "input": "list files", "stream": True},
        ) as resp:
            assert resp.status == 200
            return (await resp.read()).decode("utf-8")


@pytest.mark.asyncio
async def test_redacted_reasoning_then_tool_call_streams_function_call() -> None:
    """Encrypted/empty reasoning must not swallow the trailing function_call."""
    payload = _reasoning_then_tool_call_response(
        reasoning_content=[], reasoning_summary=[]
    )
    gen = _make_proxy(payload)
    _server, base_url = await gen.__anext__()
    try:
        raw = await _stream_responses_raw(base_url, payload)
    finally:
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    events = _parse_sse(raw)
    types = [t for t, _ in events]

    # Lifecycle events present.
    assert "response.created" in types
    assert "response.in_progress" in types
    assert "response.completed" in types

    # The reasoning item is announced ...
    added_items = [
        d["item"]["type"] for t, d in events if t == "response.output_item.added"
    ]
    assert "reasoning" in added_items
    # ... and the trailing function_call is streamed as a real tool call.
    assert "function_call" in added_items
    assert "response.function_call_arguments.delta" in types
    assert "response.function_call_arguments.done" in types

    # The function_call item is completed (opencode dispatches on output_item.done).
    done_items = [d["item"] for t, d in events if t == "response.output_item.done"]
    fc_done = [i for i in done_items if i.get("type") == "function_call"]
    assert len(fc_done) == 1
    assert fc_done[0]["name"] == "bash"
    assert json.loads(fc_done[0]["arguments"]) == {"cmd": "ls -la"}

    # The reasoning item must be announced strictly before the function_call, and
    # the function_call must be fully delivered before response.completed.
    assert types.index("response.output_item.added") < types.index(
        "response.function_call_arguments.done"
    )
    assert types.index("response.function_call_arguments.done") < types.index(
        "response.completed"
    )

    # The final response still carries both output items, in order.
    completed = next(d for t, d in events if t == "response.completed")
    out_types = [o["type"] for o in completed["response"]["output"]]
    assert out_types == ["reasoning", "function_call"]


@pytest.mark.asyncio
async def test_readable_reasoning_then_tool_call_streams_function_call() -> None:
    """Reasoning with visible text must also preserve the trailing function_call."""
    payload = _reasoning_then_tool_call_response(
        reasoning_content=[
            {"type": "reasoning_text", "text": "I should list the files."}
        ],
        reasoning_summary=[{"type": "summary_text", "text": "List files."}],
    )
    gen = _make_proxy(payload)
    _server, base_url = await gen.__anext__()
    try:
        raw = await _stream_responses_raw(base_url, payload)
    finally:
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    events = _parse_sse(raw)
    types = [t for t, _ in events]

    added_items = [
        d["item"]["type"] for t, d in events if t == "response.output_item.added"
    ]
    assert added_items.count("reasoning") == 1
    assert added_items.count("function_call") == 1
    assert "response.reasoning_text.delta" in types
    assert "response.function_call_arguments.done" in types

    completed = next(d for t, d in events if t == "response.completed")
    out_types = [o["type"] for o in completed["response"]["output"]]
    assert out_types == ["reasoning", "function_call"]
