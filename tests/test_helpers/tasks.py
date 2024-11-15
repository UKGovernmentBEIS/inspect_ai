from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import generate


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
