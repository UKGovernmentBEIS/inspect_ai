from pathlib import Path

from rich import print

from inspect_ai import Task, eval, task
from inspect_ai.agent import aide_agent
from inspect_ai.dataset import Sample
from inspect_ai.scorer import exact


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
            aide_agent(
                data_dir=Path(
                    "/home/ubuntu/workspace/aideml-inspect/aide_inspect/assets/test"
                )
            ),
        ],
        scorer=exact(),
        sandbox="docker",
    )


if __name__ == "__main__":
    log = eval(hello_world(), model="anthropic/claude-3-7-sonnet-20250219")
    print(".")
