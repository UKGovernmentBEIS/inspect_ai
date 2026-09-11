import asyncio
import base64
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, NamedTuple, cast

import inspect_sandbox_tools._util.json_rpc_chunking as chunking
import pytest
from inspect_sandbox_tools._util.json_rpc_chunking import (
    JSON_RPC_RESPONSE_CHUNK_FIELD,
    JSON_RPC_RESPONSE_CHUNK_METHOD,
    JSON_RPC_RESPONSE_MAX_BYTES_ENV,
    chunk_json_rpc_response_if_needed,
    handle_json_rpc_response_chunk_request,
    prepare_json_rpc_response_chunk_root,
)


class _ReassembledResponse(NamedTuple):
    text: str
    offsets: list[int]
    frame_sizes: list[int]
    handle: str


@pytest.fixture(autouse=True)
def isolated_chunk_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(chunking, "_CHUNK_DIR", tmp_path / "chunks")


def _fake_stat(path: Path, *, uid: int, mode: int) -> os.stat_result:
    values = list(path.lstat())
    values[0] = stat.S_IFDIR | mode
    values[4] = uid
    return os.stat_result(values)


def _forbid_chmod(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_chmod(_fd: int, _mode: int) -> None:
        raise AssertionError("the directory must be verified, not repaired")

    monkeypatch.setattr(os, "fchmod", unexpected_chmod)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _fake_owner(monkeypatch: pytest.MonkeyPatch, path: Path, uid: int) -> None:
    """Make fstat report ``uid`` as the owner of the inode currently at ``path``."""
    target = path.lstat()
    real_fstat = os.fstat

    def fstat(fd: int) -> os.stat_result:
        info = real_fstat(fd)
        if (info.st_dev, info.st_ino) != (target.st_dev, target.st_ino):
            return info
        values = list(info)
        values[4] = uid
        return os.stat_result(values)

    monkeypatch.setattr(os, "fstat", fstat)


def _act_as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Continue as root: the chunk root this uid created appears root-owned.

    The uid directories and chunk files beneath it keep their real owner, this
    uid, which plays the sandbox user whose response root reads back.
    """
    _fake_owner(monkeypatch, chunking._CHUNK_DIR, 0)
    monkeypatch.setattr(os, "geteuid", lambda: 0)


def test_chunk_root_owned_by_root_is_used_by_a_sandbox_user_without_chmod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunking._CHUNK_DIR.mkdir(mode=0o1733)
    root_owned = _fake_stat(chunking._CHUNK_DIR, uid=0, mode=0o1733)
    monkeypatch.setattr(os, "fstat", lambda _fd: root_owned)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    _forbid_chmod(monkeypatch)

    os.close(chunking._open_chunk_root(create=True))


@pytest.mark.skipif(not hasattr(os, "O_PATH"), reason="O_PATH is Linux-only")
def test_chunk_root_usable_by_non_owner_without_read_bit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 1733 root created by root denies a sandbox user read; O_PATH still works."""
    chunking._CHUNK_DIR.mkdir(mode=0o1733)
    root_owned = _fake_stat(chunking._CHUNK_DIR, uid=0, mode=0o1733)
    real_open = os.open
    opens: list[int] = []

    def open_without_read_permission(
        path: Any, flags: int, *args: Any, **kwargs: Any
    ) -> int:
        opens.append(flags)
        if not flags & os.O_PATH:
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_without_read_permission)
    monkeypatch.setattr(os, "fstat", lambda _fd: root_owned)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    os.close(chunking._open_chunk_root(create=True))
    assert len(opens) == 2 and opens[1] & os.O_PATH


