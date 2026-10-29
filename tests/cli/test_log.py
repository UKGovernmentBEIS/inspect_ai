import json
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


def _merge(*args: str) -> Any:
    return CliRunner().invoke(log_command, ["merge-shards", *args])


def test_merge_shards_of_a_merged_log_and_a_shards_dir(tmp_path: Path) -> None:
    shards = tmp_path / f"{NAME}.shards"
    _shard(shards, "0", [1, 2])
    merged = tmp_path / f"{NAME}.eval"

    result = _merge(str(merged))
    assert result.exit_code == 1
    assert "incomplete" in result.output

    result = _merge(str(merged), "--allow-incomplete")
    assert result.exit_code == 0, result.output
    assert "started, 2 samples (2 new) from 1 shards" in result.output

    _shard(shards, "1", [3, 4])
    result = _merge(f"{shards}/")
    assert result.exit_code == 0, result.output
    assert f"{merged}: success, 4 samples (2 new) from 2 shards" in result.output


def test_merge_shards_selections(tmp_path: Path) -> None:
    shards = tmp_path / f"{NAME}.shards"
    _shard(shards, "0", [1, 2])
    merged = str(tmp_path / f"{NAME}.eval")
    result = _merge(merged, "--sample-id", "1,2,3", "--allow-incomplete")
    assert result.exit_code == 0, result.output
    assert "started, 2 samples (2 new) from 1 shards, 1 missing" in result.output
    result = _merge(merged, "--sample-count", "2")
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


def test_merge_shards_deletes_shards(tmp_path: Path) -> None:
    shards = tmp_path / f"{NAME}.shards"
    _shard(shards, "0", [1, 2, 3, 4])
    result = _merge(str(tmp_path / f"{NAME}.eval"), "--delete-shards")
    assert result.exit_code == 0, result.output
    assert "shards deleted" in result.output
    assert not shards.exists()


def _json(result: Any) -> Any:
    return json.loads(result.stdout)


def test_merge_shards_json(tmp_path: Path) -> None:
    shards = tmp_path / f"{NAME}.shards"
    _shard(shards, "0", [1, 2])
    merged = tmp_path / f"{NAME}.eval"
    result = _merge(str(merged), "--sample-id", "1,2,3", "--allow-incomplete", "--json")
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
        "shards_deleted": False,
    }
    _shard(shards, "1", [3, 4])
    result = _merge(str(merged), "--sample-count", "4", "--delete-shards", "--json")
    assert result.exit_code == 0, result.output
    item = _json(result)
    assert item["status"] == "success" and item["samples"] == 4
    assert item["shards_deleted"] is True and not shards.exists()


def test_merge_shards_json_errors(tmp_path: Path) -> None:
    def error(*args: str) -> dict[str, Any]:
        result = _merge(*args, "--json")
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
