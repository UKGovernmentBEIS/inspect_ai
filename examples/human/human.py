from inspect_ai import Task, task
from inspect_ai.agent._human.agent import human_cli


@task
def human() -> Task:
    return Task(
        solver=human_cli(),
        sandbox=("docker", "compose.yaml"),
    )