def test_chunk_root_owned_by_a_sandbox_user_is_refused_by_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Root never adopts a chunk root it did not create.

    The owner of the root could otherwise rename every uid's subtree beneath it,
    root's included. Preparing the root before switching to a sandbox user is
    what keeps a legitimate first-use race from ever producing this state.
    """
    chunking._CHUNK_DIR.mkdir(mode=0o1733)
    agent_owned = _fake_stat(chunking._CHUNK_DIR, uid=1000, mode=0o1733)
    monkeypatch.setattr(os, "fstat", lambda _fd: agent_owned)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    _forbid_chmod(monkeypatch)

    with pytest.raises(RuntimeError, match="owned by uid 1000, not uid 0"):
        chunking._open_chunk_root(create=True)
    prepare_json_rpc_response_chunk_root()

    continuation = handle_json_rpc_response_chunk_request(
        {"id": 1, "params": {"handle": "0" * 32, "offset": 0}}, 512
    )
    error = json.loads(continuation)["error"]
    assert error["code"] == -32000 and "owned by uid 1000" in error["message"]
    release = handle_json_rpc_response_chunk_request(
        {"id": 2, "params": {"handle": "0" * 32, "release": True}}, 512
    )
    assert json.loads(release)["error"]["code"] == -32000


def test_symlink_planted_at_chunk_root_is_refused_without_following_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    victim = tmp_path / "victim"
    victim.mkdir(mode=0o700)
    chunking._CHUNK_DIR.symlink_to(victim, target_is_directory=True)
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    with pytest.raises(RuntimeError, match="it is a symbolic link"):
        chunking._open_chunk_root(create=True)
    prepare_json_rpc_response_chunk_root()

    assert _mode(victim) == 0o700


def test_cli_prepares_chunk_root_before_switching_user(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pytest.importorskip("jsonrpcserver")
    import inspect_sandbox_tools._cli.main as main_module

    root_at_switch: list[tuple[bool, int, int]] = []

    def record_switch(_user: Any) -> None:
        root = chunking._CHUNK_DIR
        own_dir = root / str(os.geteuid())
        root_at_switch.append(
            (root.is_dir() and not root.is_symlink(), _mode(root), _mode(own_dir))
        )

    monkeypatch.setattr(
        main_module, "switch_target", lambda user, can_switch_user: user
    )
    monkeypatch.setattr(main_module, "switch_user", record_switch)
    monkeypatch.setattr(main_module, "get_home_dir", lambda _user: os.environ["HOME"])
    target = tmp_path / "small.txt"
    target.write_text("small")

    response = _exec_cli(
        {
            "jsonrpc": "2.0",
            "method": "text_editor",
            "id": 1,
            "params": {
                "command": "view",
                "path": str(target),
                "_run_as": {"uid": 12345, "gid": 12345, "groups": []},
            },
        },
        capsys,
    )

    assert "small" in json.loads(response)["result"]
    assert root_at_switch == [(True, 0o1733, 0o700)]
    assert chunking._CHUNK_DIR.lstat().st_uid == os.geteuid()


def test_start_server_prepares_chunk_directories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("jsonrpcserver")
    import inspect_sandbox_tools._cli.main as main_module

    monkeypatch.setattr(main_module, "_ensure_server_is_running", lambda: None)
    monkeypatch.setattr(main_module, "healthcheck", lambda: None)

    main_module.start_server()

    assert _mode(chunking._CHUNK_DIR) == 0o1733
    assert _mode(chunking._CHUNK_DIR / str(os.geteuid())) == 0o700

    # An unusable chunk root must not stop the server from starting.
    shutil.rmtree(chunking._CHUNK_DIR)
    chunking._CHUNK_DIR.touch()
    main_module.start_server()


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


def test_json_rpc_response_chunks_use_private_uid_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "x" * 2000})
    first_response = chunk_json_rpc_response_if_needed({"id": 1}, response, 512)
    chunk = _chunk_metadata(first_response)
    user_dir = chunking._CHUNK_DIR / str(os.geteuid())
    chunk_path = user_dir / f"{chunk['handle']}.jsonrpc"

    assert _mode(chunking._CHUNK_DIR) == 0o1733
    assert _mode(user_dir) == 0o700
    assert chunk_path.is_file() and _mode(chunk_path) == 0o600

    _act_as_root(monkeypatch)
    root_continuation = handle_json_rpc_response_chunk_request(
        {
            "id": 2,
            "params": {"handle": chunk["handle"], "offset": chunk["next_offset"]},
        },
        512,
    )

    assert _chunk_metadata(root_continuation)["offset"] == chunk["next_offset"]
    release = handle_json_rpc_response_chunk_request(
        {"id": 3, "params": {"handle": chunk["handle"], "release": True}},
        512,
    )
    assert json.loads(release) == {"jsonrpc": "2.0", "id": 3, "result": None}
    assert not chunk_path.exists()


def test_frozen_chunk_dir_uses_hidden_sibling_of_tools_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        sys,
        "executable",
        "/var/tmp/.da7be258e003d428/inspect-sandbox-tools",
    )

    assert (
        chunking._default_chunk_dir()
        == Path("/var/tmp/.da7be258e003d428-json-rpc-chunks").resolve()
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


class _PlantedChunk(NamedTuple):
    handle: str
    path: Path
    original: bytes
    secret: Path


def _write_chunk(tmp_path: Path) -> _PlantedChunk:
    """Spill a response as the current uid and prepare a secret to point it at."""
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "x" * 2000})
    handle = cast(
        str,
        _chunk_metadata(chunk_json_rpc_response_if_needed({"id": 1}, response, 512))[
            "handle"
        ],
    )
    path = chunking._CHUNK_DIR / str(os.geteuid()) / f"{handle}.jsonrpc"
    secret = tmp_path / "secret"
    secret.write_bytes(b"root-only secret " * 40)
    return _PlantedChunk(handle, path, path.read_bytes(), secret)


def _continue(handle: str, offset: int = 0) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            handle_json_rpc_response_chunk_request(
                {"id": 2, "params": {"handle": handle, "offset": offset}}, 512
            )
        ),
    )


@pytest.mark.parametrize("as_root", [False, True], ids=["owner", "root"])
def test_chunk_replaced_by_symlink_before_open_is_not_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, as_root: bool
) -> None:
    """The uid that owns a chunk directory can swap a chunk for a symlink."""
    planted = _write_chunk(tmp_path)
    planted.path.unlink()
    planted.path.symlink_to(planted.secret)
    secret_mtime = planted.secret.stat().st_mtime_ns
    if as_root:
        _act_as_root(monkeypatch)

    payload = _continue(planted.handle)

    assert payload["error"]["message"] == "chunk handle not found"
    assert planted.secret.stat().st_mtime_ns == secret_mtime


@pytest.mark.parametrize("as_root", [False, True], ids=["owner", "root"])
def test_chunk_replaced_by_symlink_after_open_is_read_from_the_opened_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, as_root: bool
) -> None:
    planted = _write_chunk(tmp_path)
    secret_mtime = planted.secret.stat().st_mtime_ns
    real_open = os.open

    def open_then_swap(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        fd = real_open(path, flags, *args, **kwargs)
        if str(path) == planted.path.name and not flags & os.O_CREAT:
            planted.path.unlink()
            planted.path.symlink_to(planted.secret)
        return fd

    monkeypatch.setattr(os, "open", open_then_swap)
    if as_root:
        _act_as_root(monkeypatch)

    payload = _continue(planted.handle)

    chunk = payload[JSON_RPC_RESPONSE_CHUNK_FIELD]
    assert planted.original.startswith(base64.b64decode(chunk["chunk"]))
    assert chunk["total_size"] == len(planted.original)
    assert planted.path.is_symlink()
    assert planted.secret.stat().st_mtime_ns == secret_mtime


@pytest.mark.parametrize("as_root", [False, True], ids=["owner", "root"])
def test_chunk_owned_by_another_uid_is_not_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, as_root: bool
) -> None:
    """A hardlink to another user's file in the chunk directory is refused."""
    planted = _write_chunk(tmp_path)
    if as_root:
        _act_as_root(monkeypatch)
    _fake_owner(monkeypatch, planted.path, 12345)

    assert _continue(planted.handle)["error"]["message"] == "chunk handle not found"


