"""Tests for `inspect log exclude`."""

import json
from pathlib import Path

from click.testing import CliRunner

from inspect_ai import Epochs, Task, eval
from inspect_ai._cli.log import log_command
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import read_eval_log
from inspect_ai.scorer import match
from inspect_ai.scorer._metric import score_is_excluded


def test_log_exclude_command(tmp_path: Path) -> None:
    log = eval(
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
    log_file = log.location
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

    result = runner.invoke(
        log_command, ["exclude", log_file, "--sample", "zz", "--reason", "r"]
    )
    assert result.exit_code == 1
    assert "No sample matches: 'zz'" in result.output
