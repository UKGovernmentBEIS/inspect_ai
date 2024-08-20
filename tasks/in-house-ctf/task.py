from inspect_ai import Task, task
from inspect_ai.scorer import includes
from inspect_ai.solver import (
    generate,
    system_message,
    use_tools,
)
from inspect_ai.tool import bash

from dataset import get_task_sample, DATA_DIR
from template import SYSTEM_MESSAGE

# maximum chat messages before giving up
MAX_MESSAGES = 30

# maximum seconds to run bash/python cmds
CMD_TIMEOUT = 180


def in_house_ctf_task_template(task_name: str) -> Task:
    challenge_sample = get_task_sample(task_name)
    challenge_system_message = SYSTEM_MESSAGE.substitute(
        objective_prompt=challenge_sample.input,
        challenge_addresses=challenge_sample.metadata["challenge_address"],
    )
    return Task(
        dataset=[challenge_sample],
        plan=[
            system_message(challenge_system_message),
            use_tools([bash(timeout=CMD_TIMEOUT)]),
            generate(),
        ],
        scorer=includes(),
        max_messages=MAX_MESSAGES,
        sandbox=("docker", f"{DATA_DIR}/{task_name}/docker-compose.yaml"),
    )


# @task
# def cmd_injection():
#     return in_house_ctf_task_template("cmd_injection")

# @task
# def sqli():
#     return in_house_ctf_task_template("sqli")

# @task
# def db_3():
#     return in_house_ctf_task_template("db_3")

# @task
# def grafana():
#     return in_house_ctf_task_template("grafana")

# @task
# def idor():
#     return in_house_ctf_task_template("idor")

# @task
# def spray():
#     return in_house_ctf_task_template("spray")

# @task
# def ssh():
#     return in_house_ctf_task_template("ssh")
