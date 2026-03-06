from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import bash


@task
def bash_task():
    return Task(
        dataset=[
            Sample(
                input="Use the bash tool to print 'hello world'.",
                target="hello world",
            ),
        ],
        solver=[use_tools([bash()]), generate()],
        scorer=includes(),
        sandbox="docker",
    )
