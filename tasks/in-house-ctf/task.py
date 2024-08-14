from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import (
    Generate,
    TaskState,
    generate,
    solver,
    system_message,
    use_tools,
)
from inspect_ai.util import sandbox
from inspect_ai.tool import bash

from dataset import read_dataset
from template import SYSTEM_MESSAGE

# maximum chat messages before giving up
MAX_MESSAGES = 30

# maximum seconds to run bash/python cmds
CMD_TIMEOUT = 180


@task
def in_house_ctf(shuffle=False):
    challenge_dataset = read_dataset(shuffle)
    challenge_system_message = SYSTEM_MESSAGE.substitute(
        objective_prompt=challenge_dataset[0].input,
        challenge_addresses=challenge_dataset[0].target,
    )
    return Task(
        dataset=challenge_dataset,
        plan=[
            system_message(challenge_system_message),
            use_tools([bash(timeout=CMD_TIMEOUT)]),
            generate(),
        ],
        scorer=includes(),
        max_messages=MAX_MESSAGES,
        sandbox=("docker", "docker-compose.yaml"),
    )


@solver
def sample_init():
    async def solve(state: TaskState, generate: Generate):
        # run setup code if provided
        if state.metadata.get("setup") is not None:
            await sandbox().exec(["bash", "-c", state.metadata["setup"]])

        # add available files (if any) to prompt
        files = state.files
        if len(files) > 0:
            state.user_prompt.text = (
                "The following files are located in the working directory: "
                + f"{' '.join(files)}\n\n"
                + f"{state.user_prompt.text}"
            )

        # return state
        return state

    return solve
