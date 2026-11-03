import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from inspect_ai import Task, eval
from inspect_ai._cli.log import _TS_MONO_APP, log_command, view_type_resource
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match

_submodule_missing = not (_TS_MONO_APP / "src").exists()


@pytest.mark.skipif(_submodule_missing, reason="ts-mono submodule not initialized")
def test_view_type_resource():
    ts_types = view_type_resource("generated.ts")
    assert isinstance(ts_types, str)
    assert "auto-generated" in ts_types


# `inspect log merge-shards`

NAME = "2026-10-16T10-00-00-00-00_shardy_Zx7Run1Id"


def _shard(shards: Path, k: str, ids: list[int]) -> None:
    eval(
        Task(
            dataset=[Sample(id=i, input="q", target="x") for i in range(1, 5)],
            scorer=match(),
            name="shardy",
        ),
        model="mockllm/model",
        log_dir=str(shards / k),
        sample_id=ids,
        display="none",
    )


_TASK_FILE = """
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import {scorer}


@task
def shardy() -> Task:
    return Task(
        dataset=[Sample(id=i, input="q", target="x") for i in range(1, 5)],
        scorer={scorer}(),
    )
"""


def _task_spec(directory: Path, scorer: str = "match") -> str:
    """A `file.py@name` spec for the task `_shard` runs, or one with `scorer`."""
    path = directory / f"task_{scorer}.py"
    path.write_text(_TASK_FILE.format(scorer=scorer))
    return f"{path}@shardy"


def _merge(*args: str, task: str = "tasks.py@shardy") -> Any:
    return CliRunner().invoke(log_command, ["merge-shards", *args, "--task", task])


def test_merge_shards_of_a_merged_log_and_a_shards_dir(tmp_path: Path) -> None:
    shards = tmp_path / f"{NAME}.shards"
    _shard(shards, "0", [1, 2])
    merged = tmp_path / f"{NAME}.eval"
    spec = _task_spec(tmp_path)

    result = _merge(str(merged), task=spec)
    assert result.exit_code == 1
    assert "incomplete" in result.output

    result = _merge(str(merged), "--allow-incomplete", task=spec)
    assert result.exit_code == 0, result.output
    assert "started, 2 samples (2 new) from 1 shards" in result.output

    _shard(shards, "1", [3, 4])
    result = _merge(f"{shards}/", task=spec)
    assert result.exit_code == 0, result.output
    assert f"{merged}: success, 4 samples (2 new) from 2 shards" in result.output


def test_merge_shards_selections(tmp_path: Path) -> None:
    shards = tmp_path / f"{NAME}.shards"
    _shard(shards, "0", [1, 2])
    merged = str(tmp_path / f"{NAME}.eval")
    spec = _task_spec(tmp_path)
    result = _merge(merged, "--sample-id", "1,2,3", "--allow-incomplete", task=spec)
    assert result.exit_code == 0, result.output
    assert "started, 2 samples (2 new) from 1 shards, 1 missing" in result.output
    result = _merge(merged, "--sample-count", "2", task=spec)
    assert result.exit_code == 0, result.output
    assert "success" in result.output
    result = _merge(merged, "--sample-id", "1", "--sample-count", "1")
    assert result.exit_code == 2


def test_merge_shards_reports_an_argument_it_cannot_merge(tmp_path: Path) -> None:
    result = _merge(str(tmp_path / f"{NAME}-recovered.eval"))
    assert result.exit_code == 1
    assert "recovered" in result.output
    result = _merge(str(tmp_path))
    assert result.exit_code == 1
    assert "Expected a merged log" in result.output


def _json(result: Any) -> Any:
    return json.loads(result.stdout)


def test_merge_shards_json(tmp_path: Path) -> None:
    shards = tmp_path / f"{NAME}.shards"
    _shard(shards, "0", [1, 2])
    merged = tmp_path / f"{NAME}.eval"
    spec = _task_spec(tmp_path)
    result = _merge(
        str(merged), "--sample-id", "1,2,3", "--allow-incomplete", "--json", task=spec
    )
    assert result.exit_code == 0, result.output
    assert _json(result) == {
        "log": str(merged),
        "status": "started",
        "written": True,
        "shards": 1,
        "samples": 2,
        "new_samples": 2,
        "missing": ["3"],
        "running": [],
        "failed": [],
    }
    _shard(shards, "1", [3, 4])
    result = _merge(str(merged), "--sample-count", "4", "--json", task=spec)
    assert result.exit_code == 0, result.output
    item = _json(result)
    assert item["status"] == "success" and item["samples"] == 4
    # the shards are kept
    assert len(list(shards.glob("*/*.eval"))) == 2


