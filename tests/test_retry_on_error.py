import random

from test_helpers.utils import failing_solver_deterministic, skip_if_github_action

from inspect_ai import Task, eval
from inspect_ai.dataset import example_dataset
from inspect_ai.solver._prompt import system_message


def test_retry_on_error():
    task = Task(solver=failing_solver_deterministic([True, False]))
    log = eval(task, retry_on_error=1)[0]
    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples[0].error_retries) == 1


def test_no_retry_on_error():
    task = Task(solver=failing_solver_deterministic([True, False]))
    log = eval(task, fail_on_error=False)[0]
    assert log.status == "success"
    assert log.samples is not None
    assert log.samples[0].error is not None
    assert len(log.samples[0].error_retries) == 0


def test_retry_on_error_state():
    task = Task(
        solver=[
            system_message("do your best!"),
            failing_solver_deterministic([True, False]),
        ]
    )
    log = eval(task, retry_on_error=1)[0]
    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples[0].messages) == 2


def test_retry_on_error_then_fail():
    task = Task(solver=failing_solver_deterministic([True, True, True, True]))
    log = eval(task, retry_on_error=3)[0]
    assert log.status == "error"
    assert log.samples is not None
    assert len(log.samples[0].error_retries) == 3
    assert log.samples[0].error is not None


@skip_if_github_action
def test_retry_on_error_concurrency():
    dataset = example_dataset("theory_of_mind")
    solver_failures = [True, False] * len(dataset) * 5
    random.shuffle(solver_failures)
    task = Task(dataset=dataset, solver=failing_solver_deterministic(solver_failures))
    log = eval(task, max_samples=5, retry_on_error=10, fail_on_error=False)[0]
    assert log.status == "success"
    assert log.samples
    retries = 0
    for sample in log.samples:
        sample_retries = len(sample.error_retries)
        retries += sample_retries

    # retries should be around 100 but randomness will cause some divergence
    assert retries > 50 and retries < 150
