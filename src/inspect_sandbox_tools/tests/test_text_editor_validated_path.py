"""Tests for text-editor path validation, directory views, and RPC errors."""

import asyncio
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import inspect_sandbox_tools._in_process_tools._text_editor._run as run_module
import inspect_sandbox_tools._in_process_tools._text_editor.text_editor as text_editor_module
import pytest
from inspect_sandbox_tools._in_process_tools._text_editor.text_editor import (
    _validated_path,
)
from inspect_sandbox_tools._util.common_types import ToolException


@pytest.mark.parametrize("symlink", [False, True])
@pytest.mark.parametrize(
    "name",
    [
        "directory with spaces",
        "single'quote",
        'double"quote',
        "x$(touch sentinel)",
        "x`touch sentinel`",
        "x;touch sentinel;#",
        "x&touch sentinel;#",
        "x\ntouch sentinel\n#",
        "x$HOME",
        "x*",
    ],
)
async def test_view_directory_treats_path_as_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, symlink: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "x").mkdir()
    target = tmp_path / name
    target.mkdir()
    (target / "child.txt").write_text("hello")
    requested_path = target
    if symlink:
        requested_path = tmp_path / "link"
        requested_path.symlink_to(target, target_is_directory=True)

    try:
        result = await text_editor_module.view(str(requested_path))
    finally:
        assert not (tmp_path / "sentinel").exists(), (
            "Directory name executed as shell code"
        )

    resolved = target.resolve()
    assert result == (
        f"Here are the files and directories up to 2 levels deep in {resolved}, excluding hidden items:\n"
        f"{resolved}\n{resolved}/child.txt\n"
    )


@pytest.mark.parametrize("hidden_root", [False, True])
async def test_view_directory_preserves_find_output(
    tmp_path: Path, hidden_root: bool
) -> None:
    # With a hidden root every path matches `*/\.*`, so find prints nothing and
    # the view is a lone "." (normpath of the empty line). Pre-existing; that case
    # pins equivalence with the old shell command, not that the output is desirable.
    target = tmp_path / (".hidden" if hidden_root else "visible")
    target.mkdir()
    (target / "file.txt").touch()
    (target / ".hidden.txt").touch()
    (target / "subdir").mkdir()
    (target / "subdir" / "child.txt").touch()
    (target / "subdir" / "deeper").mkdir()
    (target / "subdir" / "deeper" / "excluded.txt").touch()
    (target / "link").symlink_to(target / "subdir", target_is_directory=True)
    path = target.resolve()
    legacy = subprocess.run(
        [
            "sh",
            "-c",
            rf"find {shlex.quote(str(path) + '/')} -maxdepth 2 -not -path '*/\.*'",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    expected = "\n".join(
        os.path.normpath(line) for line in legacy.stdout.strip().split("\n")
    )

    result = await text_editor_module.view(str(target))

    assert result == (
        f"Here are the files and directories up to 2 levels deep in {path}, excluding hidden items:\n{expected}\n"
    )
    assert "excluded.txt" not in result
    assert ".hidden.txt" not in result


async def test_view_directory_rejects_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        text_editor_module,
        "run",
        AsyncMock(return_value=(0, "partial listing", "permission denied")),
    )
    with pytest.raises(ToolException, match="permission denied"):
        await text_editor_module.view(str(tmp_path))


async def test_view_directory_ignores_find_on_inherited_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = tmp_path / "sentinel"
    forged_dir = tmp_path / "bin"
    forged_dir.mkdir()
    forged = forged_dir / "find"
    forged.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(sentinel))}\n")
    forged.chmod(0o755)
    monkeypatch.setenv("PATH", f"{forged_dir}{os.pathsep}{os.environ['PATH']}")
    assert shutil.which("find") == str(forged), "forgery not first on PATH"
    target = tmp_path / "target"
    target.mkdir()
    (target / "child.txt").touch()

    result = await text_editor_module.view(str(target))

    assert f"{target.resolve()}/child.txt" in result
    assert not sentinel.exists(), "find resolved from the inherited PATH"


