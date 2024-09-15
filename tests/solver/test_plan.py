import os
from random import random

import pytest

from inspect_ai import Task, eval, eval_async, eval_retry, task
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.solver import (
    Generate,
    Plan,
    PlanSpec,
    TaskState,
    chain_of_thought,
    generate,
    plan,
    solver,
)


@solver
def failing_solver(rate=1.0):
    async def solve(state: TaskState, generate: Generate):
        if random() <= rate:
            raise ValueError("Eval failed!")
        return state

    return solve


@pytest.mark.asyncio
async def test_plan_cleanup():
    @solver
    def failing_solver():
        async def solve(state: TaskState, generate: Generate):
            raise ValueError("Eval failed!")

        return solve

    cleaned_up = False

    async def cleanup(state):
        nonlocal cleaned_up
        cleaned_up = True

    task = Task(
        dataset=[Sample(input="Say hello.", target="Hello")],
        plan=Plan(
            steps=[chain_of_thought(), failing_solver(), generate()], cleanup=cleanup
        ),
    )

    result = await eval_async(tasks=task, model="mockllm/model")

    assert result[0].status == "error"
    assert cleaned_up


@plan
def the_plan(rate=1.0):
    return Plan(steps=[failing_solver(rate), generate()])


@task
def the_task(plan: Plan = Plan(generate())):
    return Task(
        dataset=[Sample(input="Say hello.", target="Hello")],
        plan=plan,
    )


def test_plan_spec():
    plan_file = f"{os.path.relpath(__file__)}"

    def check_plan_spec(plan_spec: str):
        log = eval(
            f"{plan_file}@the_task",
            plan=PlanSpec(plan_spec, {"rate": 1.0}),
        )[0]
        check_plan(log, plan_spec)

    check_plan_spec("the_plan")
    check_plan_spec(plan_file)
    check_plan_spec(f"{plan_file}@the_plan")


def test_plan_retry():
    log = eval(the_task(), plan=the_plan(1.0), model="mockllm/model")[0]
    check_plan(log)

    log = eval_retry(log)[0]
    check_plan(log)


def check_plan(log: EvalLog, plan_name="the_plan"):
    assert log.eval.plan == plan_name
    assert log.eval.plan_args == {"rate": 1.0}
    assert log.plan.steps[0].params["rate"] == 1.0
