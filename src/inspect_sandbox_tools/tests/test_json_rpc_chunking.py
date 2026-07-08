import asyncio
import base64
import json

import pytest
from inspect_sandbox_tools._util.json_rpc_chunking import (
    JSON_RPC_RESPONSE_CHUNK_MARKER,
    JSON_RPC_RESPONSE_CHUNK_METHOD,
    chunk_json_rpc_response_if_needed,
    handle_json_rpc_response_chunk_request,
)


def test_json_rpc_response_chunking_round_trips_large_response(monkeypatch) -> None:
    monkeypatch.setenv("INSPECT_SANDBOX_JSON_RPC_RESPONSE_CHUNK_SIZE", "32")
    original_response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "x" * 200})

    first_response = chunk_json_rpc_response_if_needed(
        {"jsonrpc": "2.0", "method": "large", "id": 1}, original_response
    )
    first_payload = json.loads(first_response)
    first_chunk = first_payload["result"]

    assert (
        first_chunk["__inspect_json_rpc_response_chunk__"]
        == JSON_RPC_RESPONSE_CHUNK_MARKER
    )

    response_bytes = bytearray(base64.b64decode(first_chunk["chunk"]))
    chunk = first_chunk
    while not chunk["done"]:
        next_response = handle_json_rpc_response_chunk_request(
            {
                "jsonrpc": "2.0",
                "method": "__inspect_json_rpc_response_chunk__",
                "params": {
                    "handle": chunk["handle"],
                    "offset": chunk["next_offset"],
                },
                "id": 2,
            }
        )
        chunk = json.loads(next_response)["result"]
        response_bytes.extend(base64.b64decode(chunk["chunk"]))

    assert response_bytes.decode("utf-8") == original_response


def test_json_rpc_response_chunking_leaves_small_response_unwrapped(
    monkeypatch,
) -> None:
    monkeypatch.setenv("INSPECT_SANDBOX_JSON_RPC_RESPONSE_CHUNK_SIZE", "1024")
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "small"})

    assert (
        chunk_json_rpc_response_if_needed(
            {"jsonrpc": "2.0", "method": "small", "id": 1}, response
        )
        == response
    )


def test_cli_chunks_large_in_process_tool_response(
    monkeypatch, tmp_path, capsys
) -> None:
    pytest.importorskip("jsonrpcserver")
    monkeypatch.setenv("INSPECT_SANDBOX_JSON_RPC_RESPONSE_CHUNK_SIZE", "128")
    target = tmp_path / "large.txt"
    target.write_text("x" * 2000)

    first_response = _exec_cli(
        {
            "jsonrpc": "2.0",
            "method": "text_editor",
            "params": {"command": "view", "path": str(target)},
            "id": 1,
        },
        capsys,
    )
    response = _reassemble_chunked_response(first_response, capsys)
    payload = json.loads(response)

    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 1
    assert "x" * 100 in payload["result"]


def _exec_cli(request: dict[str, object], capsys) -> str:
    from inspect_sandbox_tools._cli.main import _exec

    asyncio.run(_exec(json.dumps(request)))
    captured = capsys.readouterr()
    assert captured.err == ""
    return captured.out.strip()


def _reassemble_chunked_response(first_response: str, capsys) -> str:
    payload = json.loads(first_response)
    chunk = payload["result"]
    assert (
        chunk["__inspect_json_rpc_response_chunk__"] == JSON_RPC_RESPONSE_CHUNK_MARKER
    )
    response_bytes = bytearray(base64.b64decode(chunk["chunk"]))

    while not chunk["done"]:
        next_response = _exec_cli(
            {
                "jsonrpc": "2.0",
                "method": JSON_RPC_RESPONSE_CHUNK_METHOD,
                "params": {
                    "handle": chunk["handle"],
                    "offset": chunk["next_offset"],
                },
                "id": 2,
            },
            capsys,
        )
        chunk = json.loads(next_response)["result"]
        assert (
            chunk["__inspect_json_rpc_response_chunk__"]
            == JSON_RPC_RESPONSE_CHUNK_MARKER
        )
        response_bytes.extend(base64.b64decode(chunk["chunk"]))

    return response_bytes.decode("utf-8")