@pytest.mark.parametrize("missing", [False, True])
def test_view_directory_launch_failure_is_tool_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing: bool,
) -> None:
    from inspect_sandbox_tools._cli.main import _exec

    monkeypatch.setattr(run_module, "SYSTEM_PATH", str(tmp_path))
    if not missing:
        (tmp_path / "find").write_text("not executable")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "text_editor",
        "params": {"command": "view", "path": str(tmp_path)},
    }

    asyncio.run(_exec(json.dumps(request)))
    response = json.loads(capsys.readouterr().out)

    assert response["error"]["code"] == -32099
    assert "find" in response["error"]["message"]
    assert str(tmp_path.resolve()) in response["error"]["message"]
    assert f"PATH={tmp_path}" in response["error"]["message"]


def test_view_directory_timeout_preserves_rpc_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from inspect_sandbox_tools._cli.main import _exec

    monkeypatch.setattr(
        text_editor_module,
        "run",
        AsyncMock(side_effect=TimeoutError("find timed out after 120 seconds")),
    )
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "text_editor",
        "params": {"command": "view", "path": str(tmp_path)},
    }

    asyncio.run(_exec(json.dumps(request)))
    response = json.loads(capsys.readouterr().out)

    assert response["error"]["code"] == -32098
    assert response["error"]["message"] == repr(
        TimeoutError("find timed out after 120 seconds")
    )


def _set_history_path(monkeypatch: pytest.MonkeyPatch, history_path: Path) -> None:
    monkeypatch.setattr(text_editor_module, "_history_path", lambda: history_path)


def test_validated_path_rejects_too_long_filename() -> None:
    """Pathological long path from the model must raise ToolException, not OSError.

    Regression: UKGovernmentBEIS/inspect_ai#3689 — a 5000-char path component
    caused `path.exists()` to raise `OSError(ENAMETOOLONG)`, which propagated as
    JSON-RPC `-32098` and crashed the eval instead of being fed back to the model.
    """
    with pytest.raises(ToolException):
        _validated_path("a" * 5000, "view")


def test_validated_path_rejects_embedded_null_byte() -> None:
    """Null-byte paths must raise ToolException, not crash the JSON-RPC server."""
    with pytest.raises(ToolException, match="Invalid path"):
        _validated_path("/repo/foo\x00bar", "view")


async def test_str_replace_recovers_from_truncated_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    history_path = tmp_path / "history.json"
    history_path.write_bytes(b'{"truncated":')
    history_path.chmod(0o600)
    _set_history_path(monkeypatch, history_path)

    target = tmp_path / "target.txt"
    target.write_text("before\n")

    result = await text_editor_module.str_replace(str(target), "before", "after")

    assert target.read_text() == "after\n"
    assert f"The file {target}" in result
    assert text_editor_module._load_history()[target.resolve()] == ["before\n"]


