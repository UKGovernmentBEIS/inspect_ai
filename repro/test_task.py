from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match
from inspect_ai.solver import generate

@task
def dummy():
    dataset = [
        Sample(
            input="What is 1 + 1?",
            target="2"
        )
    ]

    return Task(
        dataset=dataset,
        solver=generate(),
        scorer=match()
    )
