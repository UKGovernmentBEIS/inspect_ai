import base64
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from .constants import SERVER_DIR

JSON_RPC_RESPONSE_CHUNK_METHOD = "__inspect_json_rpc_response_chunk__"
JSON_RPC_RESPONSE_CHUNK_MARKER = "inspect-json-rpc-response-chunk-v1"

_DEFAULT_RESPONSE_CHUNK_SIZE = 64 * 1024
_CHUNK_SIZE_ENV = "INSPECT_SANDBOX_JSON_RPC_RESPONSE_CHUNK_SIZE"
_CHUNK_DIR = SERVER_DIR / "json-rpc-response-chunks"
_VALID_HANDLE = re.compile(r"^[0-9a-f]{32}$")


def ensure_json_rpc_response_chunk_dir() -> None:
    _CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    _CHUNK_DIR.chmod(0o777)


def chunk_json_rpc_response_if_needed(
    request_data: dict[str, Any], response: str
) -> str:
    request_id = request_data.get("id")
    if request_id is None:
        return response

    response_bytes = response.encode("utf-8")
    chunk_size = _response_chunk_size()
    if len(response_bytes) <= chunk_size:
        return response

    ensure_json_rpc_response_chunk_dir()
    handle = uuid.uuid4().hex
    chunk_path = _chunk_path(handle)
    chunk_path.write_bytes(response_bytes)
    chunk_path.chmod(0o666)
    return _chunk_response(request_id, handle, response_bytes, 0, chunk_size)


def handle_json_rpc_response_chunk_request(request_data: dict[str, Any]) -> str:
    request_id = request_data.get("id")
    params = request_data.get("params")
    if not isinstance(params, dict):
        return _json_rpc_error(request_id, -32602, "chunk params must be an object")

    handle = params.get("handle")
    offset = params.get("offset")
    if not isinstance(handle, str) or not _VALID_HANDLE.fullmatch(handle):
        return _json_rpc_error(request_id, -32602, "invalid chunk handle")
    if not isinstance(offset, int) or offset < 0:
        return _json_rpc_error(request_id, -32602, "invalid chunk offset")

    chunk_path = _chunk_path(handle)
    try:
        response_bytes = chunk_path.read_bytes()
    except FileNotFoundError:
        return _json_rpc_error(request_id, -32000, "chunk handle not found")

    return _chunk_response(
        request_id, handle, response_bytes, offset, _response_chunk_size()
    )


def _chunk_response(
    request_id: Any,
    handle: str,
    response_bytes: bytes,
    offset: int,
    chunk_size: int,
) -> str:
    chunk = response_bytes[offset : offset + chunk_size]
    next_offset = offset + len(chunk)
    done = next_offset >= len(response_bytes)
    if done:
        _chunk_path(handle).unlink(missing_ok=True)

    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "__inspect_json_rpc_response_chunk__": JSON_RPC_RESPONSE_CHUNK_MARKER,
                "handle": handle,
                "chunk": base64.b64encode(chunk).decode("ascii"),
                "next_offset": next_offset,
                "done": done,
            },
        }
    )


def _chunk_path(handle: str) -> Path:
    if not _VALID_HANDLE.fullmatch(handle):
        raise ValueError("invalid chunk handle")
    return _CHUNK_DIR / f"{handle}.jsonrpc"


def _response_chunk_size() -> int:
    value = os.environ.get(_CHUNK_SIZE_ENV)
    if value is not None:
        try:
            chunk_size = int(value)
        except ValueError:
            chunk_size = _DEFAULT_RESPONSE_CHUNK_SIZE
        else:
            if chunk_size > 0:
                return chunk_size

    return _DEFAULT_RESPONSE_CHUNK_SIZE


def _json_rpc_error(request_id: Any, code: int, message: str) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }
    )
