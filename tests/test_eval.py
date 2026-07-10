import functools
import logging
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import anyio
import pytest
from botocore.exceptions import ClientError
from test_helpers.utils import skip_if_no_docker

from inspect_ai import (
    Epochs,
    Task,
    TaskSource,
    eval,
    eval_async,
    eval_set,
    task,
    task_source,
)
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._util._async import tg_collect
from inspect_ai.approval._policy import ApprovalPolicyConfig, ApproverPolicyConfig
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match


def test_eval_epochs_sample_count():
    task = Task(dataset=[Sample(input="s1"), Sample(input="s2")])
    log = eval(task, model="mockllm/model", epochs=3)[0]
    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples) == 6  # 2 samples * 3 epochs


def _peak_model_concurrency(max_tasks: int | None) -> int:
    """Run one task against two models and return the peak concurrent models.

    A `record` solver brackets its work with enter/exit markers; the peak depth
    of overlapping enter/exit pairs is how many models ran at once.
    """
    from inspect_ai.solver import Generate, TaskState, solver

    events: list[str] = []

    @solver
    def record():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            events.append("enter")
            await anyio.sleep(0.2)
            events.append("exit")
            return state

        return solve

    task = Task(dataset=[Sample(input="x", target="y")], solver=[record()], name="t")
    eval(
        task,
        model=["mockllm/model", "mockllm/model2"],
        max_tasks=max_tasks,
        display="none",
    )

    depth = peak = 0
    for e in events:
        depth += 1 if e == "enter" else -1
        peak = max(peak, depth)
    return peak


def test_max_tasks_bounds_concurrent_models_single_task():
    # Regression for #4195: a single task definition fanned across models must
    # honor max_tasks. max_tasks=1 runs model-by-model; unset runs them all.
    assert _peak_model_concurrency(max_tasks=1) == 1
    assert _peak_model_concurrency(max_tasks=None) == 2


@pytest.mark.anyio
async def test_no_concurrent_eval_async():
    tasks = [
        Task(dataset=[Sample(input="Say Hello", target="Hello")], scorer=match())
        for i in range(0, 2)
    ]

    with pytest.raises(RuntimeError):
        await tg_collect(
            [
                functools.partial(eval_async, task, model="mockllm/model")
                for task in tasks
            ]
        )


def test_eval_config_override():
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        message_limit=10,
        epochs=Epochs(2, "at_least_1"),
        fail_on_error=True,
        scorer=match(),
    )

    log = eval(deepcopy(task), model="mockllm/model")[0]
    assert log.eval.config.message_limit == 10
    assert log.eval.config.epochs == 2
    assert log.eval.config.epochs_reducer == ["at_least_1"]
    assert log.eval.config.fail_on_error is True

    log = eval(
        deepcopy(task),
        message_limit=5,
        epochs=Epochs(5, "at_least_3"),
        fail_on_error=0.5,
        model="mockllm/model",
    )[0]
    assert log.eval.config.message_limit == 5
    assert log.eval.config.epochs == 5
    assert log.eval.config.epochs_reducer == ["at_least_3"]
    assert log.eval.config.fail_on_error == 0.5


def test_eval_approval_override():
    eval_approval = ApprovalPolicyConfig(
        approvers=[
            ApproverPolicyConfig(name="human", tools="human_tool"),
            ApproverPolicyConfig(name="auto", tools="auto_tool"),
        ]
    )
    task = Task(dataset=[Sample(input="Say Hello", target="Hello")], approval="auto")
    log = eval(
        deepcopy(task),
        model="mockllm/model",
        approval=eval_approval,
    )[0]
    assert log.eval.config.approval == eval_approval


@skip_if_no_docker
def test_eval_sandbox_init_when_first_task_has_no_sandbox():
    """Check that Sandbox initialization runs when ANY task has a sandbox, not just the first."""
    results = eval(
        tasks=[
            Task(dataset=[Sample(input="x")], name="no_sandbox"),
            Task(dataset=[Sample(input="x")], sandbox="docker", name="docker_sandbox"),
        ],
        model="mockllm/model",
        max_tasks=2,
    )
    assert len(results) == 2
    for r in results:
        assert r.status == "success", f"{r.eval.task}: {r.error}"


# -- unconsumed task_args warning (#4194) ------------------------------------
# task_args only apply to tasks resolved by specification (name, file,
# TaskInfo, task function/class, or cwd auto-discovery). When every task is a
# Task instance passed directly, task_args are silently ignored — eval() and
# eval_set() should warn.

TASK_ARGS_WARNING_SNIPPET = "will not be applied"


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


def _task_args_warnings(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if TASK_ARGS_WARNING_SNIPPET in r.message]


