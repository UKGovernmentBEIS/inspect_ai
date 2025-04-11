import asyncio

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import exact
from inspect_ai.solver._fork import fork
from inspect_ai.solver._solver import Generate, solver
from inspect_ai.solver._task_state import TaskState

# This is the simplest possible Inspect eval, useful for testing your configuration / network / platform etc.


@solver
def my_solver():
    async def solve(state: TaskState, generate: Generate):
        await generate(state)

        results = await fork(state, [inner_fork() for _ in range(3)])

        print(results)

        return state

    return solve


@solver
def inner_fork():
    async def solve(state: TaskState, generate: Generate):
        await generate(state)
        await asyncio.sleep(0)
        await generate(state)
        await asyncio.sleep(0)
        await generate(state)

        return state

    return solve


@task
def hello_world():
    return Task(
        dataset=[
            Sample(
                input="Just reply with Hello World",
                target="Hello World",
            )
        ],
        solver=[my_solver()],
        scorer=exact(),
        message_limit=4,
    )


if __name__ == "__main__":
    eval(hello_world(), model="mockllm/model")
