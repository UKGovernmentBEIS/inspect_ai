from dataset import read_dataset

from inspect_ai import Task, task
from inspect_ai.scorer import includes
from inspect_ai.solver import (
    generate,
    system_message,
    use_tools,
)
from inspect_ai.tool import bash, python

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
            generate(),
        ],
        scorer=includes(),
        max_messages=MAX_MESSAGES,
        sandbox="docker",
    )
