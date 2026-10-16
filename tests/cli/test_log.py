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
    result = _merge(f"{shards}/", "--json")
    assert result.exit_code == 0, result.output
    [item] = json.loads(result.output)
    assert item == {
        "source": f"{shards}/",
        "log": str(merged),
        "status": "success",
        "written": True,
        "shards": 2,
        "samples": 4,
        "missing": None,
        "running": [],
        "failed": [],
        "shards_deleted": False,
        "error": None,
    }


def test_merge_shards_selections(tmp_path: Path) -> None:
    shards = tmp_path / f"{NAME}.shards"
    _shard(shards, "0", [1, 2])
    merged = str(tmp_path / f"{NAME}.eval")
    result = _merge(merged, "--sample-id", "1,2,3", "--allow-incomplete", "--json")
    [item] = json.loads(result.output)
    assert item["status"] == "started" and item["missing"] == ["3"]
    result = _merge(merged, "--sample-count", "2")
    assert result.exit_code == 0, result.output
    assert "success" in result.output
    result = _merge(merged, "--sample-id", "1", "--sample-count", "1")
    assert result.exit_code == 2


def test_merge_shards_of_a_log_directory(tmp_path: Path) -> None:
    good = tmp_path / f"{NAME}.shards"
    _shard(good, "0", [1, 2, 3, 4])
    bad_name = NAME.replace("Zx7Run1Id", "Bad1Run2")
    bad = tmp_path / "sub" / f"{bad_name}.shards"
    _shard(bad, "0", [1, 2])
    _shard(bad, "1", [2, 3])

    result = _merge(str(tmp_path), "--sample-count", "4")
    assert result.exit_code == 2
    assert "log directory" in result.output

    result = _merge(str(tmp_path), "--json")
    assert result.exit_code == 1
    items = json.loads(result.output)
    assert [Path(i["log"]).name for i in items] == [f"{NAME}.eval", f"{bad_name}.eval"]
    assert all(i["source"] == str(tmp_path) for i in items)
    assert items[0]["status"] == "success" and items[0]["error"] is None
    assert "both select" in items[1]["error"] and items[1]["status"] is None


def test_merge_shards_reports_arguments_it_cannot_merge(tmp_path: Path) -> None:
    result = _merge(
        str(tmp_path / "missing"),
        str(tmp_path / f"{NAME}-recovered.eval"),
        "--json",
    )
    assert result.exit_code == 1
    missing, recovered = json.loads(result.output)
    assert missing["log"] is None and "No such log directory" in missing["error"]
    assert recovered["log"] is None and "recovered" in recovered["error"]


def test_merge_shards_deletes_shards(tmp_path: Path) -> None:
    shards = tmp_path / f"{NAME}.shards"
    _shard(shards, "0", [1, 2, 3, 4])
    result = _merge(str(tmp_path / f"{NAME}.eval"), "--delete-shards", "--json")
    assert result.exit_code == 0, result.output
    [item] = json.loads(result.output)
    assert item["shards_deleted"] is True
    assert not shards.exists()