def test_task_instance_with_task_args_warns(capture_eval_warnings) -> None:
    caplog = capture_eval_warnings
    log = eval(
        task_args_warning_check(),
        task_args={"task_arg": "custom"},
        model="mockllm/model",
    )[0]
    assert log.status == "success"
    records = _task_args_warnings(caplog)
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
    assert len(_task_args_warnings(caplog)) == 1


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
    assert not _task_args_warnings(caplog)


def test_task_instance_without_task_args_no_warning(capture_eval_warnings) -> None:
    caplog = capture_eval_warnings
    log = eval(task_args_warning_check(), model="mockllm/model")[0]
    assert log.status == "success"
    assert not _task_args_warnings(caplog)


def test_eval_set_task_instance_warns_once(capture_eval_warnings) -> None:
    # eval_set re-enters resolution internally with ResolvedTask objects;
    # the warning must fire exactly once, not per resolution pass
    caplog = capture_eval_warnings
    with tempfile.TemporaryDirectory() as log_dir:
        success, _ = eval_set(
            tasks=task_args_warning_check(),
            task_args={"task_arg": "custom"},
            model="mockllm/model",
            log_dir=log_dir,
        )
    assert success
    records = _task_args_warnings(caplog)
    assert len(records) == 1, (
        f"expected exactly one unconsumed task_args warning, got {len(records)}"
    )


class _SeedTasks(TaskSource):
    def __init__(self, count: int) -> None:
        self._count = count

    def initial_tasks(self) -> list[Task]:
        return [
            Task(dataset=[Sample(input=f"t{i}")], name=f"t{i}")
            for i in range(self._count)
        ]

    async def next_tasks(self) -> list[Task] | None:
        return None


@task_source(name="task_args_warning_source")
def task_args_warning_source(count: int = 1) -> TaskSource:
    return _SeedTasks(count)


def test_task_source_with_task_args_no_warning(capture_eval_warnings) -> None:
    # task_args are consumed by the source (resolve_task_source) to build its
    # seed; resolving the seed Task instances must not false-warn (#4194)
    caplog = capture_eval_warnings
    logs = eval(
        "task_args_warning_source",
        task_args={"count": 2},
        model="mockllm/model",
        display="none",
    )
    assert all(log.status == "success" for log in logs)
    assert len(logs) == 2  # count applied by the source -> two seed tasks
    assert not _task_args_warnings(caplog)


# A failed log write must not tear down the whole run. Log writes at task
# start (the log_start() header flush) and the error-status log_finish() are
# the only exceptions that escape task_run(). If log storage (e.g. S3) is
# unreachable at that moment, the failure previously propagated out of
# _run_task() and crashed the entire eval — cancelling every sibling task. It
# should instead surface as an errored EvalLog so the task can be retried like
# any other task error.


@task
def log_write_failure_task() -> Task:
    return Task(
        dataset=[Sample(id=1, input="x", target="y")], name="log_write_failure_task"
    )


def _skew_error() -> ClientError:
    return ClientError(
        cast(
            Any,
            {
                "Error": {
                    "Code": "RequestTimeTooSkewed",
                    "Message": "The difference between the request time and the "
                    "current time is too large.",
                },
                "ResponseMetadata": {"RequestId": "request-1"},
            },
        ),
        "PutObject",
    )


def test_failed_log_start_returns_errored_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A permanently failing log_start yields an errored log, not a crash."""

    async def failing_log_start(self: TaskLogger, *args: Any, **kwargs: Any) -> None:
        raise _skew_error()

    monkeypatch.setattr(TaskLogger, "log_start", failing_log_start)

    logs = eval(
        log_write_failure_task(),
        model="mockllm/model",
        log_dir=str(tmp_path),
    )

    assert len(logs) == 1
    assert logs[0].status == "error"
    assert logs[0].error is not None
    assert "RequestTimeTooSkewed" in logs[0].error.message
    assert logs[0].location  # the path the failed write was destined for


def test_failed_log_start_is_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A transient log_start failure is retried and the task completes."""
    calls = {"n": 0}
    original_log_start = TaskLogger.log_start

    async def flaky_log_start(self: TaskLogger, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            # push the retry's `created` (second resolution) past the failed
            # attempt's so the retry gets a different log location and must
            # cope with the failed attempt's log never having been written
            await anyio.sleep(1.1)
            raise _skew_error()
        return await original_log_start(self, *args, **kwargs)

    monkeypatch.setattr(TaskLogger, "log_start", flaky_log_start)

    logs = eval(
        log_write_failure_task(),
        model="mockllm/model",
        log_dir=str(tmp_path),
        task_retry_attempts=1,
    )

    assert len(logs) == 1
    assert logs[0].status == "success"
    assert calls["n"] == 2
