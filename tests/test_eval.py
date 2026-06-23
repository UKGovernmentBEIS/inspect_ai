import functools
import logging
import tempfile
from copy import deepcopy

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Epochs, Task, eval, eval_async, eval_set, task
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
