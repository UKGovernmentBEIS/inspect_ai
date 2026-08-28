import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from inspect_ai.tool._sandbox_tools_utils import sandbox as sandbox_tools


def _completed(
    cmd: Sequence[str], returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, "", "")


def test_check_main_divergence_prefers_origin_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd == ["git", "rev-parse", "--git-dir"]:
            return _completed(cmd)
        if cmd == ["git", "rev-parse", "--verify", "origin/main"]:
            return _completed(cmd)
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return _completed(cmd)
        if cmd[:3] == ["git", "diff", "origin/main"]:
            return _completed(cmd)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert sandbox_tools._check_main_divergence(tmp_path.as_uri()) == "clean"
    assert ["git", "rev-parse", "--verify", "main"] not in calls


def test_check_main_divergence_falls_back_to_local_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd == ["git", "rev-parse", "--git-dir"]:
            return _completed(cmd)
        if cmd == ["git", "rev-parse", "--verify", "origin/main"]:
            return _completed(cmd, returncode=128)
        if cmd == ["git", "rev-parse", "--verify", "main"]:
            return _completed(cmd)
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return _completed(cmd)
        if cmd[:3] == ["git", "diff", "main"]:
            return _completed(cmd)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert sandbox_tools._check_main_divergence(tmp_path.as_uri()) == "clean"
    assert any(cmd[:3] == ["git", "diff", "main"] for cmd in calls)


def test_check_main_divergence_treats_git_diff_error_as_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd == ["git", "rev-parse", "--git-dir"]:
            return _completed(cmd)
        if cmd == ["git", "rev-parse", "--verify", "origin/main"]:
            return _completed(cmd)
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return _completed(cmd)
        if cmd[:3] == ["git", "diff", "origin/main"]:
            return _completed(cmd, returncode=128)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert sandbox_tools._check_main_divergence(tmp_path.as_uri()) == "clean"


def test_check_main_divergence_detects_uncommitted_edits_without_main_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd == ["git", "rev-parse", "--git-dir"]:
            return _completed(cmd)
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(
                cmd, 0, " M src/inspect_sandbox_tools/main.py\n", ""
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert sandbox_tools._check_main_divergence(tmp_path.as_uri()) == "edited"


def test_check_main_divergence_reports_real_diffs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd == ["git", "rev-parse", "--git-dir"]:
            return _completed(cmd)
        if cmd == ["git", "rev-parse", "--verify", "origin/main"]:
            return _completed(cmd)
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return _completed(cmd)
        if cmd[:3] == ["git", "diff", "origin/main"]:
            return _completed(cmd, returncode=1)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert sandbox_tools._check_main_divergence(tmp_path.as_uri()) == "edited"
