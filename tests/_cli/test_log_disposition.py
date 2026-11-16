"""Tests for `inspect log exclude`."""

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import inspect_ai._cli.log as cli_log
import inspect_ai.log as log_module
from inspect_ai import Epochs, Task, eval
from inspect_ai._cli.log import log_command
from inspect_ai._util.error import WriteConflictError
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import EvalLog, read_eval_log
from inspect_ai.scorer import match
from inspect_ai.scorer._metric import score_is_excluded


def _eval_log(tmp_path: Path) -> EvalLog:
    return eval(
        Task(
            dataset=MemoryDataset(
                [Sample(id=id, input="", target="x") for id in ("a", "b", "c")]
            ),
            scorer=match(),
            epochs=Epochs(2),
        ),
        model="mockllm/model",
        log_dir=tmp_path.as_posix(),
        display="none",
    )[0]


def test_log_exclude_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_file = _eval_log(tmp_path).location
    runner = CliRunner()

    args = ["exclude", log_file, "--sample", "a", "--sample", "b", "--epoch", "2"]
    args += ["--reason", "broken environment", "--author", "alice"]
    result = runner.invoke(log_command, args)

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[:2] == ["excluded a (epoch 2)", "excluded b (epoch 2)"]
    assert lines[2].startswith("match/accuracy: ")

    written = read_eval_log(log_file)
    scores = {(s.id, s.epoch): (s.scores or {})["match"] for s in written.samples or []}
    excluded = {key: score for key, score in scores.items() if score_is_excluded(score)}
    assert sorted(excluded) == [("a", 2), ("b", 2)]
    provenance = excluded[("a", 2)].history[-1].provenance
    assert provenance is not None
    assert (provenance.author, provenance.reason) == ("alice", "broken environment")

    result = runner.invoke(
        log_command,
        ["exclude", log_file, "--sample", "a", "--reason", "again", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "log": log_file,
        "applied": [["a", 1]],
        "unchanged": [["a", 2]],
    }

    # every target already excluded: nothing is written
    def no_write(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the log was written")

    monkeypatch.setattr(log_module, "write_eval_log", no_write)
    result = runner.invoke(
        log_command, ["exclude", log_file, "--sample", "a", "--reason", "r"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[:2] == [
        "unchanged a (epoch 1)",
        "unchanged a (epoch 2)",
    ]

    result = runner.invoke(
        log_command, ["exclude", log_file, "--sample", "zz", "--reason", "r"]
    )
    assert result.exit_code == 1
    assert "No sample matches: 'zz'" in result.output


def test_log_exclude_command_write_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_file = _eval_log(tmp_path).location

    def read_with_etag(location: str) -> EvalLog:
        log = read_eval_log(location)
        log.etag = "etag-1"
        return log

    etags: list[str | None] = []

    def conflicting_write(
        log: EvalLog, location: str, if_match_etag: str | None = None
    ) -> None:
        etags.append(if_match_etag)
        raise WriteConflictError("the log changed since it was read")

    monkeypatch.setattr(cli_log, "read_eval_log", read_with_etag)
    monkeypatch.setattr(log_module, "write_eval_log", conflicting_write)
    result = CliRunner().invoke(
        log_command,
        ["exclude", log_file, "--sample", "a", "--reason", "r", "--json"],
    )

    assert etags == ["etag-1"]
    assert result.exit_code == 1
    assert "the log changed since it was read" in result.output
    assert '"applied"' not in result.output