def test_missing_chunk_is_not_found(tmp_path: Path) -> None:
    handle = "0" * 32
    release = {"id": 3, "params": {"handle": handle, "release": True}}

    # Before anything was spilled there is no chunk root at all.
    assert _continue(handle)["error"]["message"] == "chunk handle not found"
    released = json.loads(handle_json_rpc_response_chunk_request(release, 512))
    assert released["result"] is None

    _write_chunk(tmp_path)
    assert _continue(handle)["error"]["message"] == "chunk handle not found"


@pytest.mark.parametrize("kind", ["fifo", "directory"])
def test_non_regular_file_at_chunk_name_is_rejected_without_blocking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    planted = _write_chunk(tmp_path)
    planted.path.unlink()
    if kind == "fifo":
        os.mkfifo(planted.path)
    else:
        planted.path.mkdir()
    _act_as_root(monkeypatch)
    results: list[dict[str, Any]] = []

    worker = threading.Thread(
        target=lambda: results.append(_continue(planted.handle)), daemon=True
    )
    worker.start()
    worker.join(timeout=10)

    assert not worker.is_alive(), "opening the planted FIFO blocked"
    assert results[0]["error"]["message"] == "chunk handle not found"


@pytest.mark.parametrize("as_root", [False, True], ids=["owner", "root"])
def test_release_and_lookup_do_not_follow_a_replaced_uid_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, as_root: bool
) -> None:
    planted = _write_chunk(tmp_path)
    user_dir = planted.path.parent
    decoy_dir = tmp_path / "decoy"
    decoy_dir.mkdir(mode=0o700)
    decoy = decoy_dir / planted.path.name
    decoy.write_bytes(planted.original)
    user_dir.rename(tmp_path / "moved-aside")
    user_dir.symlink_to(decoy_dir, target_is_directory=True)
    if as_root:
        _act_as_root(monkeypatch)

    assert _continue(planted.handle)["error"]["message"] == "chunk handle not found"
    release = handle_json_rpc_response_chunk_request(
        {"id": 3, "params": {"handle": planted.handle, "release": True}}, 512
    )

    assert json.loads(release)["result"] is None
    assert decoy.read_bytes() == planted.original


