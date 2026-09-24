from pathlib import Path

import pytest

from inspect_ai import Task, eval
from inspect_ai._util.constants import MODEL_NONE
from inspect_ai._util.environ import environ_var
from inspect_ai._util.file import basename
from inspect_ai._util.log_layout import (
    eval_checkpoints_dir,
    eval_log_for_shards_dir,
    eval_log_name,
    eval_shards_dir,
    log_basename,
)
from inspect_ai.log import EvalConfig, EvalDataset, EvalSpec
from inspect_ai.log._recorders.eval import EvalRecorder
from inspect_ai.util._checkpoint import _layout as checkpoint_layout


def test_log_filename():
    with environ_var("INSPECT_EVAL_LOG_FILE_PATTERN", "{task}_{model}_{id}"):
        log = eval(Task(), model="mockllm/model")[0]
        assert "mockllm-model" in log.location


def test_log_filename_no_plus_sign():
    log = eval(Task(), model="mockllm/model")[0]
    filename = log.location.split("/")[-1]
    assert "+" not in filename, f"Filename contains '+': {filename}"


def _eval_spec(task: str, task_id: str, created: str, model: str) -> EvalSpec:
    return EvalSpec(
        created=created,
        task=task,
        task_id=task_id,
        model=model,
        dataset=EvalDataset(name="test", samples=1),
        config=EvalConfig(),
    )


@pytest.mark.parametrize(
    "pattern,model,expected",
    [
        (None, "openai/gpt-5", "2026-09-24T09-39-00-00-00_my-task_abc-123"),
        (
            "{task}_{model}_{id}",
            "openai/gpt-5",
            "2026-09-24T09-39-00-00-00_my-task_openai-gpt-5_abc-123",
        ),
        (
            "{task}_{model}_{id}",
            MODEL_NONE,
            "2026-09-24T09-39-00-00-00_my-task__abc-123",
        ),
    ],
)
def test_eval_log_name_matches_recorder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pattern: str | None,
    model: str,
    expected: str,
) -> None:
    if pattern is None:
        monkeypatch.delenv("INSPECT_EVAL_LOG_FILE_PATTERN", raising=False)
    else:
        monkeypatch.setenv("INSPECT_EVAL_LOG_FILE_PATTERN", pattern)
    created = "2026-09-24T09:39:00+00:00"
    spec = _eval_spec("mypkg/my_task", "abc_123", created, model)
    recorder_key = EvalRecorder(str(tmp_path))._log_file_key(spec)
    name = eval_log_name(
        task="mypkg/my_task", task_id="abc_123", created=created, model=model
    )
    assert recorder_key == expected
    assert name == recorder_key


def test_eval_log_name_matches_eval_location() -> None:
    with environ_var("INSPECT_EVAL_LOG_FILE_PATTERN", "{task}_{model}_{id}"):
        log = eval(Task(), model="mockllm/model")[0]
        name = eval_log_name(
            task=log.eval.task,
            task_id=log.eval.task_id,
            created=log.eval.created,
            model=log.eval.model,
        )
    assert basename(log.location) == f"{name}.eval"


@pytest.mark.parametrize(
    "log,shards",
    [
        ("/logs/run.eval", "/logs/run.shards"),
        ("/run.eval", "/run.shards"),
        ("run.eval", "run.shards"),
        ("./logs/run.eval", "./logs/run.shards"),
        ("file:///tmp/my%20logs/run.eval", "file:///tmp/my%20logs/run.shards"),
        ("file:///run.eval", "file:///run.shards"),
        ("s3://bucket/logs/run.eval", "s3://bucket/logs/run.shards"),
        ("s3://bucket/run.eval", "s3://bucket/run.shards"),
    ],
)
def test_eval_shards_dir_round_trip(log: str, shards: str) -> None:
    assert eval_shards_dir(log) == shards
    assert eval_log_for_shards_dir(shards) == log
    assert eval_log_for_shards_dir(f"{shards}/") == log


@pytest.mark.parametrize(
    "log,shards",
    [
        ("C:\\logs\\run.eval", "C:\\logs\\run.shards"),
        ("\\\\server\\share\\run.eval", "\\\\server\\share\\run.shards"),
        ("logs\\run.eval", "logs\\run.shards"),
        (".\\run.eval", ".\\run.shards"),
    ],
)
def test_eval_shards_dir_round_trip_backslash_paths(log: str, shards: str) -> None:
    assert eval_shards_dir(log) == shards
    assert eval_log_for_shards_dir(shards) == log
    assert eval_log_for_shards_dir(f"{shards}\\") == log
    assert eval_log_for_shards_dir(f"{shards}\\\\") == log


@pytest.mark.parametrize(
    "recovered,shards,log",
    [
        ("/logs/run-recovered.eval", "/logs/run.shards", "/logs/run.eval"),
        ("run-recovered.eval", "run.shards", "run.eval"),
        (
            "file:///tmp/logs/run-recovered.eval",
            "file:///tmp/logs/run.shards",
            "file:///tmp/logs/run.eval",
        ),
        (
            "s3://bucket/logs/run-recovered.eval",
            "s3://bucket/logs/run.shards",
            "s3://bucket/logs/run.eval",
        ),
    ],
)
def test_eval_shards_dir_recovered_log(recovered: str, shards: str, log: str) -> None:
    assert eval_shards_dir(recovered) == shards
    assert eval_log_for_shards_dir(shards) == log


@pytest.mark.parametrize(
    "path", ["/logs/run", "/logs/run.checkpoints", "s3://bucket/logs/.shards"]
)
def test_eval_log_for_shards_dir_rejects_other_dirs(path: str) -> None:
    with pytest.raises(ValueError, match="Not a shards directory"):
        eval_log_for_shards_dir(path)


@pytest.mark.parametrize(
    "log,checkpoints",
    [
        ("/logs/run.eval", "/logs/run.checkpoints"),
        ("/logs/run-recovered.eval", "/logs/run.checkpoints"),
        ("file:///tmp/logs/run.eval", "file:///tmp/logs/run.checkpoints"),
        ("s3://bucket/logs/run-recovered.eval", "s3://bucket/logs/run.checkpoints"),
    ],
)
def test_eval_checkpoints_dir_shares_suffix_rule(log: str, checkpoints: str) -> None:
    assert eval_checkpoints_dir(log, None) == checkpoints
    assert checkpoint_layout.eval_checkpoints_dir(log, None) == checkpoints
    assert log_basename(log) == "run"
