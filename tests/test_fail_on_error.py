from random import random
from typing import Callable

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import Generate, TaskState, generate, solver


@solver
def failing_solver(fail: Callable[[TaskState], bool] = lambda state: True):
    async def solve(state: TaskState, generate: Generate):
        if fail(state):
            raise ValueError("Eval failed!")

        return state

    return solve


def create_failing_task(
    samples: int,
    fail_on_error: bool | float | None,
    fail: Callable[[TaskState], bool] = lambda s: True,
):
    dataset: list[Sample] = []
    for i in range(0, samples):
        dataset.append(Sample(input="Say hello.", target="Hello"))

    return Task(
        dataset=dataset,
        solver=[failing_solver(fail), generate()],
        fail_on_error=fail_on_error,
    )


def eval_failing_task(
    samples: int,
    fail_on_error: bool | float | None,
    fail: Callable[[TaskState], bool] = lambda s: True,
):
    task = create_failing_task(samples, fail_on_error, fail)
    return eval(task, model="mockllm/model")[0]


def test_fail_on_error():
    log = eval_failing_task(1, True)
    assert log.status == "error"


def test_no_fail_on_error():
    log = eval_failing_task(1, False)
    assert log.status == "success"


def test_fail_on_num_errors():
    log = eval_failing_task(
        samples=10, fail_on_error=4, fail=lambda state: state.sample_id < 5
    )
    assert log.status == "error"
    log = eval_failing_task(
        samples=10, fail_on_error=4, fail=lambda state: state.sample_id < 3
    )
    assert log.results.completed_samples == 8
    assert log.status == "success"


def test_fail_on_pct_errors():
    log = eval_failing_task(
        samples=10, fail_on_error=0.35, fail=lambda state: state.sample_id < 5
    )
    assert log.status == "error"
    log = eval_failing_task(
        samples=10, fail_on_error=0.7, fail=lambda state: state.sample_id < 7
    )
    assert log.results.completed_samples == 4
    assert log.status == "success"


def test_fail_on_error_override():
    task = create_failing_task(
        samples=10, fail_on_error=0.7, fail=lambda state: state.sample_id < 7
    )
    log = eval(task, fail_on_error=0.6, model="mockllm/model")[0]
    assert log.status == "error"


@task
def fail_on_error_failing_task():
    return Task(
        dataset=[
            Sample(input="Say hello", target="hello"),
            Sample(input="Say hello", target="hello"),
            Sample(input="Say hello", target="hello"),
        ],
        solver=[failing_solver(lambda _s: random() > 0.33), generate()],
        fail_on_error=False,
        scorer=includes(),
    )


def test_fail_on_error_retry():
    # run eval with a solver that fails 2/3 times
    log = eval(fail_on_error_failing_task, model="mockllm/model")[0]

    # note the task id so we can be certain it remains the same
    task_id = log.eval.task_id

    # retry until we succeed (confirming the task_id is stable)
    while not log.results or (
        log.results.completed_samples < log.results.total_samples
    ):
        log = eval_retry(log)[0]
        assert log.eval.task_id == task_id


@task
def always_fails():
    return Task(
        solver=[failing_solver(), generate()],
    )


def test_fail_on_error_retry_override():
    # fail the first time
    log = eval(always_fails(), model="mockllm/model")[0]
    assert log.status == "error"

    # try again with fail_on_error = False
    log = eval_retry(log, fail_on_error=False)[0]
    assert log.status == "success"
