from inspect_ai import Task, task
from inspect_ai.solver._human_agent import human_agent


@task
def human() -> Task:
    return Task(
        solver=human_agent(user="nonroot"),
        sandbox=("docker", "compose.yaml"),
    )
