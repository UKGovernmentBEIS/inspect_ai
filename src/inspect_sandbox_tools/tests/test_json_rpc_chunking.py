import asyncio
import base64
import json
import os
import stat
from typing import Any, NamedTuple, cast

import inspect_sandbox_tools._util.json_rpc_chunking as chunking
import pytest
from inspect_sandbox_tools._util.json_rpc_chunking import (
    JSON_RPC_RESPONSE_CHUNK_FIELD,
    JSON_RPC_RESPONSE_CHUNK_METHOD,
    JSON_RPC_RESPONSE_MAX_BYTES_ENV,
    chunk_json_rpc_response_if_needed,
    handle_json_rpc_response_chunk_request,
)


class _ReassembledResponse(NamedTuple):
    text: str
    offsets: list[int]
    frame_sizes: list[int]
    handle: str


@pytest.fixture(autouse=True)
def isolated_chunk_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(chunking, "_CHUNK_DIR", tmp_path / "chunks")


def test_chunk_dir_accepts_secure_root_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunking._CHUNK_DIR.mkdir(mode=0o1733)
    stat_values = list(chunking._CHUNK_DIR.lstat())
    stat_values[0] = stat.S_IFDIR | 0o1733
    stat_values[4] = 0
    root_owned = os.stat_result(stat_values)
    path_type = type(chunking._CHUNK_DIR)

    monkeypatch.setattr(path_type, "lstat", lambda _self: root_owned)
    monkeypatch.setattr(chunking.os, "getuid", lambda: 1000)

    def unexpected_chmod(_self, _mode: int) -> None:
        raise AssertionError("a non-owner must not chmod the shared directory")

    monkeypatch.setattr(path_type, "chmod", unexpected_chmod)

    chunking.ensure_json_rpc_response_chunk_dir()


def test_json_rpc_response_chunking_round_trips_large_stdout_and_stderr() -> None:
    max_response_bytes = 128 * 1024
    original_response = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "stdout": "stdout-" + "o" * 1_200_000,
                "stderr": "stderr-" + "e" * 1_200_000,
            },
        },
        ensure_ascii=False,
    )

    first_response = chunk_json_rpc_response_if_needed(
        {"jsonrpc": "2.0", "method": "large", "id": 1},
        original_response,
        max_response_bytes,
    )
    reassembled = _reassemble(first_response, max_response_bytes)

    assert reassembled.text == original_response
    assert len(reassembled.offsets) > 2
    assert reassembled.offsets == sorted(reassembled.offsets)
    assert all(size <= max_response_bytes for size in reassembled.frame_sizes)


def test_json_rpc_response_chunking_preserves_split_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chunking, "_MAX_CHUNK_BYTES", 7)
    original_response = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "result": "🙂你好🌍" * 100},
        ensure_ascii=False,
    )

    first_response = chunk_json_rpc_response_if_needed(
        {"jsonrpc": "2.0", "method": "unicode", "id": 1},
        original_response,
        512,
    )
    reassembled = _reassemble(first_response, 512)

    assert reassembled.text == original_response
    assert any(offset % 4 for offset in reassembled.offsets[1:])


def test_json_rpc_response_chunking_leaves_small_response_unwrapped() -> None:
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "small"})

    assert (
        chunk_json_rpc_response_if_needed(
            {"jsonrpc": "2.0", "method": "small", "id": 1}, response, 1024
        )
        == response
    )


def test_json_rpc_response_chunking_rejects_invalid_offsets() -> None:
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "x" * 2000})
    first_response = chunk_json_rpc_response_if_needed({"id": 1}, response, 512)
    chunk = _chunk_metadata(first_response)

    bool_offset = handle_json_rpc_response_chunk_request(
        {"id": 2, "params": {"handle": chunk["handle"], "offset": True}}, 512
    )
    past_end = handle_json_rpc_response_chunk_request(
        {
            "id": 3,
            "params": {
                "handle": chunk["handle"],
                "offset": chunk["total_size"],
            },
        },
        512,
    )

    assert json.loads(bool_offset)["error"]["code"] == -32602
    assert json.loads(past_end)["error"]["code"] == -32602


