import base64
import json
import os
import re
import stat
import tempfile
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

JSON_RPC_RESPONSE_CHUNK_METHOD = "__inspect_json_rpc_response_chunk__"
JSON_RPC_RESPONSE_CHUNK_FIELD = "__inspect_json_rpc_response_chunk__"
JSON_RPC_RESPONSE_CHUNK_VERSION = 1
JSON_RPC_RESPONSE_MAX_BYTES_ENV = "INSPECT_SANDBOX_JSON_RPC_RESPONSE_MAX_BYTES"

_DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_CHUNK_BYTES = 512 * 1024
_CHUNK_TTL_SECONDS = 60 * 60
_CHUNK_DIR = Path(tempfile.gettempdir()) / "inspect-sandbox-tools-json-rpc-chunks"
_VALID_HANDLE = re.compile(r"^[0-9a-f]{32}$")


def ensure_json_rpc_response_chunk_dir() -> None:
    """Create the cross-user chunk directory and remove abandoned responses."""
    try:
        _CHUNK_DIR.mkdir(mode=0o733)
    except FileExistsError:
        pass

    chunk_dir_stat = _CHUNK_DIR.lstat()
    if stat.S_ISLNK(chunk_dir_stat.st_mode) or not stat.S_ISDIR(chunk_dir_stat.st_mode):
        raise RuntimeError(
            f"JSON-RPC response chunk path is not a directory: {_CHUNK_DIR}"
        )
    current_uid = os.getuid()
    if chunk_dir_stat.st_uid not in (0, current_uid):
        raise RuntimeError(
            f"JSON-RPC response chunk directory has unexpected owner: {_CHUNK_DIR}"
        )

    # The CLI can drop privileges before an in-process tool returns. Other users
    # therefore need write/search access, while the sticky bit and absent read bit
    # prevent them from deleting or enumerating another request's random handle.
    required_mode = 0o1733
    if chunk_dir_stat.st_uid == current_uid:
        _CHUNK_DIR.chmod(required_mode)
    elif stat.S_IMODE(chunk_dir_stat.st_mode) != required_mode:
        raise RuntimeError(
            f"JSON-RPC response chunk directory has unsafe permissions: {_CHUNK_DIR}"
        )
    _remove_stale_chunks()


def chunk_json_rpc_response_if_needed(
    request_data: dict[str, Any],
    response: str,
    max_response_bytes: int | None = None,
    *,
    chunk_dir_prepared: bool = False,
) -> str:
    """Return a bounded response envelope, spilling large frames to a file."""
    request_id = request_data.get("id")
    if request_id is None:
        return response

    response_bytes = response.encode("utf-8")
    response_limit = _response_byte_limit(max_response_bytes)
    if len(response_bytes) + 1 <= response_limit:
        return response

    if not chunk_dir_prepared:
        ensure_json_rpc_response_chunk_dir()
    handle, chunk_path = _write_response(response_bytes)
    try:
        return _read_chunk_response(request_id, handle, chunk_path, 0, response_limit)
    except Exception:
        chunk_path.unlink(missing_ok=True)
        raise


def handle_json_rpc_response_chunk_request(
    request_data: dict[str, Any], max_response_bytes: int | None = None
) -> str:
    """Fetch or release a previously spilled JSON-RPC response."""
    request_id = request_data.get("id")
    params = request_data.get("params")
    if not isinstance(params, dict):
        return _json_rpc_error(request_id, -32602, "chunk params must be an object")

    handle = params.get("handle")
    if not isinstance(handle, str) or not _VALID_HANDLE.fullmatch(handle):
        return _json_rpc_error(request_id, -32602, "invalid chunk handle")
    chunk_path = _chunk_path(handle)

    if params.get("release") is True:
        chunk_path.unlink(missing_ok=True)
        return _json_rpc_success(request_id, None)
    if "release" in params:
        return _json_rpc_error(request_id, -32602, "release must be true")

    offset = params.get("offset")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return _json_rpc_error(request_id, -32602, "invalid chunk offset")

    try:
        return _read_chunk_response(
            request_id,
            handle,
            chunk_path,
            offset,
            _response_byte_limit(max_response_bytes),
        )
    except FileNotFoundError:
        return _json_rpc_error(request_id, -32000, "chunk handle not found")
    except ValueError as ex:
        return _json_rpc_error(request_id, -32602, str(ex))
    except OSError as ex:
        return _json_rpc_error(request_id, -32000, f"unable to read chunk: {ex}")


