from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import exact
from inspect_ai.solver._fork import fork
from inspect_ai.solver._solver import Generate, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._limit import message_limit


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
        with message_limit(2):
            await generate(state)
            await generate(state)
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
        message_limit=5,  # 1 user, 1 assistant, 3 for each subagent
    )


if __name__ == "__main__":
    eval(hello_world(), model="mockllm/model")
