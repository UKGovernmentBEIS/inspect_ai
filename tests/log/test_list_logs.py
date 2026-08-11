from os.path import dirname, join
from pathlib import Path
from typing import Any, cast

import anyio
import pytest

from inspect_ai._util.file import filesystem
from inspect_ai.log import list_eval_logs, list_eval_logs_async
from inspect_ai.log._file import _walk_without_detail

file = Path(__file__)

log_dir = join(dirname(file), "test_list_logs")

ignored_files = ["ignore.json"]


def test_list_logs():
    logs = list_eval_logs(log_dir, formats=["eval", "json"])
    names = [log.name for log in logs]

    assert len(logs) == 3
    assert all(file not in names for file in ignored_files)


async def test_list_logs_async_matches_sync():
    sync_names = sorted(
        log.name for log in list_eval_logs(log_dir, formats=["eval", "json"])
    )
    async_names = sorted(
        log.name
        for log in await list_eval_logs_async(log_dir, formats=["eval", "json"])
    )

    assert async_names == sync_names


async def test_list_logs_async_missing_dir(tmp_path: Path):
    logs = await list_eval_logs_async(str(tmp_path / "does-not-exist"))

    assert logs == []


async def _check_list_logs_async_filter() -> None:
    logs = await list_eval_logs_async(
        log_dir, formats=["eval", "json"], filter=lambda log: True
    )
    names = [log.name for log in logs]

    assert len(logs) == 3
    assert all(file not in names for file in ignored_files)


async def test_list_logs_async_filter():
    await _check_list_logs_async_filter()


async def test_list_logs_async_filter_excludes_all():
    logs = await list_eval_logs_async(
        log_dir, formats=["eval", "json"], filter=lambda log: False
    )

    assert logs == []


async def _check_list_logs_async_header_fallback() -> None:
    # custom.eval has a non-conforming filename, so its task/task_id must be
    # resolved by reading the log header — verify this works on both backends
    # (under trio a sync header read would silently degrade to empty fields)
    logs = await list_eval_logs_async(log_dir, formats=["eval", "json"])
    custom = next(log for log in logs if log.name.endswith("custom.eval"))
    assert custom.task == "input_task"
    assert custom.task_id == "hxs4q9azL3ySGkjJirypKZ"


async def test_list_logs_async_header_fallback():
    await _check_list_logs_async_header_fallback()


async def test_list_logs_unfiltered_in_async_context():
    # unfiltered sync listing is backend-agnostic (the trio guard is filter-only)
    logs = list_eval_logs(log_dir, formats=["eval", "json"])
    assert len(logs) == 3


async def test_walk_without_detail_error_handling():
    # unlistable directories are skipped (fsspec walk's on_error="omit"
    # semantics), while non-OSError failures propagate
    class FakeFS:
        async def _ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
            if path == "root":
                return [
                    {"name": "root/a.eval", "type": "file"},
                    {"name": "root/ok", "type": "directory"},
                    {"name": "root/denied", "type": "directory"},
                ]
            elif path == "root/ok":
                return [{"name": "root/ok/b.eval", "type": "file"}]
            elif path == "root/denied":
                raise PermissionError("access denied")
            else:
                raise ValueError(f"unexpected path {path}")

    files = await _walk_without_detail(cast(Any, FakeFS()), "root")
    names = {file["name"] for file in files}
    assert "root/a.eval" in names
    assert "root/ok/b.eval" in names

    class FailingFS:
        async def _ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
            raise ValueError("auth failure")

    with pytest.raises(ValueError, match="auth failure"):
        await _walk_without_detail(cast(Any, FailingFS()), "root")


# NOTE: The trio tests below use anyio.run(backend="trio") directly so the
# trio paths run on regular CI, which has no --runtrio leg (see the NOTE
# above the trio tests in test_eval_log.py).


def test_list_logs_filter_trio_guard():
    async def check() -> None:
        with pytest.raises(RuntimeError, match="list_eval_logs_async"):
            list_eval_logs(log_dir, formats=["eval", "json"], filter=lambda log: True)

    anyio.run(check, backend="trio")


def test_list_logs_async_filter_trio():
    anyio.run(_check_list_logs_async_filter, backend="trio")


def test_list_logs_async_header_fallback_trio():
    anyio.run(_check_list_logs_async_header_fallback, backend="trio")


def test_list_logs_async_remote_fs_trio(monkeypatch: pytest.MonkeyPatch):
    # remote (async) filesystems must be listed via the backend-agnostic sync
    # fallback under trio (fsspec's asynchronous=True mode is asyncio-only) —
    # simulate one by marking the local filesystem async
    def remote_style_filesystem(path: str, fs_options: dict[str, Any] = {}) -> Any:
        fs = filesystem(path, fs_options)
        monkeypatch.setattr(fs, "is_async", lambda: True)
        return fs

    monkeypatch.setattr("inspect_ai.log._file.filesystem", remote_style_filesystem)

    async def check() -> None:
        logs = await list_eval_logs_async(log_dir, formats=["eval", "json"])
        assert len(logs) == 3

    anyio.run(check, backend="trio")