def test_json_rpc_response_chunks_are_independent_when_interleaved() -> None:
    originals = {
        "a": json.dumps({"jsonrpc": "2.0", "id": 1, "result": "a" * 3000}),
        "b": json.dumps({"jsonrpc": "2.0", "id": 2, "result": "b" * 4000}),
    }
    chunks = {
        name: _chunk_metadata(
            chunk_json_rpc_response_if_needed({"id": index}, response, 512)
        )
        for index, (name, response) in enumerate(originals.items(), start=1)
    }
    buffers = {name: bytearray() for name in originals}

    while chunks:
        for name in list(chunks):
            chunk = chunks[name]
            buffers[name].extend(base64.b64decode(chunk["chunk"], validate=True))
            if chunk["done"]:
                del chunks[name]
                continue
            chunks[name] = _chunk_metadata(
                handle_json_rpc_response_chunk_request(
                    {
                        "id": 10,
                        "params": {
                            "handle": chunk["handle"],
                            "offset": chunk["next_offset"],
                        },
                    },
                    512,
                )
            )

    assert {name: data.decode() for name, data in buffers.items()} == originals


def test_cli_chunks_large_in_process_tool_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pytest.importorskip("jsonrpcserver")
    monkeypatch.setenv(JSON_RPC_RESPONSE_MAX_BYTES_ENV, "512")
    target = tmp_path / "large.txt"
    target.write_text("🙂text-editor-output" * 500)

    first_response = _exec_cli(
        {
            "jsonrpc": "2.0",
            "method": "text_editor",
            "params": {"command": "view", "path": str(target)},
            "id": 1,
        },
        capsys,
    )
    reassembled = _reassemble(first_response, 512, capsys=capsys)
    payload = json.loads(reassembled.text)

    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 1
    assert "🙂text-editor-output" * 10 in payload["result"]


def _exec_cli(request: dict[str, object], capsys: pytest.CaptureFixture[str]) -> str:
    from inspect_sandbox_tools._cli.main import _exec

    asyncio.run(_exec(json.dumps(request)))
    captured = capsys.readouterr()
    assert captured.err == ""
    return captured.out.strip()


def _reassemble(
    first_response: str,
    max_response_bytes: int,
    *,
    capsys: pytest.CaptureFixture[str] | None = None,
) -> _ReassembledResponse:
    chunk = _chunk_metadata(first_response)
    handle = cast(str, chunk["handle"])
    response_bytes = bytearray()
    offsets: list[int] = []
    frame_sizes = [len(first_response.encode("utf-8")) + 1]

    while True:
        offsets.append(cast(int, chunk["offset"]))
        response_bytes.extend(base64.b64decode(chunk["chunk"], validate=True))
        if chunk["done"]:
            break
        request: dict[str, object] = {
            "jsonrpc": "2.0",
            "method": JSON_RPC_RESPONSE_CHUNK_METHOD,
            "params": {"handle": handle, "offset": chunk["next_offset"]},
            "id": 2,
        }
        next_response = (
            _exec_cli(request, capsys)
            if capsys is not None
            else handle_json_rpc_response_chunk_request(request, max_response_bytes)
        )
        frame_sizes.append(len(next_response.encode("utf-8")) + 1)
        chunk = _chunk_metadata(next_response)

    handle_json_rpc_response_chunk_request(
        {"id": 3, "params": {"handle": handle, "release": True}},
        max_response_bytes,
    )
    return _ReassembledResponse(
        response_bytes.decode("utf-8"), offsets, frame_sizes, handle
    )


def _chunk_metadata(response: str) -> dict[str, Any]:
    payload = cast(dict[str, Any], json.loads(response))
    return cast(dict[str, Any], payload[JSON_RPC_RESPONSE_CHUNK_FIELD])
