from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import exact
from inspect_ai.solver import generate

# This is the simplest possible Inspect eval, useful for testing your configuration / network / platform etc.


@task
def hello_world():
    return Task(
        dataset=[
            Sample(
                input="Just reply with Hello World",
                target="Hello World",
            )
        ],
        solver=[
            generate(),
        ],
        scorer=exact(),
    )
