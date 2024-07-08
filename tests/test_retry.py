import tempfile
from random import random

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai.dataset import Sample
from inspect_ai.log import list_eval_logs, retryable_eval_logs
from inspect_ai.scorer import match
from inspect_ai.solver import Generate, TaskState, generate, solver


@solver
def failing_solver():
    async def solve(state: TaskState, generate: Generate):
        if random() > 0.33:
            raise ValueError("Eval failed!")

        return state

    return solve


@task
def failing_task():
    return Task(
        dataset=[Sample(input="Say hello", target="hello")],
        plan=[failing_solver(), generate()],
        scorer=match(),
    )


def test_eval_retry():
    # run eval with a solver that fails 2/3 times
    failing_eval = f"{__file__}@failing_task"
    log = eval(tasks=failing_eval, limit=1, model="mockllm/model")[0]

    # note the task id so we can be certain it remains the same
    task_id = log.eval.task_id

    # retry until we succeed (confirming the task_id is stable)
    while log.status != "success":
        log = eval_retry(log)[0]
        assert log.eval.task_id == task_id


def test_eval_retryable():
    with tempfile.TemporaryDirectory() as log_dir:
        # run eval with a solver that fails 2/3 of the time
        failing_eval = f"{__file__}@failing_task"
        log = eval(tasks=failing_eval, limit=1, model="mockllm/model", log_dir=log_dir)[
            0
        ]

        # note the task id so we can be certain it remains the same
        task_id = log.eval.task_id

        # retry until we succeed (confirming the task_id is stable)
        retryable = retryable_eval_logs(list_eval_logs(log_dir))
        while len(retryable) > 0:
            assert len(retryable) == 1
            assert retryable[0].task_id == task_id
            eval_retry(retryable, log_dir=log_dir)
            retryable = retryable_eval_logs(list_eval_logs(log_dir))
