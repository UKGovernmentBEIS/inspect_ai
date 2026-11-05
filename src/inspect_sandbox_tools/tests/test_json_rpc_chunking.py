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
import time
from collections.abc import Callable
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
    open_chunk_spill,
)


class _ReassembledResponse(NamedTuple):
    text: str
    offsets: list[int]
    frame_sizes: list[int]
    handle: str


@pytest.fixture(autouse=True)
def isolated_chunk_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(chunking, "_CHUNK_DIR", tmp_path / "chunks")


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


def test_chunks_live_in_the_tools_users_private_directory() -> None:
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "x" * 2000})
    first_response = chunk_json_rpc_response_if_needed({"id": 1}, response, 512)
    chunk = _chunk_metadata(first_response)
    chunk_path = chunking._CHUNK_DIR / f"{chunk['handle']}.jsonrpc"

    assert stat.S_IMODE(chunking._CHUNK_DIR.lstat().st_mode) == 0o700
    assert chunk_path.is_file()
    assert stat.S_IMODE(chunk_path.lstat().st_mode) == 0o600

    continuation = handle_json_rpc_response_chunk_request(
        {
            "id": 2,
            "params": {"handle": chunk["handle"], "offset": chunk["next_offset"]},
        },
        512,
    )
    assert _chunk_metadata(continuation)["offset"] == chunk["next_offset"]
    release = handle_json_rpc_response_chunk_request(
        {"id": 3, "params": {"handle": chunk["handle"], "release": True}}, 512
    )
    assert json.loads(release) == {"jsonrpc": "2.0", "id": 3, "result": None}
    assert not chunk_path.exists()


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
    continuation: Callable[[dict[str, object]], str] | None = None,
) -> _ReassembledResponse:
    chunk = _chunk_metadata(first_response)
    handle = cast(str, chunk["handle"])
    response_bytes = bytearray()
    offsets: list[int] = []
    frame_sizes = [len(first_response.encode("utf-8")) + 1]

    def send(request: dict[str, object]) -> str:
        if continuation is not None:
            return continuation(request)
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

    Small responses never touch chunk storage and must keep working whatever
    state the tools user's own directory is in.
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


def _simulate_switch_away_from_tools_user() -> None:
    """Take away what setuid would: the right to create or unlink in the directory."""
    if os.geteuid() == 0:
        pytest.skip("root is not subject to directory modes")
    os.chmod(chunking._CHUNK_DIR, 0o500)


def _simulate_switch_back_to_tools_user() -> None:
    os.chmod(chunking._CHUNK_DIR, 0o700)


def test_reserved_spill_is_written_after_directory_access_is_lost() -> None:
    spill = open_chunk_spill()
    _simulate_switch_away_from_tools_user()
    try:
        response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "y" * 4000})
        first_response = chunk_json_rpc_response_if_needed(
            {"id": 1}, response, 512, spill=spill
        )
        assert _chunk_metadata(first_response)["handle"] == spill.handle
        assert spill.file.closed

        # A small response closes an unneeded reservation without failing.
        small = chunk_json_rpc_response_if_needed(
            {"id": 2}, '{"jsonrpc":"2.0","id":2,"result":"ok"}', 512, spill=None
        )
        assert json.loads(small)["result"] == "ok"
    finally:
        _simulate_switch_back_to_tools_user()

    reassembled = _reassemble(first_response, 512)
    assert reassembled.text == response
    assert not (chunking._CHUNK_DIR / f"{spill.handle}.jsonrpc").exists()