def test_merge_shards_json_errors(tmp_path: Path) -> None:
    spec = _task_spec(tmp_path)

    def error(*args: str, task: str = spec) -> dict[str, Any]:
        result = _merge(*args, "--json", task=task)
        assert result.exit_code == 1, result.output
        [(key, value)] = _json(result).items()
        assert key == "error"
        return value

    merged = str(tmp_path / f"{NAME}.eval")
    shards = tmp_path / f"{NAME}.shards"

    usage = error(merged, "--sample-id", "1", "--sample-count", "1")
    assert usage["type"] == "UsageError" and "--sample-count" in usage["message"]

    missing = error(merged)
    assert missing["type"] == "FileNotFoundError" and merged in missing["message"]

    recovered = error(str(tmp_path / f"{NAME}-recovered.eval"))
    assert recovered["type"] == "ValueError" and "recovered" in recovered["message"]

    _shard(shards, "0", [1, 2])
    incomplete = error(merged)
    assert incomplete["type"] == "ShardSetIncomplete"
    assert incomplete["status"] == "started" and incomplete["missing"] is None
    assert incomplete["running"] == [] and incomplete["failed"] == []

    # a task other than the one the shards ran
    other = error(merged, "--allow-incomplete", task=_task_spec(tmp_path, "includes"))
    assert other["type"] == "ShardSetError" and "in its scorers" in other["message"]
    assert not Path(merged).exists()

    lock = tmp_path / f"{NAME}.merge.lock"
    lock.write_text('{"pid": 1, "host": "elsewhere"}')
    conflict = error(merged)
    assert (
        conflict["type"] == "WriteConflictError" and "elsewhere" in conflict["message"]
    )
    lock.unlink()

    (shards / f"{NAME}.eval").write_bytes(b"x")
    stray = error(merged)
    assert stray["type"] == "ShardSetError" and "not shard attempts" in stray["message"]


@pytest.mark.parametrize(
    "root",
    [
        "abfs://container@account.dfs.core.windows.net/logs",
        "gs://bucket/logs",
        "webhdfs://user@namenode:9870/logs",
        "memory://bucket/logs",
        "file:///tmp/cache::memory://bucket/logs",
        "s3://bucket/cache::memory://bucket/logs",
    ],
    ids=["abfs", "gs", "webhdfs", "memory", "file-chain", "s3-chain"],
)
def test_merge_shards_json_refuses_unsupported_storage(
    monkeypatch: pytest.MonkeyPatch, root: str
) -> None:
    from inspect_ai._util.asyncfiles import AsyncFilesystem

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("storage was accessed")

    monkeypatch.setattr("fsspec.core.url_to_fs", refuse)
    monkeypatch.setattr("fsspec.filesystem", refuse)
    monkeypatch.setattr(AsyncFilesystem, "s3_client", refuse)
    monkeypatch.setattr(AsyncFilesystem, "s3_client_async", refuse)
    merged = f"{root}/{NAME}.eval"
    result = _merge(merged, "--json")
    assert result.exit_code == 1, result.output
    assert _json(result) == {
        "error": {
            "type": "ValueError",
            "message": f"{merged} cannot be merged: shard merging supports "
            "local paths, file:// URIs and s3:// URLs only.",
        }
    }


def _merge_raising(monkeypatch: pytest.MonkeyPatch, ex: Exception) -> None:
    async def merge_shards(*args: Any, **kwargs: Any) -> Any:
        raise ex

    monkeypatch.setattr("inspect_ai.log._shards._api.merge_shards", merge_shards)


@pytest.mark.parametrize(
    "ex",
    [PermissionError("denied: x"), ImportError("no module s3fs"), KeyError("bug")],
    ids=["PermissionError", "ImportError", "KeyError"],
)
def test_merge_shards_json_reports_an_unexpected_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ex: Exception
) -> None:
    _merge_raising(monkeypatch, ex)
    merged = str(tmp_path / f"{NAME}.eval")
    result = _merge(merged, "--json")
    assert result.exit_code == 1, result.output
    assert _json(result) == {"error": {"type": type(ex).__name__, "message": str(ex)}}
    assert "Traceback" in result.stderr and str(ex) in result.stderr

    # without --json it propagates
    result = _merge(merged)
    assert result.exception is ex and result.stdout == ""


def test_merge_shards_json_reports_a_prerequisite_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai._util.error import PrerequisiteError

    _merge_raising(monkeypatch, PrerequisiteError("install s3fs"))
    result = _merge(str(tmp_path / f"{NAME}.eval"), "--json")
    assert result.exit_code == 1, result.output
    assert _json(result) == {
        "error": {"type": "PrerequisiteError", "message": "install s3fs"}
    }
    assert "install s3fs" in result.stderr and "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "stage",
    [
        "inspect_ai._cli.log.process_common_options",
        "inspect_ai._util.platform.platform_init",
    ],
    ids=["common_options", "platform_init"],
)
def test_merge_shards_json_reports_a_startup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    ex = PermissionError("denied at startup")

    def fail(*args: Any, **kwargs: Any) -> None:
        raise ex

    monkeypatch.setattr(stage, fail)
    merged = str(tmp_path / f"{NAME}.eval")
    result = _merge(merged, "--json")
    assert result.exit_code == 1, result.output
    assert _json(result) == {
        "error": {"type": "PermissionError", "message": "denied at startup"}
    }
    assert "Traceback" in result.stderr

    # without --json it propagates
    result = _merge(merged)
    assert result.exception is ex and result.stdout == ""


def test_merge_shards_json_reports_a_missing_required_hook(tmp_path: Path) -> None:
    # a fresh process: hook initialization is cached per process
    env = {**os.environ, "INSPECT_REQUIRED_HOOKS": "review_missing_hook"}
    command = [sys.executable, "-m", "inspect_ai", "log", "merge-shards"]
    merged = str(tmp_path / f"{NAME}.eval")
    command += [merged, "--task", "tasks.py@shardy"]
    result = subprocess.run(
        [*command, "--json"], capture_output=True, text=True, env=env
    )
    assert result.returncode == 1, result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "PrerequisiteError"
    assert "review_missing_hook" in error["message"]
    assert "review_missing_hook" in result.stderr and "Traceback" not in result.stderr

    # without --json the message is printed as before
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    assert result.returncode == 1
    assert "review_missing_hook" in result.stdout + result.stderr
