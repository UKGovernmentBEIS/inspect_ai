from shortuuid import uuid

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import basic_agent
from inspect_ai.tool import bash


@task
def hello_world_simple_react_agent() -> Task:
    return Task(
        dataset=[Sample(input="Say hello world", target="hello world")],
        solver=basic_agent(tools=[bash()], message_limit=5),
        scorer=includes(),
        sandbox="docker",
    )


if __name__ == "__main__":
    eval(
        tasks=[
            hello_world_simple_react_agent(),
            hello_world_simple_react_agent(),
        ],
        max_tasks=2,
        model="openai/gpt-4o",
    )