def test_cli_reserves_the_spill_before_switching_user(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pytest.importorskip("jsonrpcserver")
    import inspect_sandbox_tools._cli.main as main_module

    reserved_at_switch: list[int] = []

    def switch(_user: Any) -> None:
        reserved_at_switch.append(len(list(chunking._CHUNK_DIR.glob("*.jsonrpc"))))
        _simulate_switch_away_from_tools_user()

    monkeypatch.setattr(
        main_module, "switch_target", lambda user, can_switch_user: user
    )
    monkeypatch.setattr(main_module, "switch_user", switch)
    monkeypatch.setattr(main_module, "get_home_dir", lambda _user: os.environ["HOME"])
    monkeypatch.setenv(JSON_RPC_RESPONSE_MAX_BYTES_ENV, "4096")
    target = tmp_path / "large.txt"
    target.write_text("line\n" * 2000)
    request = {
        "jsonrpc": "2.0",
        "method": "text_editor",
        "id": 1,
        "params": {
            "command": "view",
            "path": str(target),
            "_run_as": {"uid": 12345, "gid": 12345, "groups": []},
        },
    }

    try:
        first_response = _exec_cli(request, capsys)
    finally:
        _simulate_switch_back_to_tools_user()
    assert reserved_at_switch == [1]

    reassembled = _reassemble(first_response, 4096, capsys=capsys)
    assert json.loads(reassembled.text)["result"].count("line") >= 2000
    assert list(chunking._CHUNK_DIR.glob("*.jsonrpc")) == []


def _open_as(uid: int, gid: int, path: Path) -> int:
    """Try to open ``path`` for reading as another uid; return the child's exit code."""
    pid = os.fork()
    if pid == 0:
        try:
            os.setgid(gid)
            os.setuid(uid)
            with open(path, "rb"):
                os._exit(0)
        except PermissionError:
            os._exit(3)
        except BaseException:
            os._exit(4)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


@pytest.mark.skipif(os.geteuid() != 0, reason="requires root to switch user")
def test_root_cli_round_trips_a_chunked_response_produced_as_another_user() -> None:
    """The real cross-uid path: the CLI switches to a sandbox user in-process.

    Root reserves the spill file, the sandbox user's response is written through
    the inherited descriptor, and root serves the continuations from its private
    directory, which the sandbox user cannot enter.
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

    def cli(request: dict[str, object]) -> str:
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
        chunk_dir = workdir / "sandbox-tools" / "chunks"
        chunk_path = chunk_dir / f"{_chunk_metadata(first_response)['handle']}.jsonrpc"
        for entry, mode in ((chunk_dir, 0o700), (chunk_path, 0o600)):
            info = entry.lstat()
            assert info.st_uid == 0 and stat.S_IMODE(info.st_mode) == mode, entry
        assert _open_as(agent.pw_uid, agent.pw_gid, chunk_path) == 3
        assert not (workdir / ".inspect-sandbox-tools-json-rpc-chunks").exists()

        reassembled = _reassemble(first_response, 4096, continuation=cli)

        assert json.loads(reassembled.text)["result"].count("line") >= 2000
        assert not chunk_path.exists()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_unusable_chunk_storage_fails_only_responses_that_need_chunking(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed reservation before the switch is raised only if chunking is needed."""
    pytest.importorskip("jsonrpcserver")
    import inspect_sandbox_tools._cli.main as main_module

    monkeypatch.setattr(
        main_module, "switch_target", lambda user, can_switch_user: user
    )
    monkeypatch.setattr(main_module, "switch_user", lambda _user: None)
    monkeypatch.setattr(main_module, "get_home_dir", lambda _user: os.environ["HOME"])
    monkeypatch.setenv(JSON_RPC_RESPONSE_MAX_BYTES_ENV, "4096")
    chunking._CHUNK_DIR.touch()
    small = tmp_path / "small.txt"
    small.write_text("small")
    large = tmp_path / "large.txt"
    large.write_text("line\n" * 2000)

    def request(path: Path) -> dict[str, object]:
        return {
            "jsonrpc": "2.0",
            "method": "text_editor",
            "id": 1,
            "params": {
                "command": "view",
                "path": str(path),
                "_run_as": {"uid": 12345, "gid": 12345, "groups": []},
            },
        }

    assert "small" in json.loads(_exec_cli(request(small), capsys))["result"]
    with pytest.raises(RuntimeError, match="cannot be trusted: it is not a directory"):
        _exec_cli(request(large), capsys)


def test_chunk_is_removed_when_no_piece_fits() -> None:
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "x" * 2000})

    with pytest.raises(ValueError, match="too small"):
        chunk_json_rpc_response_if_needed({"id": 1}, response, 64)

    assert list(chunking._CHUNK_DIR.glob("*.jsonrpc")) == []


def test_chunk_is_emptied_when_no_piece_fits_after_directory_access_is_lost() -> None:
    """After the switch the file cannot be unlinked, so it is emptied and swept later."""
    spill = open_chunk_spill()
    path = chunking._CHUNK_DIR / f"{spill.handle}.jsonrpc"
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "x" * 2000})
    _simulate_switch_away_from_tools_user()
    try:
        with pytest.raises(ValueError, match="too small"):
            chunk_json_rpc_response_if_needed({"id": 1}, response, 64, spill=spill)
        assert path.exists() and path.stat().st_size == 0
    finally:
        _simulate_switch_back_to_tools_user()

    stale = time.time() - chunking._CHUNK_TTL_SECONDS - 5
    os.utime(path, (stale, stale))
    open_chunk_spill().file.close()
    assert not path.exists()


def test_continuation_and_release_do_not_create_chunk_storage() -> None:
    handle = "0" * 32
    missing = handle_json_rpc_response_chunk_request(
        {"id": 1, "params": {"handle": handle, "offset": 0}}, 512
    )
    assert json.loads(missing)["error"]["message"] == "chunk handle not found"
    released = handle_json_rpc_response_chunk_request(
        {"id": 2, "params": {"handle": handle, "release": True}}, 512
    )
    assert json.loads(released)["result"] is None
    assert not chunking._CHUNK_DIR.exists()


def test_continuation_refuses_a_symlink_at_the_chunk_path(tmp_path: Path) -> None:
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "x" * 2000})
    chunk = _chunk_metadata(chunk_json_rpc_response_if_needed({"id": 1}, response, 512))
    chunk_path = chunking._CHUNK_DIR / f"{chunk['handle']}.jsonrpc"
    secret = tmp_path / "secret"
    secret.write_bytes(b"secret " * 100)
    chunk_path.unlink()
    chunk_path.symlink_to(secret)

    continuation = json.loads(
        handle_json_rpc_response_chunk_request(
            {"id": 2, "params": {"handle": chunk["handle"], "offset": 0}}, 512
        )
    )

    assert continuation["error"]["code"] == -32000
    assert "symbolic link" in continuation["error"]["message"]
    assert "secret" not in json.dumps(continuation)


def test_stale_reservations_and_chunks_are_swept_on_the_next_reservation() -> None:
    stale = time.time() - chunking._CHUNK_TTL_SECONDS - 5
    unneeded = open_chunk_spill()
    unneeded.file.close()
    complete = open_chunk_spill()
    complete.file.write(b"x")
    complete.file.close()
    for spill in (unneeded, complete):
        os.utime(chunking._CHUNK_DIR / f"{spill.handle}.jsonrpc", (stale, stale))
    fresh = open_chunk_spill()
    fresh.file.close()

    sweeper = open_chunk_spill()
    sweeper.file.close()

    names = {p.stem for p in chunking._CHUNK_DIR.glob("*.jsonrpc")}
    assert names == {fresh.handle, sweeper.handle}
