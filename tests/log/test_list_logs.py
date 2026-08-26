from os.path import dirname, join
from pathlib import Path
from typing import Any, cast

import anyio
import pytest

from inspect_ai._util.file import filesystem
from inspect_ai.log import list_eval_logs, list_eval_logs_async
from inspect_ai.log._file import (
    EvalLogInfo,
    _walk_without_detail,
    manifest_eval_log_name,
)

file = Path(__file__)

log_dir = join(dirname(file), "test_list_logs")

ignored_files = ["ignore.json"]


def test_manifest_eval_log_name_uses_filesystem_separator() -> None:
    info = EvalLogInfo(
        name="logs\\2024-01-01_task.eval",
        type="file",
        size=100,
        mtime=1.0,
        task="task",
        task_id="1",
        suffix=None,
    )

    assert manifest_eval_log_name(info, "logs", "\\") == "2024-01-01_task.eval"


def test_manifest_eval_log_name_normalizes_manifest_separator() -> None:
    info = EvalLogInfo(
        name="logs/subdir/2024-01-01_task.eval",
        type="file",
        size=100,
        mtime=1.0,
        task="task",
        task_id="1",
        suffix=None,
    )

    assert manifest_eval_log_name(info, "logs", "/") == "subdir/2024-01-01_task.eval"


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


def _s3_error_fs(monkeypatch: pytest.MonkeyPatch, error_factory):
    """Return a filesystem that raises the given error on iter_files (S3 path)."""

    def s3_style_filesystem(path: str, fs_options: dict[str, Any] = {}) -> Any:
        fs = filesystem(path, fs_options)
        monkeypatch.setattr(fs, "is_s3", lambda: True)
        monkeypatch.setattr(fs, "is_async", lambda: True)
        # Force the code path down the `fs.is_s3() and not fs_options` branch
        return fs

    monkeypatch.setattr("inspect_ai.log._file.filesystem", s3_style_filesystem)
    monkeypatch.setattr(
        "inspect_ai.log._file.AsyncFilesystem",
        error_factory,
    )
    return s3_style_filesystem


@pytest.mark.anyio
async def test_list_logs_async_s3_auth_error_degrades(monkeypatch: pytest.MonkeyPatch):
    """An S3 credential/denial error must degrade to an empty listing, not raise."""
    from botocore.exceptions import ClientError

    class _RaisesClientError:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise ClientError(
                {
                    "Error": {
                        "Code": "AccessDenied",
                        "Message": "Access Denied",
                    },
                    "ResponseMetadata": {"HTTPStatusCode": 403},
                },
                "ListObjectsV2",
            )

        async def __aexit__(self, *args):
            return False

    def error_factory(*args, **kwargs):
        return _RaisesClientError()

    _s3_error_fs(monkeypatch, error_factory)

    logs = await list_eval_logs_async("s3://bucket/logs", formats=["eval"])
    assert logs == []


@pytest.mark.anyio
async def test_list_logs_async_s3_no_credentials_degrades(
    monkeypatch: pytest.MonkeyPatch,
):
    """Missing credentials must degrade to an empty listing, not raise."""
    from botocore.exceptions import NoCredentialsError

    class _RaisesNoCredentials:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise NoCredentialsError()

        async def __aexit__(self, *args):
            return False

    def error_factory(*args, **kwargs):
        return _RaisesNoCredentials()

    _s3_error_fs(monkeypatch, error_factory)

    logs = await list_eval_logs_async("s3://bucket/logs", formats=["eval"])
    assert logs == []


def _client_error() -> Exception:
    from botocore.exceptions import ClientError

    return ClientError(
        {
            "Error": {"Code": "AccessDenied", "Message": "Access Denied"},
            "ResponseMetadata": {
                "HTTPStatusCode": 403,
                "RequestId": "test-request-id",
                "HostId": "test-host-id",
                "HTTPHeaders": {},
                "RetryAttempts": 0,
            },
        },
        "ListObjectsV2",
    )


def test_list_logs_trio_sync_s3_auth_error_degrades(
    monkeypatch: pytest.MonkeyPatch,
):
    """Generic trio-sync branch: S3 auth errors degrade to an empty listing (#4914)."""
    import anyio

    class _SyncErrorFs:
        def is_async(self) -> bool:
            return True

        def is_s3(self) -> bool:
            return True

        def exists(self, path: str) -> bool:
            raise _client_error()

        def ls(self, path: str, recursive: bool = False) -> list:
            return []

    monkeypatch.setattr(
        "inspect_ai.log._file.filesystem",
        lambda path, fs_options={}: _SyncErrorFs(),
    )
    monkeypatch.setattr(
        "inspect_ai.log._file.current_async_backend",
        lambda: "trio",
    )

    async def check() -> None:
        logs = await list_eval_logs_async(
            "s3://bucket/logs", formats=["eval"], fs_options={"endpoint": "https://x"}
        )
        assert logs == []

    anyio.run(check, backend="trio")


def test_list_logs_async_s3_auth_error_degrades_with_fs_options(
    monkeypatch: pytest.MonkeyPatch,
):
    """Generic asyncio branch (fs_options set): S3 auth errors degrade to empty (#4914)."""
    import asyncio

    class _AsyncErrorFs:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def _exists(self, path: str) -> bool:
            raise _client_error()

        def invalidate_cache(self, path: str) -> None:
            pass

        async def _ls(self, path: str, detail: bool = True) -> list:
            return []

    captured: dict[str, Any] = {}

    def fake_async_filesystem(path: str, fs_options=None):
        captured["fs_options"] = fs_options
        return _AsyncErrorFs()

    def s3_style_filesystem(path: str, fs_options: dict[str, Any] = {}) -> Any:
        fs = filesystem(path, fs_options)
        monkeypatch.setattr(fs, "is_s3", lambda: True)
        monkeypatch.setattr(fs, "is_async", lambda: True)
        return fs

    monkeypatch.setattr("inspect_ai.log._file.filesystem", s3_style_filesystem)
    monkeypatch.setattr(
        "inspect_ai.log._file.async_filesystem",
        fake_async_filesystem,
    )
    monkeypatch.setattr(
        "inspect_ai.log._file.current_async_backend",
        lambda: "asyncio",
    )

    async def check() -> list:
        return await list_eval_logs_async(
            "s3://bucket/logs",
            formats=["eval"],
            fs_options={"endpoint": "https://minio.local"},
        )

    assert asyncio.run(check()) == []
    # fs_options must actually reach the generic branch for this test to be
    # meaningful — it is what forces the slow path in production.
    assert captured["fs_options"] == {"endpoint": "https://minio.local"}
