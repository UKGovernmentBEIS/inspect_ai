from dataset import read_dataset

from inspect_ai import Task, task
from inspect_ai.scorer import includes
from inspect_ai.solver import (
    Generate,
    TaskState,
    bash,
    generate,
    python,
    solver,
    system_message,
    tool_environment,
    use_tools,
)


@task
def intercode_ctf():
    return Task(
        dataset=read_dataset(),
        plan=[
            system_message("system.txt"),
            use_tools([bash(), python()]),
            sample_setup(),
            generate(),
        ],
        scorer=includes(),
        max_messages=30,
        tool_environment="docker",
    )


@solver
def sample_setup():
    async def solve(state: TaskState, generate: Generate):
        if state.metadata.get("setup") is not None:
            await tool_environment().exec(["bash", "-c", state.metadata["setup"]])
        return state

    return solve
