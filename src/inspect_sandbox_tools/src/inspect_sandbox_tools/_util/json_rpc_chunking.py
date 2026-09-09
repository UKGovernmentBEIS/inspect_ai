import base64
import errno
import json
import os
import re
import stat
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from typing import Any, BinaryIO, NamedTuple

from inspect_sandbox_tools._util.framework_directory import open_framework_directory

JSON_RPC_RESPONSE_CHUNK_METHOD = "__inspect_json_rpc_response_chunk__"
JSON_RPC_RESPONSE_CHUNK_FIELD = "__inspect_json_rpc_response_chunk__"
JSON_RPC_RESPONSE_CHUNK_VERSION = 1
JSON_RPC_RESPONSE_MAX_BYTES_ENV = "INSPECT_SANDBOX_JSON_RPC_RESPONSE_MAX_BYTES"

_DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_CHUNK_BYTES = 512 * 1024
_CHUNK_TTL_SECONDS = 60 * 60
_VALID_HANDLE = re.compile(r"^[0-9a-f]{32}$")
_CHUNK_DIR_KIND = "JSON-RPC response chunk directory"


def _default_chunk_dir() -> Path:
    """Return the chunk-storage root, a hidden sibling of the tools directory.

    It cannot live inside the tools tree, which is private to the tools user,
    because sandbox users write their own chunks. Ownership checks, not the
    location, keep it trustworthy.
    """
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return executable.parent.parent / f"{executable.parent.name}-json-rpc-chunks"
    return Path(tempfile.gettempdir()) / ".inspect-sandbox-tools-json-rpc-chunks"


_CHUNK_DIR = _default_chunk_dir()


def prepare_json_rpc_response_chunk_root() -> None:
    """Create the shared chunk root and this user's directory in it.

    Runs as the tools user when the server starts and again before the CLI
    switches to a sandbox user, so a sandbox user later finds a root and a
    tools-user directory it neither owns nor can replace. Failure is not
    reported here: small responses never need the root, and chunking raises the
    error if a large response does.
    """
    with suppress(RuntimeError, OSError):
        with _closing(_open_chunk_root(create=True)) as root_fd:
            os.close(_open_user_dir(root_fd, os.geteuid(), create=True))


def _open_chunk_root(*, create: bool) -> int:
    """Open the shared root, owned by root or (for a rootless tools user) by us.

    Its sticky 1733 mode lets every uid create a private subdirectory while
    denying enumeration and deletion of another uid's entries.
    """
    return open_framework_directory(
        _CHUNK_DIR,
        kind=_CHUNK_DIR_KIND,
        owners=(0, os.geteuid()),
        mode=0o1733,
        create=create,
        shared=True,
    )


def _open_user_dir(root_fd: int, uid: int, *, create: bool) -> int:
    return open_framework_directory(
        _CHUNK_DIR / str(uid),
        kind=_CHUNK_DIR_KIND,
        owners=(uid,),
        mode=0o700,
        create=create,
        dir_fd=root_fd,
    )


@contextmanager
def _closing(fd: int) -> Iterator[int]:
    try:
        yield fd
    finally:
        os.close(fd)


def chunk_json_rpc_response_if_needed(
    request_data: dict[str, Any],
    response: str,
    max_response_bytes: int | None = None,
) -> str:
    """Return a bounded response envelope, spilling large frames to a file."""
    request_id = request_data.get("id")
    if request_id is None:
        return response

    response_bytes = response.encode("utf-8")
    response_limit = _response_byte_limit(max_response_bytes)
    if len(response_bytes) + 1 <= response_limit:
        return response

    with ExitStack() as stack:
        root_fd = stack.enter_context(_closing(_open_chunk_root(create=True)))
        user_dir_fd = stack.enter_context(
            _closing(_open_user_dir(root_fd, os.geteuid(), create=True))
        )
        _remove_stale_chunks(user_dir_fd)
        written = _write_response(user_dir_fd, response_bytes)
        stack.enter_context(written.file)
        try:
            return _read_chunk_response(
                request_id, written.handle, written.file, 0, response_limit
            )
        except Exception:
            with suppress(OSError):
                os.unlink(_chunk_name(written.handle), dir_fd=user_dir_fd)
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

    if params.get("release") is True:
        try:
            with _locate_chunk(handle) as located:
                if located is not None:
                    os.unlink(located.name, dir_fd=located.dir_fd)
        except (RuntimeError, OSError) as ex:
            return _json_rpc_error(request_id, -32000, f"unable to release chunk: {ex}")
        return _json_rpc_success(request_id, None)
    if "release" in params:
        return _json_rpc_error(request_id, -32602, "release must be true")

    offset = params.get("offset")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return _json_rpc_error(request_id, -32602, "invalid chunk offset")

    try:
        with _locate_chunk(handle) as located:
            if located is None:
                return _json_rpc_error(request_id, -32000, "chunk handle not found")
            return _read_chunk_response(
                request_id,
                handle,
                located.file,
                offset,
                _response_byte_limit(max_response_bytes),
            )
    except ValueError as ex:
        return _json_rpc_error(request_id, -32602, str(ex))
    except (RuntimeError, OSError) as ex:
        return _json_rpc_error(request_id, -32000, f"unable to read chunk: {ex}")


