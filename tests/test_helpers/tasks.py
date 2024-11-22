from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import Tool


@task
def empty_task() -> Task:
    return Task()


@task
def minimal_task() -> Task:
    return Task(
        dataset=[Sample(input="What is 1+1?", target="2")],
        solver=[generate()],
        scorer=includes(),
        metadata={"task_idx": 1},
    )


@task
def minimal_task_for_tool_use(tool: Tool) -> Task:
    return Task(
        dataset=[Sample(input="Please use the tool", target="n/a")],
        solver=[use_tools(tool), generate()],
        scorer=includes(),
        metadata={"task_idx": 1},
        message_limit=3,
        sandbox="docker",
    )