def _write_response(response_bytes: bytes) -> tuple[str, Path]:
    while True:
        handle = uuid.uuid4().hex
        chunk_path = _chunk_path(handle)
        try:
            descriptor = os.open(
                chunk_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            continue

        with os.fdopen(descriptor, "wb") as chunk_file:
            chunk_file.write(response_bytes)
        return handle, chunk_path


def _read_chunk_response(
    request_id: Any,
    handle: str,
    chunk_path: Path,
    offset: int,
    max_response_bytes: int,
) -> str:
    total_size = chunk_path.stat().st_size
    if offset >= total_size:
        raise ValueError("chunk offset is beyond the response")

    with chunk_path.open("rb") as chunk_file:
        chunk_file.seek(offset)
        candidate = chunk_file.read(min(_MAX_CHUNK_BYTES, total_size - offset))
    if not candidate:
        raise OSError("chunk file ended before its declared size")

    response = _largest_fitting_chunk_response(
        request_id,
        handle,
        offset,
        total_size,
        candidate,
        max_response_bytes,
    )
    os.utime(chunk_path, None)
    return response


def _largest_fitting_chunk_response(
    request_id: Any,
    handle: str,
    offset: int,
    total_size: int,
    candidate: bytes,
    max_response_bytes: int,
) -> str:
    smallest = _chunk_response(request_id, handle, offset, total_size, candidate[:1])
    if len(smallest.encode("utf-8")) + 1 > max_response_bytes:
        raise ValueError(
            "sandbox exec output limit is too small for a JSON-RPC chunk envelope"
        )

    low = 1
    high = len(candidate)
    best = smallest
    while low <= high:
        size = (low + high) // 2
        response = _chunk_response(
            request_id, handle, offset, total_size, candidate[:size]
        )
        if len(response.encode("utf-8")) + 1 <= max_response_bytes:
            best = response
            low = size + 1
        else:
            high = size - 1
    return best


def _chunk_response(
    request_id: Any,
    handle: str,
    offset: int,
    total_size: int,
    chunk: bytes,
) -> str:
    next_offset = offset + len(chunk)
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            JSON_RPC_RESPONSE_CHUNK_FIELD: {
                "version": JSON_RPC_RESPONSE_CHUNK_VERSION,
                "handle": handle,
                "offset": offset,
                "next_offset": next_offset,
                "total_size": total_size,
                "done": next_offset == total_size,
                "chunk": base64.b64encode(chunk).decode("ascii"),
            },
        },
        separators=(",", ":"),
    )


def _chunk_path(handle: str) -> Path:
    if not _VALID_HANDLE.fullmatch(handle):
        raise ValueError("invalid chunk handle")
    return _CHUNK_DIR / f"{handle}.jsonrpc"


def _response_byte_limit(explicit_limit: int | None) -> int:
    value: int | str | None = explicit_limit
    if value is None:
        value = os.environ.get(JSON_RPC_RESPONSE_MAX_BYTES_ENV)
    if value is None:
        return _DEFAULT_MAX_RESPONSE_BYTES
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_RESPONSE_BYTES
    return limit if limit > 0 else _DEFAULT_MAX_RESPONSE_BYTES


def _remove_stale_chunks() -> None:
    stale_before = time.time() - _CHUNK_TTL_SECONDS
    with suppress(OSError):
        for chunk_path in _CHUNK_DIR.glob("*.jsonrpc"):
            with suppress(OSError):
                if chunk_path.stat().st_mtime < stale_before:
                    chunk_path.unlink()


def _json_rpc_success(request_id: Any, result: object) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "result": result},
        separators=(",", ":"),
    )


def _json_rpc_error(request_id: Any, code: int, message: str) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        },
        separators=(",", ":"),
    )
