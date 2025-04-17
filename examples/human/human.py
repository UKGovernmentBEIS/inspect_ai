from typing import Literal

from inspect_ai import Task, task
from inspect_ai.agent._human.agent import human_cli


@task
def human(user: Literal["root", "nonroot"] | None = None) -> Task:
    return Task(
        solver=human_cli(user=user),
        sandbox=("docker", "compose.yaml"),
    )
