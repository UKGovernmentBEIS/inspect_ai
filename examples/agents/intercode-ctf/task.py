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

# maximum chat messages before giving up
MAX_MESSAGES = 30

# maximum seconds to run bash/python cmds
CMD_TIMEOUT = 180


@task
def intercode_ctf(shuffle=False):
    return Task(
        dataset=read_dataset(shuffle),
        plan=[
            system_message("system.txt"),
            use_tools([bash(timeout=CMD_TIMEOUT), python(timeout=CMD_TIMEOUT)]),
            sample_init(),
            generate(),
        ],
        scorer=includes(),
        max_messages=MAX_MESSAGES,
        tool_environment="docker",
    )


@solver
def sample_init():
    async def solve(state: TaskState, generate: Generate):
        # run setup code if provided
        if state.metadata.get("setup") is not None:
            await tool_environment().exec(["bash", "-c", state.metadata["setup"]])

        # add available files (if any) to prompt
        files = state.metadata["files"]
        if len(files) > 0:
            state.user_prompt.text = (
                "The following files are located in the working directory: "
                + f"{' '.join(files)}\n\n"
                + f"{state.user_prompt.text}"
            )

        # return state
        return state

    return solve