async def test_str_replace_continues_when_history_save_fails(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    history_path = tmp_path / "history.json"
    _set_history_path(monkeypatch, history_path)

    def fail_dump(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(json, "dump", fail_dump)
    caplog.set_level("WARNING", logger=text_editor_module.__name__)

    target = tmp_path / "target.txt"
    target.write_text("before\n")

    result = await text_editor_module.str_replace(str(target), "before", "after")

    assert target.read_text() == "after\n"
    assert f"The file {target}" in result
    assert "Discarding text_editor history" in caplog.text


def test_history_retains_last_ten_entries_per_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    history_path = tmp_path / "history.json"
    _set_history_path(monkeypatch, history_path)

    target = (tmp_path / "target.txt").resolve()
    other_target = (tmp_path / "other.txt").resolve()
    for i in range(12):
        text_editor_module._add_history_entry(
            target, f"old {i}", text_editor_module._load_history()
        )
    text_editor_module._add_history_entry(
        other_target, "other old", text_editor_module._load_history()
    )

    history = text_editor_module._load_history()

    assert history[target] == [f"old {i}" for i in range(2, 12)]
    assert history[other_target] == ["other old"]


async def test_undo_edit_reports_retained_history_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    history_path = tmp_path / "history.json"
    _set_history_path(monkeypatch, history_path)

    target = tmp_path / "target.txt"
    target.write_text("current")

    with pytest.raises(ToolException, match="only retains the last 10 edits per file"):
        await text_editor_module.undo_edit(str(target))


@pytest.fixture
def private_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(text_editor_module, "_HISTORY_PARENT", tmp_path)
    return text_editor_module._history_path()


async def test_history_round_trip(private_history: Path, tmp_path: Path) -> None:
    target = tmp_path / "unicode-λ.txt"
    original = "hello λ\nsecond line\n"
    await text_editor_module.create(str(target), original)
    await text_editor_module.str_replace(str(target), "hello", "goodbye")
    replaced = target.read_text()
    await text_editor_module.insert(str(target), 1, "inserted")
    assert target.read_text() == "goodbye λ\ninserted\nsecond line\n"
    assert json.loads(private_history.read_text()) == {
        str(target.resolve()): [-1, original, replaced]
    }
    assert private_history.stat().st_mode & 0o777 == 0o600
    assert private_history.parent.stat().st_mode & 0o777 == 0o700
    await text_editor_module.undo_edit(str(target))
    assert target.read_text() == replaced
    await text_editor_module.undo_edit(str(target))
    assert target.read_text() == original
    await text_editor_module.undo_edit(str(target))
    assert not target.exists()
    assert text_editor_module._load_history() == {}


@pytest.mark.parametrize(
    "contents",
    [
        b"{",
        b"\xff",
        b"[]",
        b"null",
        b'{"/x": "text"}',
        b'{"/x": [true]}',
        b'{"/x": [-1.0]}',
        b'{"/x": [0]}',
        b'{"/x": [{}]}',
        b'{"/x": [null]}',
    ],
)
def test_malformed_history_is_discarded(
    private_history: Path, contents: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    private_history.write_bytes(contents)
    private_history.chmod(0o600)
    assert text_editor_module._load_history() == {}
    assert not private_history.exists()
    assert "Discarding text_editor history" in caplog.text


def test_pickle_history_never_executes(private_history: Path, tmp_path: Path) -> None:
    # Protocol 0 GLOBAL/REDUCE would execute this command when unpickled.
    marker = tmp_path / "executed"
    payload = f"cos\nsystem\n(S'touch {marker}'\ntR.".encode()
    legacy = tmp_path / "inspect_editor_history.pkl"
    legacy.write_bytes(payload)
    assert text_editor_module._load_history() == {}
    assert legacy.read_bytes() == payload
    private_history.write_bytes(payload)
    private_history.chmod(0o600)
    assert text_editor_module._load_history() == {}
    assert not marker.exists()


@pytest.mark.parametrize("kind", ["symlink", "file", "exposed"])
def test_unsafe_history_directory_is_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    monkeypatch.setattr(text_editor_module, "_HISTORY_PARENT", tmp_path)
    directory = tmp_path / f"inspect-editor-{os.geteuid()}"
    if kind == "symlink":
        directory.symlink_to(tmp_path)
    elif kind == "file":
        directory.touch()
    else:
        directory.mkdir(mode=0o777)
        directory.chmod(0o777)
    before = directory.lstat()
    with pytest.raises(ToolException, match="Cannot access text_editor history"):
        text_editor_module._load_history()
    assert directory.lstat() == before


def test_unsafe_history_parent_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(text_editor_module, "_HISTORY_PARENT", tmp_path)
    tmp_path.chmod(0o777)
    try:
        with pytest.raises(ToolException, match="History parent.*cannot be trusted"):
            text_editor_module._load_history()
        assert list(tmp_path.iterdir()) == []
    finally:
        tmp_path.chmod(0o700)


def test_history_rejects_parent_symlink_swapped_after_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intermediate = tmp_path / "intermediate"
    parent = intermediate / "temp"
    parent.mkdir(parents=True)
    replacement = tmp_path / "replacement"
    (replacement / "temp").mkdir(parents=True)
    original_resolve = Path.resolve

    def resolve_then_swap(path: Path, strict: bool = False) -> Path:
        resolved = original_resolve(path, strict=strict)
        if path == parent:
            intermediate.rename(tmp_path / "moved")
            intermediate.symlink_to(replacement, target_is_directory=True)
        return resolved

    # Deterministically inject the filesystem change between resolution and
    # verification; this simulates the timing, not a real second OS account.
    monkeypatch.setattr(text_editor_module, "_HISTORY_PARENT", parent)
    monkeypatch.setattr(Path, "resolve", resolve_then_swap)
    with pytest.raises(ToolException, match="History parent.*cannot be trusted"):
        text_editor_module._load_history()
    assert list((replacement / "temp").iterdir()) == []
    assert list((tmp_path / "moved" / "temp").iterdir()) == []


@pytest.mark.parametrize(
    "kind", ["symlink", "directory", "fifo", "hardlink", "exposed"]
)
def test_unsafe_history_file_is_not_discarded(
    private_history: Path, tmp_path: Path, kind: str
) -> None:
    other = tmp_path / "other.json"
    other.write_text("{}")
    other.chmod(0o600)
    if kind == "symlink":
        private_history.symlink_to(other)
    elif kind == "directory":
        private_history.mkdir()
    elif kind == "fifo":
        os.mkfifo(private_history)
    elif kind == "hardlink":
        os.link(other, private_history)
    else:
        private_history.write_text("{}")
        private_history.chmod(0o666)
    before = private_history.lstat()
    with pytest.raises(ToolException, match="Cannot read text_editor history"):
        text_editor_module._load_history()
    assert private_history.lstat() == before
    assert other.read_text() == "{}"


@pytest.mark.parametrize("command", ["create", "str_replace", "insert", "undo_edit"])
async def test_unsafe_history_prevents_edit(
    private_history: Path, tmp_path: Path, command: str
) -> None:
    private_history.parent.chmod(0o777)
    target = tmp_path / "target.txt"
    if command != "create":
        target.write_text("original")
    with pytest.raises(ToolException, match="Cannot access text_editor history"):
        if command == "create":
            await text_editor_module.create(str(target), "changed")
        elif command == "str_replace":
            await text_editor_module.str_replace(str(target), "original", "changed")
        elif command == "insert":
            await text_editor_module.insert(str(target), 0, "changed")
        else:
            await text_editor_module.undo_edit(str(target))
    assert (
        not target.exists() if command == "create" else target.read_text() == "original"
    )


def test_atomic_history_failure_keeps_previous_file(
    private_history: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_editor_module._save_history({Path("/x"): ["old"]})

    def interrupt(*args: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        text_editor_module._atomic_json_dump({Path("/x"): ["new"]}, private_history)
    assert text_editor_module._load_history() == {Path("/x"): ["old"]}
    assert list(private_history.parent.iterdir()) == [private_history]


def test_history_uses_effective_uid_at_access_time(
    private_history: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous_uid = os.geteuid()
    # Simulates a switch after importing the module; Docker coverage switches
    # real accounts through the CLI as well.
    monkeypatch.setattr(os, "geteuid", lambda: previous_uid + 1)
    monkeypatch.setattr(
        text_editor_module, "ensure_private_server_dir", lambda *a, **kw: None
    )
    monkeypatch.setattr(text_editor_module, "_HISTORY_PARENT", Path("/tmp"))
    assert (
        text_editor_module._history_path().parent.name
        == f"inspect-editor-{previous_uid + 1}"
    )
