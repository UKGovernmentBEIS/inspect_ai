import functools
from copy import deepcopy

import pytest

from inspect_ai import Epochs, Task, eval, eval_async
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