@pytest.mark.skipif(os.geteuid() == 0, reason="root would own the directory itself")
def test_root_verifies_but_never_repairs_another_uid_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    planted = _write_chunk(tmp_path)
    user_dir = planted.path.parent
    os.chmod(user_dir, 0o755)
    misnamed = chunking._CHUNK_DIR / str(os.geteuid() + 1)
    misnamed.mkdir(mode=0o700)
    (misnamed / planted.path.name).write_bytes(planted.original)
    real_geteuid, real_fstat = os.geteuid, os.fstat
    _act_as_root(monkeypatch)

    assert _continue(planted.handle)["error"]["message"] == "chunk handle not found"
    assert _mode(user_dir) == 0o755

    # The owner repairs its own directory and finds the chunk again.
    monkeypatch.setattr(os, "geteuid", real_geteuid)
    monkeypatch.setattr(os, "fstat", real_fstat)
    assert JSON_RPC_RESPONSE_CHUNK_FIELD in _continue(planted.handle)
    assert _mode(user_dir) == 0o700


def test_stale_chunks_are_swept_on_the_next_write(tmp_path: Path) -> None:
    stale = _write_chunk(tmp_path)
    user_dir = stale.path.parent
    old = (time.time() - chunking._CHUNK_TTL_SECONDS - 60,) * 2
    os.utime(stale.path, old)
    other = user_dir / "notes.txt"
    other.write_text("keep")
    os.utime(other, old)
    link = user_dir / f"{'f' * 32}.jsonrpc"
    link.symlink_to(other)
    os.utime(link, old, follow_symlinks=False)

    fresh = _write_chunk(tmp_path)

    assert not stale.path.exists() and fresh.path.exists()
    assert other.read_text() == "keep" and link.is_symlink()


def test_chunk_is_removed_when_no_piece_fits() -> None:
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "x" * 2000})

    with pytest.raises(ValueError, match="too small"):
        chunk_json_rpc_response_if_needed({"id": 1}, response, 64)

    user_dir = chunking._CHUNK_DIR / str(os.geteuid())
    assert list(user_dir.glob("*.jsonrpc")) == []


def test_existing_chunk_directories_are_reused() -> None:
    root_fd = chunking._open_chunk_root(create=True)
    os.close(chunking._open_chunk_root(create=True))
    user_dir_fd = chunking._open_user_dir(root_fd, os.geteuid(), create=True)
    os.close(chunking._open_user_dir(root_fd, os.geteuid(), create=True))
    os.close(user_dir_fd)
    os.close(root_fd)

    assert _mode(chunking._CHUNK_DIR) == 0o1733
    assert _mode(chunking._CHUNK_DIR / str(os.geteuid())) == 0o700


