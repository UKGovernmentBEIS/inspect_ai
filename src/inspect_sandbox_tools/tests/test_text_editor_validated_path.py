"""Unit tests for `_validated_path` in the text_editor sandbox tool."""

import asyncio
import json
import os
import pickle
import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import inspect_sandbox_tools._in_process_tools._text_editor.text_editor as text_editor_module
import pytest
from inspect_sandbox_tools._in_process_tools._text_editor._run import CommandResult, run
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


@pytest.mark.parametrize("returncode", [0, 1])
async def test_view_directory_rejects_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, returncode: int
) -> None:
    monkeypatch.setattr(
        text_editor_module,
        "run",
        AsyncMock(
            return_value=CommandResult(
                returncode=returncode,
                stdout="partial listing",
                stderr="permission denied",
            )
        ),
    )
    with pytest.raises(ToolException, match="permission denied"):
        await text_editor_module.view(str(tmp_path))


@pytest.mark.parametrize("missing", [False, True])
def test_view_directory_launch_failure_is_tool_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing: bool,
) -> None:
    from inspect_sandbox_tools._cli.main import _exec

    monkeypatch.setenv("PATH", str(tmp_path))
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


@pytest.mark.parametrize("cancel", [False, True])
async def test_directory_command_reaped_when_interrupted(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    create_subprocess_exec = asyncio.create_subprocess_exec
    started = asyncio.Event()
    processes: list[asyncio.subprocess.Process] = []

    async def start(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        process = await create_subprocess_exec(
            sys.executable,
            "-c",
            "import time; print('ready', flush=True); time.sleep(60)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        processes.append(process)
        assert process.stdout is not None
        assert await process.stdout.readline() == b"ready\n"
        started.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    task = asyncio.create_task(run(["find", "/unused"], timeout=None if cancel else 0))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        assert processes[0].returncode is not None
    finally:
        task.cancel()
        for process in processes:
            if process.returncode is None:
                process.kill()
            await process.wait()


def _set_history_path(monkeypatch: pytest.MonkeyPatch, history_path: Path) -> None:
    monkeypatch.setattr(text_editor_module, "DEFAULT_HISTORY_PATH", str(history_path))
    # DEFAULT_HISTORY_PATH is bound into these defaults at function definition time.
    monkeypatch.setattr(
        text_editor_module._load_history, "__defaults__", (str(history_path),)
    )
    monkeypatch.setattr(
        text_editor_module._save_history, "__defaults__", (str(history_path),)
    )


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
    history_path = tmp_path / "history.pkl"
    history_path.write_bytes(b"\x80\x04")
    _set_history_path(monkeypatch, history_path)

    target = tmp_path / "target.txt"
    target.write_text("before\n")

    result = await text_editor_module.str_replace(str(target), "before", "after")

    assert target.read_text() == "after\n"
    assert f"The file {target}" in result
    assert text_editor_module._load_history(str(history_path))[target.resolve()] == [
        "before\n"
    ]


async def test_str_replace_continues_when_history_save_fails(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    history_path = tmp_path / "history.pkl"
    _set_history_path(monkeypatch, history_path)

    def fail_dump(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(pickle, "dump", fail_dump)
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
    history_path = tmp_path / "history.pkl"
    _set_history_path(monkeypatch, history_path)

    target = (tmp_path / "target.txt").resolve()
    other_target = (tmp_path / "other.txt").resolve()
    for i in range(12):
        text_editor_module._add_history_entry(target, f"old {i}")
    text_editor_module._add_history_entry(other_target, "other old")

    history = text_editor_module._load_history(str(history_path))

    assert history[target] == [f"old {i}" for i in range(2, 12)]
    assert history[other_target] == ["other old"]


async def test_undo_edit_reports_retained_history_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    history_path = tmp_path / "history.pkl"
    _set_history_path(monkeypatch, history_path)

    target = tmp_path / "target.txt"
    target.write_text("current")

    with pytest.raises(ToolException, match="only retains the last 10 edits per file"):
        await text_editor_module.undo_edit(str(target))
