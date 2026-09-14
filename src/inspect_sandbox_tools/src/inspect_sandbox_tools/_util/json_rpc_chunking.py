"""Spill oversized JSON-RPC responses to files and serve them back in pieces.

Chunk files live in a private directory beside the server's state files, so
only the tools user can create, replace, or read them. When the CLI switches
to a sandbox user before running an in-process tool, it reserves the spill file
first: an open descriptor stays writable after setuid while the directory does
not, so the sandbox user's response still lands in tools-user storage, and the
tools user serves the continuations from there.
"""

import base64
import fcntl
import json
import os
import re
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, BinaryIO, NamedTuple

from inspect_sandbox_tools._util.constants import SERVER_DIR
from inspect_sandbox_tools._util.server_dir import ensure_private_server_dir

JSON_RPC_RESPONSE_CHUNK_METHOD = "__inspect_json_rpc_response_chunk__"
JSON_RPC_RESPONSE_CHUNK_FIELD = "__inspect_json_rpc_response_chunk__"
JSON_RPC_RESPONSE_CHUNK_VERSION = 1
JSON_RPC_RESPONSE_MAX_BYTES_ENV = "INSPECT_SANDBOX_JSON_RPC_RESPONSE_MAX_BYTES"

_DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_CHUNK_BYTES = 512 * 1024
_CHUNK_TTL_SECONDS = 60 * 60
_RESERVATION_GRACE_SECONDS = 60
_VALID_HANDLE = re.compile(r"^[0-9a-f]{32}$")

_CHUNK_DIR = SERVER_DIR / "chunks"


class ChunkSpill(NamedTuple):
    """A reserved chunk file, held open and locked by the process that made it."""

    handle: str
    file: BinaryIO


def open_chunk_spill() -> ChunkSpill:
    """Reserve a chunk file for a response that does not exist yet.

    The CLI calls this as the tools user before switching to a sandbox user.
    The file is created exclusively and locked; the lock marks it as live to
    the stale sweep and is released when the process exits, so a reservation
    that turned out to be unneeded is swept as an empty orphan by a later call.
    """
    chunk_dir = _chunk_dir()
    _remove_stale_chunks(chunk_dir)
    while True:
        handle = uuid.uuid4().hex
        try:
            fd = os.open(
                chunk_dir / _chunk_name(handle),
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                0o600,
            )
        except FileExistsError:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.fchmod(fd, 0o600)  # the umask may have masked owner bits
        except BaseException:
            os.close(fd)
            raise
        return ChunkSpill(handle, os.fdopen(fd, "rb+"))


def _chunk_dir() -> Path:
    ensure_private_server_dir(_CHUNK_DIR.parent)
    ensure_private_server_dir(_CHUNK_DIR)
    return _CHUNK_DIR


def chunk_json_rpc_response_if_needed(
    request_data: dict[str, Any],
    response: str,
    max_response_bytes: int | None = None,
    spill: ChunkSpill | None = None,
) -> str:
    """Return a bounded response envelope, spilling large frames to a file.

    ``spill`` is a file reserved earlier with :func:`open_chunk_spill`. Without
    one the file is created here, which requires running as the tools user.
    """
    request_id = request_data.get("id")
    response_bytes = response.encode("utf-8")
    response_limit = _response_byte_limit(max_response_bytes)
    if request_id is None or len(response_bytes) + 1 <= response_limit:
        if spill is not None:
            spill.file.close()
        return response

    if spill is None:
        spill = open_chunk_spill()
    with spill.file as chunk_file:
        try:
            chunk_file.write(response_bytes)
            chunk_file.flush()
            return _read_chunk_response(
                request_id, spill.handle, chunk_file, 0, response_limit
            )
        except Exception:
            # A sandbox user cannot unlink in the tools user's directory but can
            # empty the file it holds open; the next sweep removes the orphan.
            with suppress(OSError):
                chunk_file.truncate(0)
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

    try:
        chunk_path = _chunk_dir() / _chunk_name(handle)
        if params.get("release") is True:
            chunk_path.unlink(missing_ok=True)
            return _json_rpc_success(request_id, None)
        if "release" in params:
            return _json_rpc_error(request_id, -32602, "release must be true")

        offset = params.get("offset")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            return _json_rpc_error(request_id, -32602, "invalid chunk offset")

        with open(chunk_path, "rb") as chunk_file:
            response = _read_chunk_response(
                request_id,
                handle,
                chunk_file,
                offset,
                _response_byte_limit(max_response_bytes),
            )
            os.utime(chunk_file.fileno())  # keep a response being read alive
            return response
    except FileNotFoundError:
        return _json_rpc_error(request_id, -32000, "chunk handle not found")
    except ValueError as ex:
        return _json_rpc_error(request_id, -32602, str(ex))
    except (RuntimeError, OSError) as ex:
        return _json_rpc_error(request_id, -32000, f"unable to read chunk: {ex}")


def _read_chunk_response(
    request_id: Any,
    handle: str,
    chunk_file: BinaryIO,
    offset: int,
    max_response_bytes: int,
) -> str:
    total_size = os.fstat(chunk_file.fileno()).st_size
    if offset >= total_size:
        raise ValueError("chunk offset is beyond the response")

    chunk_file.seek(offset)
    candidate = chunk_file.read(min(_MAX_CHUNK_BYTES, total_size - offset))
    if not candidate:
        raise OSError("chunk file ended before its declared size")

    return _largest_fitting_chunk_response(
        request_id,
        handle,
        offset,
        total_size,
        candidate,
        max_response_bytes,
    )


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


def _chunk_name(handle: str) -> str:
    return f"{handle}.jsonrpc"


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


def _remove_stale_chunks(chunk_dir: Path) -> None:
    """Remove chunks past their TTL and reservations no process holds.

    A live reservation is locked by the process that made it. An unlocked empty
    file older than the grace period is a reservation that was never needed or
    whose process died; the grace period covers the instant between creating a
    reservation and locking it.
    """
    now = time.time()
    with suppress(OSError), os.scandir(chunk_dir) as entries:
        for entry in entries:
            if entry.name.endswith(".jsonrpc"):
                with suppress(OSError):
                    _remove_if_orphaned(entry.path, now)


def _remove_if_orphaned(path: str, now: float) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        info = os.fstat(fd)
        age = now - info.st_mtime
        if age > _CHUNK_TTL_SECONDS or (
            info.st_size == 0 and age > _RESERVATION_GRACE_SECONDS
        ):
            os.unlink(path)
    finally:
        os.close(fd)


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