@pytest.mark.skipif(os.geteuid() != 0, reason="requires root to switch user")
def test_root_cli_round_trips_a_chunked_response_produced_as_another_user() -> None:
    """The real cross-uid path: the CLI switches to a sandbox user in-process.

    Root prepares the shared root, the sandbox user spills the response into its
    own directory, and root reads it back for the host's continuation requests.
    """
    pytest.importorskip("jsonrpcserver")
    try:
        agent = pwd.getpwnam("nobody")
    except KeyError:
        pytest.skip("no 'nobody' user")
    workdir = Path(tempfile.mkdtemp())
    workdir.chmod(0o1777)
    target = workdir / "large.txt"
    target.write_text("line\n" * 2000)
    target.chmod(0o644)
    env = {
        **os.environ,
        "TMPDIR": str(workdir),
        JSON_RPC_RESPONSE_MAX_BYTES_ENV: "4096",
    }

    def cli(request: dict[str, Any]) -> str:
        result = subprocess.run(
            [sys.executable, "-m", "inspect_sandbox_tools._cli.main", "exec"],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            env=env,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    try:
        first_response = cli(
            {
                "jsonrpc": "2.0",
                "method": "text_editor",
                "id": 1,
                "params": {
                    "command": "view",
                    "path": str(target),
                    "_run_as": {
                        "uid": agent.pw_uid,
                        "gid": agent.pw_gid,
                        "groups": [],
                    },
                },
            }
        )
        chunk_root = workdir / ".inspect-sandbox-tools-json-rpc-chunks"
        assert chunk_root.lstat().st_uid == 0 and _mode(chunk_root) == 0o1733
        assert _mode(chunk_root / "0") == 0o700
        user_dir = chunk_root / str(agent.pw_uid)
        assert user_dir.lstat().st_uid == agent.pw_uid and _mode(user_dir) == 0o700

        reassembled = _reassemble(first_response, 4096, continuation=cli)

        assert json.loads(reassembled.text)["result"].count("line") >= 2000
        assert not (user_dir / f"{reassembled.handle}.jsonrpc").exists()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


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
    continuation: Any = None,
) -> _ReassembledResponse:
    chunk = _chunk_metadata(first_response)
    handle = cast(str, chunk["handle"])
    response_bytes = bytearray()
    offsets: list[int] = []
    frame_sizes = [len(first_response.encode("utf-8")) + 1]

    def send(request: dict[str, object]) -> str:
        if continuation is not None:
            return cast(str, continuation(request))
        if capsys is not None:
            return _exec_cli(request, capsys)
        return handle_json_rpc_response_chunk_request(request, max_response_bytes)

    while True:
        offsets.append(cast(int, chunk["offset"]))
        response_bytes.extend(base64.b64decode(chunk["chunk"], validate=True))
        if chunk["done"]:
            break
        next_response = send(
            {
                "jsonrpc": "2.0",
                "method": JSON_RPC_RESPONSE_CHUNK_METHOD,
                "params": {"handle": handle, "offset": chunk["next_offset"]},
                "id": 2,
            }
        )
        frame_sizes.append(len(next_response.encode("utf-8")) + 1)
        chunk = _chunk_metadata(next_response)

    send(
        {
            "jsonrpc": "2.0",
            "method": JSON_RPC_RESPONSE_CHUNK_METHOD,
            "params": {"handle": handle, "release": True},
            "id": 3,
        }
    )
    return _ReassembledResponse(
        response_bytes.decode("utf-8"), offsets, frame_sizes, handle
    )


def _chunk_metadata(response: str) -> dict[str, Any]:
    payload = cast(dict[str, Any], json.loads(response))
    return cast(dict[str, Any], payload[JSON_RPC_RESPONSE_CHUNK_FIELD])


def test_small_response_unaffected_by_unusable_chunk_dir(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unusable chunk path must not break non-chunked requests.

    The chunk dir lives at a well-known path in a world-writable location, so
    sandbox code can pre-create it (e.g. as a plain file). Small responses
    never touch the chunk dir and must keep working regardless of its state.
    """
    pytest.importorskip("jsonrpcserver")
    chunking._CHUNK_DIR.touch()

    response = _exec_cli(
        {"jsonrpc": "2.0", "method": "version", "id": 1},
        capsys,
    )

    payload = json.loads(response)
    assert payload["id"] == 1
    assert "result" in payload
