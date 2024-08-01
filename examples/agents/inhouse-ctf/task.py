from dataset import create_system_message_file, get_task_details

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import (
    bash,
    generate,
    python,
    system_message,
    use_tools,
)

# maximum chat messages before giving up
MAX_MESSAGES = 30

# maximum seconds to run bash/python cmds
CMD_TIMEOUT = 180

# task details
TASK_DETAILS_PATH = "challenges/tasks_details.json"

# system template path
SYSTEM_TEMP_PATH = "challenges/system_template.txt"

# scratch directory
SCRATCH_PATH = "scratch"


@task
def inhouse_ctf(task_name="idor"):
    info_file_path = f"{SCRATCH_PATH}/{task_name}_container_info.json"
    command, prompt, flag, address = get_task_details(
        task_name, TASK_DETAILS_PATH, info_file_path
    )
    print(command, prompt, flag, address)
    system_message_path = f"{SCRATCH_PATH}/system_{task_name}.txt"
    create_system_message_file(command, address, SYSTEM_TEMP_PATH, system_message_path)
    return Task(
        dataset=[
            Sample(
                input=prompt,
                target=flag,
            )
        ],
        plan=[
            system_message(system_message_path),
            use_tools([bash(timeout=CMD_TIMEOUT), python(timeout=CMD_TIMEOUT)]),
            generate(),
        ],
        scorer=includes(),
        max_messages=MAX_MESSAGES,
        tool_environment="docker",
    )
