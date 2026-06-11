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
from inspect_ai._eval.loader import task_args_apply_to_tasks
from inspect_ai.dataset import Sample

WARNING_SNIPPET = "will not be applied"


@task
def task_args_warning_check(task_arg: str = "default") -> Task:
    return Task(dataset=[Sample(input=f"{task_arg}: test input")])


# -- predicate unit tests ----------------------------------------------------


def test_predicate_task_instance() -> None:
    assert task_args_apply_to_tasks(task_args_warning_check()) is False


def test_predicate_task_instance_list() -> None:
    tasks = [task_args_warning_check(), task_args_warning_check()]
    assert task_args_apply_to_tasks(tasks) is False


def test_predicate_string_spec() -> None:
    assert task_args_apply_to_tasks("task_args_warning_check") is True


def test_predicate_mixed_list() -> None:
    # at least one element resolves by specification: args are applied
    assert (
        task_args_apply_to_tasks([task_args_warning_check(), "task_args_warning_check"])
        is True
    )


def test_predicate_task_function() -> None:
    # decorated task functions resolve via their registry name
    assert task_args_apply_to_tasks(task_args_warning_check) is True


def test_predicate_none_auto_discovery() -> None:
    assert task_args_apply_to_tasks(None) is True
    assert task_args_apply_to_tasks([]) is True


def test_predicate_resolved_tasks_skipped() -> None:
    # re-entrant resolution (eval_set internals): determination was made
    # on the first pass, so the predicate must opt out
    from inspect_ai._eval.loader import resolve_tasks
    from inspect_ai.model import get_model

    resolved_tasks = resolve_tasks(
        task_args_warning_check(),
        {},
        get_model("mockllm/model"),
        None,
        None,
        None,
    )
    assert task_args_apply_to_tasks(resolved_tasks) is None


# -- end-to-end warning tests ------------------------------------------------


@pytest.fixture
def capture_eval_warnings(caplog):
    # attach caplog's handler directly to the emitting module logger:
    # eval() reconfigures the package logger's propagation during the run,
    # so propagation-based capture misses warnings emitted mid-eval
    eval_logger = logging.getLogger("inspect_ai._eval.eval")
    eval_logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        eval_logger.removeHandler(caplog.handler)


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
