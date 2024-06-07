from dataset import read_dataset, sample_setup

from inspect_ai import Task, task
from inspect_ai.scorer import includes
from inspect_ai.solver import (
    bash, generate, python, system_message, use_tools
)

# maximum chat messages before giving up
MAX_MESSAGES = 30

# maximum seconds to run bash/python cmds
CMD_TIMEOUT = 180


@task
def intercode_ctf():
    return Task(
        dataset=read_dataset(),
        plan=[
            system_message("system.txt"),
            use_tools([
                bash(timeout=CMD_TIMEOUT), 
                python(timeout=CMD_TIMEOUT)
            ]),
            sample_setup(),
            generate(),
        ],
        scorer=includes(),
        max_messages=MAX_MESSAGES,
        tool_environment="docker",
    )

