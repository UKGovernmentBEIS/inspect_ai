from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import code_execution


@task
def code_execution_task():
    return Task(
        dataset=[
            Sample(
                "Please use your available tools to execute Python code that adds 435678 + 23457 and then prints the result."
            )
        ],
        solver=[use_tools(code_execution()), generate()],
        sandbox="docker",
    )
