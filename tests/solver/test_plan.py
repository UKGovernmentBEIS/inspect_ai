import pytest

from inspect_ai import Task, eval_async
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


@pytest.mark.asyncio
async def test_plan_cleanup():
    @solver
    def failing_solver():
        async def solve(state: TaskState, generate: Generate):
            raise ValueError("Eval failed!")

        return solve

    cleaned_up = False

    def cleanup(state):
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
