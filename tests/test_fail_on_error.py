from typing import Callable

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, TaskState, generate, solver


@solver
def failing_solver(fail: Callable[[TaskState], bool]):
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
        plan=[failing_solver(fail), generate()],
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
