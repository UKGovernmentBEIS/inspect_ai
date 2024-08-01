from dataset import create_system_task_file, get_task_details

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
TASK_DETAILS_PATH = "tasks_details.json"

# system template path
SYSTEM_TEMP_PATH = "system_template.txt"


@task
def inhouse_ctf(task_name="idor"):
    task_details = get_task_details(task_name, TASK_DETAILS_PATH)
    system_message_path = f"scratch/system_{task_details["challenge"]}.txt"
    create_system_task_file(task_details, SYSTEM_TEMP_PATH, system_message_path)
    return Task(
        dataset=[
            Sample(
                input=task_details["prompt"],
                target=["flag"],
            )
        ],
        plan=[
            system_message(system_message_path),
            use_tools([bash(timeout=CMD_TIMEOUT), python(timeout=CMD_TIMEOUT)]),
            generate(),
        ],
        scorer=includes(),
        max_messages=MAX_MESSAGES,
        # sandbox=("docker", "docker-compose.yaml"),
        tool_environment="docker",
    )
