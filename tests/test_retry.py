from random import random

from utils import skip_if_no_openai

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai.dataset import Sample
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


@skip_if_no_openai
def test_eval_retry():
    # run eval with a solver that fails 2/3 times
    failing_eval = f"{__file__}@failing_task"
    log = eval(failing_eval, limit=1)[0]

    # note the task id so we can be certain it remains the same
    task_id = log.eval.task_id

    # retry until we succeed (confirming the task_id is stable)
    while log.status != "success":
        log = eval_retry(log)[0]
        assert log.eval.task_id == task_id
