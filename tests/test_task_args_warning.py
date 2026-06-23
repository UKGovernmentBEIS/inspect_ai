"""Tests for the unconsumed task_args warning (#4194).

task_args only apply to tasks resolved by specification (name, file,
TaskInfo, task function/class, or cwd auto-discovery). When every task is
a Task instance passed directly, task_args are silently ignored — eval()
and eval_set() should warn.
"""

import logging
import tempfile

import pytest

from inspect_ai import Task, eval, eval_set, task
from inspect_ai.dataset import Sample

WARNING_SNIPPET = "will not be applied"


@task
def task_args_warning_check(task_arg: str = "default") -> Task:
    return Task(dataset=[Sample(input=f"{task_arg}: test input")])


@pytest.fixture
def capture_eval_warnings(caplog):
    # the warning is emitted from resolve_tasks (the loader module). attach
    # caplog's handler directly to the emitting module logger: eval()
    # reconfigures the package logger's propagation during the run, so
    # propagation-based capture misses warnings emitted mid-eval
    loader_logger = logging.getLogger("inspect_ai._eval.loader")
    loader_logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        loader_logger.removeHandler(caplog.handler)


def warning_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if WARNING_SNIPPET in r.message]


def test_task_instance_with_task_args_warns(capture_eval_warnings) -> None:
    caplog = capture_eval_warnings
    log = eval(
        task_args_warning_check(),
        task_args={"task_arg": "custom"},
        model="mockllm/model",
    )[0]
    assert log.status == "success"
    records = warning_records(caplog)
    assert len(records) == 1, "expected exactly one unconsumed task_args warning"
    assert "task_arg" in records[0].message


def test_task_instance_multiple_models_warns_once(capture_eval_warnings) -> None:
    # resolve_tasks runs once per model; the warning is gated to the first
    # model so it fires exactly once regardless of the model count
    caplog = capture_eval_warnings
    logs = eval(
        task_args_warning_check(),
        task_args={"task_arg": "custom"},
        model=["mockllm/model", "mockllm/model"],
    )
    assert all(log.status == "success" for log in logs)
    assert len(warning_records(caplog)) == 1


def test_string_task_with_task_args_no_warning(capture_eval_warnings) -> None:
    caplog = capture_eval_warnings
    log = eval(
        "task_args_warning_check",
        task_args={"task_arg": "custom"},
        model="mockllm/model",
    )[0]
    assert log.status == "success"
    # args actually applied
    assert log.eval.task_args["task_arg"] == "custom"
    assert not warning_records(caplog)


def test_task_instance_without_task_args_no_warning(capture_eval_warnings) -> None:
    caplog = capture_eval_warnings
    log = eval(task_args_warning_check(), model="mockllm/model")[0]
    assert log.status == "success"
    assert not warning_records(caplog)


def test_eval_set_task_instance_warns_once(capture_eval_warnings) -> None:
    # eval_set re-enters resolution internally with ResolvedTask objects;
    # the warning must fire exactly once, not per resolution pass
    caplog = capture_eval_warnings
    with tempfile.TemporaryDirectory() as log_dir:
        success, logs = eval_set(
            tasks=task_args_warning_check(),
            task_args={"task_arg": "custom"},
            model="mockllm/model",
            log_dir=log_dir,
        )
    assert success
    records = warning_records(caplog)
    assert len(records) == 1, (
        f"expected exactly one unconsumed task_args warning, got {len(records)}"
    )
