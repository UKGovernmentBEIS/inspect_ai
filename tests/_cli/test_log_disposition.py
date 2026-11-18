"""Tests for `inspect log exclude` and `inspect log zero`."""

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import inspect_ai._cli.log as cli_log
import inspect_ai.log as log_module
from inspect_ai import Epochs, Task, eval, task
from inspect_ai._cli.log import log_command
from inspect_ai._util.error import WriteConflictError
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import EvalLog, read_eval_log, write_eval_log
from inspect_ai.scorer import match
from inspect_ai.scorer._metric import score_is_excluded
from inspect_ai.solver import empty_attempt


@task
def disposition_task() -> Task:
    return Task(
        dataset=MemoryDataset(
            [Sample(id=id, input="", target="mockllm") for id in ("a", "b", "c")]
        ),
        scorer=match(location="any"),
        epochs=Epochs(2),
    )


def _eval_log(tmp_path: Path, **kwargs: Any) -> EvalLog:
    return eval(
        disposition_task(),
        model="mockllm/model",
        log_dir=tmp_path.as_posix(),
        display="none",
        **kwargs,
    )[0]


def test_log_exclude_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_file = _eval_log(tmp_path).location
    runner = CliRunner()

    args = ["exclude", log_file, "--sample", "a", "--sample", "b", "--epoch", "2"]
    args += ["--reason", "broken environment", "--author", "alice"]
    result = runner.invoke(log_command, args)

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "excluded 2 samples"
    assert lines[1].startswith("match/accuracy: ")

    written = read_eval_log(log_file)
    scores = {(s.id, s.epoch): (s.scores or {})["match"] for s in written.samples or []}
    excluded = {key: score for key, score in scores.items() if score_is_excluded(score)}
    assert sorted(excluded) == [("a", 2), ("b", 2)]
    provenance = excluded[("a", 2)].history[-1].provenance
    assert provenance is not None
    assert (provenance.author, provenance.reason) == ("alice", "broken environment")

    # epoch 2 of a is already excluded: it is excluded again
    result = runner.invoke(
        log_command, ["exclude", log_file, "--sample", "a", "--reason", "again"]
    )

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == "excluded 2 samples"
    written = read_eval_log(log_file)
    score = next(
        (s.scores or {})["match"]
        for s in written.samples or []
        if (s.id, s.epoch) == ("a", 2)
    )
    assert len(score.history) == len(excluded[("a", 2)].history) + 1
    provenance = score.history[-1].provenance
    assert provenance is not None and provenance.reason == "again"

    # every target already excluded: the log is still written
    writes: list[str] = []

    def counting_write(log: EvalLog, location: str, **kwargs: Any) -> None:
        writes.append(location)
        write_eval_log(log, location, **kwargs)

    monkeypatch.setattr(log_module, "write_eval_log", counting_write)
    result = runner.invoke(
        log_command, ["exclude", log_file, "--sample", "a", "--reason", "r"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == "excluded 2 samples"
    assert writes == [log_file]

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
        ["exclude", log_file, "--sample", "a", "--reason", "r"],
    )

    assert etags == ["etag-1"]
    assert result.exit_code == 1
    assert "the log changed since it was read" in result.output
    assert "excluded" not in result.output


def test_log_zero_command(tmp_path: Path) -> None:
    log_file = _eval_log(tmp_path).location
    empty_file = _eval_log(
        tmp_path / "empty", solver=empty_attempt(), sample_id=["a", "b"]
    ).location
    runner = CliRunner()

    args = ["zero", log_file, "--from", empty_file, "--sample", "a", "--sample", "b"]
    args += ["--epoch", "2", "--reason", "handed the answer", "--author", "alice"]
    result = runner.invoke(log_command, args)

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines == ["zeroed 2 samples", "match/accuracy: " + str(4 / 6)]

    written = read_eval_log(log_file)
    scores = {(s.id, s.epoch): (s.scores or {})["match"] for s in written.samples or []}
    zeroed = {key: score for key, score in scores.items() if score.reason == "zeroed"}
    assert sorted(zeroed) == [("a", 2), ("b", 2)]
    assert zeroed[("a", 2)].value == "I"
    assert zeroed[("a", 2)].history[0].value == "C"
    provenance = zeroed[("a", 2)].history[-1].provenance
    assert provenance is not None
    assert (provenance.author, provenance.reason) == ("alice", "handed the answer")

    result = runner.invoke(
        log_command,
        ["zero", log_file, "--from", empty_file, "--sample", "a", "--reason", "r"],
    )

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == "zeroed 2 samples"

    # a sample the empty attempt did not run is refused
    result = runner.invoke(
        log_command,
        ["zero", log_file, "--from", empty_file, "--sample", "c", "--reason", "r"],
    )
    assert result.exit_code == 1
    assert "the empty-attempt log has no such sample" in result.output
