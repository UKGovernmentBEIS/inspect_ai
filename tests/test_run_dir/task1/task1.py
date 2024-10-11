from test_helpers.utils import file_check

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import generate


@task
def task1():
    return Task(
        dataset=[Sample(input="What is 1+1?", target="2")],
        solver=[file_check("task1.py"), generate()],
        scorer=includes(),
        metadata={"task_idx": 1},
    )