class _WrittenChunk(NamedTuple):
    handle: str
    file: BinaryIO


def _write_response(user_dir_fd: int, response_bytes: bytes) -> _WrittenChunk:
    while True:
        handle = uuid.uuid4().hex
        name = _chunk_name(handle)
        try:
            descriptor = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                0o600,
                dir_fd=user_dir_fd,
            )
        except FileExistsError:
            continue

        chunk_file = os.fdopen(descriptor, "rb+")
        try:
            # The umask may have masked owner bits; the owner reopens it later.
            os.fchmod(descriptor, 0o600)
            chunk_file.write(response_bytes)
            chunk_file.flush()
        except BaseException:
            chunk_file.close()
            with suppress(OSError):
                os.unlink(name, dir_fd=user_dir_fd)
            raise
        return _WrittenChunk(handle, chunk_file)


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

    response = _largest_fitting_chunk_response(
        request_id,
        handle,
        offset,
        total_size,
        candidate,
        max_response_bytes,
    )
    os.utime(chunk_file.fileno())
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


def _chunk_name(handle: str) -> str:
    return f"{handle}.jsonrpc"


class _LocatedChunk(NamedTuple):
    dir_fd: int
    """The verified directory of the uid that wrote the chunk."""
    name: str
    file: BinaryIO
    """The chunk, verified as a regular file owned by that uid."""


@contextmanager
def _locate_chunk(handle: str) -> Iterator[_LocatedChunk | None]:
    """Find the chunk for ``handle``, holding its directory and file open.

    Every directory and the file itself are verified as they are opened, and the
    descriptors returned are the objects that were verified: the uid that owns a
    chunk directory can rename or replace its entries at any time.
    """
    name = _chunk_name(handle)
    try:
        root_fd = _open_chunk_root(create=False)
    except FileNotFoundError:
        yield None
        return
    with _closing(root_fd):
        for uid in _chunk_owner_candidates(root_fd):
            try:
                user_dir_fd = _open_user_dir(root_fd, uid, create=False)
            except (FileNotFoundError, RuntimeError):
                continue
            with _closing(user_dir_fd):
                chunk_file = _open_chunk_file(user_dir_fd, name, uid)
                if chunk_file is None:
                    continue
                with chunk_file:
                    yield _LocatedChunk(user_dir_fd, name, chunk_file)
                    return
        yield None


def _chunk_owner_candidates(root_fd: int) -> list[int]:
    current_uid = os.geteuid()
    if current_uid != 0:
        return [current_uid]
    # The host sends continuations as the tools user (normally root) even when
    # the in-process request that produced the response had switched to a
    # sandbox user, so root also searches the other uids' directories.
    others = {
        int(entry)
        for entry in os.listdir(root_fd)
        if entry.isdecimal() and str(int(entry)) == entry
    }
    return [current_uid, *sorted(others - {current_uid})]


def _open_chunk_file(user_dir_fd: int, name: str, owner: int) -> BinaryIO | None:
    """Open a chunk that must be a regular file owned by ``owner``, else None.

    O_NOFOLLOW rejects a symlink planted at the name; O_NONBLOCK keeps a planted
    FIFO from blocking the open, so the fstat that follows can reject it.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        fd = os.open(name, flags, dir_fd=user_dir_fd)
    except FileNotFoundError:
        return None
    except OSError as ex:
        if ex.errno in (errno.ELOOP, errno.ENXIO):
            return None
        raise
    try:
        info = os.fstat(fd)
    except BaseException:
        os.close(fd)
        raise
    if not stat.S_ISREG(info.st_mode) or info.st_uid != owner:
        os.close(fd)
        return None
    return os.fdopen(fd, "rb")


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


def _remove_stale_chunks(user_dir_fd: int) -> None:
    stale_before = time.time() - _CHUNK_TTL_SECONDS
    with suppress(OSError), os.scandir(user_dir_fd) as entries:
        for entry in entries:
            if not entry.name.endswith(".jsonrpc"):
                continue
            with suppress(OSError):
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) and info.st_mtime < stale_before:
                    os.unlink(entry.name, dir_fd=user_dir_fd)


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
