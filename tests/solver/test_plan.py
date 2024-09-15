from random import random
import pytest

from inspect_ai import Task, eval, eval_async, eval_retry, task
from inspect_ai._util.registry import registry_info
from inspect_ai.dataset import Sample
from inspect_ai.solver import (
    Generate,
    Plan,
    TaskState,
    chain_of_thought,
    generate,
    plan,
    solver,
)


@plan(fancy=True)
def my_plan() -> Plan:
    return Plan(steps=[chain_of_thought(), generate()])


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


def test_plan_registration():
    plan = my_plan()
    assert registry_info(plan).name == "my_plan"


def test_plan_attribs():
    plan = my_plan()
    assert registry_info(plan).metadata["attribs"]["fancy"] is True


@plan
def the_plan(rate=1.0):
    return Plan(steps=[failing_solver(rate), generate()])


@task
def the_task(plan: Plan = Plan(generate())):
    return Task(
        dataset=[Sample(input="Say hello.", target="Hello")],
        plan=plan,
    )


def test_plan_retry():
    log = eval(the_task(the_plan()), plan=the_plan(1.0), model="mockllm/model")[0]
    assert log.eval.plan == "the_plan"
    assert log.eval.plan_args == {"rate": 1.0}
    assert log.plan.steps[0].params["rate"] == 1.0

    log = eval_retry(log)[0]
    assert log.eval.plan == "the_plan"
    assert log.eval.plan_args == {"rate": 1.0}
    assert log.plan.steps[0].params["rate"] == 1.0
