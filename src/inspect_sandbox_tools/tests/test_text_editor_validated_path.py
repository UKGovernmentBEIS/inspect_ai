"""Unit tests for `_validated_path` in the text_editor sandbox tool."""

from pathlib import Path

import inspect_sandbox_tools._in_process_tools._text_editor.text_editor as text_editor_module
import pytest
from inspect_sandbox_tools._in_process_tools._text_editor.text_editor import (
    _validated_path,
)
from inspect_sandbox_tools._util.common_types import ToolException


def test_validated_path_rejects_too_long_filename() -> None:
    """Pathological long path from the model must raise ToolException, not OSError.

    Regression: UKGovernmentBEIS/inspect_ai#3689 — a 5000-char path component
    caused `path.exists()` to raise `OSError(ENAMETOOLONG)`, which propagated as
    JSON-RPC `-32098` and crashed the eval instead of being fed back to the model.
    """
    with pytest.raises(ToolException):
        _validated_path("a" * 5000, "view")


async def test_str_replace_recovers_from_truncated_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    history_path = tmp_path / "history.pkl"
    history_path.write_bytes(b"\x80\x04")
    monkeypatch.setattr(text_editor_module, "DEFAULT_HISTORY_PATH", str(history_path))

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
    monkeypatch.setattr(text_editor_module, "DEFAULT_HISTORY_PATH", str(history_path))

    def fail_dump(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(text_editor_module.pickle, "dump", fail_dump)
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
    monkeypatch.setattr(text_editor_module, "DEFAULT_HISTORY_PATH", str(history_path))

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
    monkeypatch.setattr(text_editor_module, "DEFAULT_HISTORY_PATH", str(history_path))

    target = tmp_path / "target.txt"
    target.write_text("current")

    with pytest.raises(ToolException, match="only retains the last 10 edits per file"):
        await text_editor_module.undo_edit(str(target))
