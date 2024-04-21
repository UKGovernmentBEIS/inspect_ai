from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes, match
from inspect_ai.solver import generate, system_message, tool, use_tools
from inspect_ai.util import subprocess


@tool(prompt="""
    If you are given a math problem of any kind,
    please use the add tool to compute the result.
    """
)
def add():
    async def execute(x: int, y: int):
        """
        Tool for adding two numbers.

        Args:
            x (int): First number to add.
            y (int): Second number to add.

        Returns:
            The sum of the two numbers.
        """
        return x + y

    return execute

@task
def addition_problem():
    return Task(
        dataset=[Sample(
            input="What is 1 + 1?",
            target=["2", "2.0"]
        )],
        plan=[use_tools(add()), generate()],
        scorer=match(numeric=True),
    )

@tool(
    prompt="""
    If you are asked to list the files in a directory you
    should call the list_files function to list the files.
    """
)
def list_files():
    async def execute(dir: str):
        """List the files in a directory.

        Args:
            dir (str): Directory

        Returns:
            File listing of the directory
        """
        result = await subprocess(["ls", dir])
        if result.success:
            return result.stdout
        else:
            return f"Error: {result.stderr}"

    return execute

SYSTEM_MESSAGE = """
Please answer exactly Yes or No with no additional words.
"""

@task
def bash():

    dataset = [Sample(
        input=(
            "Please list the files in the /usr/bin directory. "
            + "Is there a file named 'python3' in the directory?"
        ),
        target=["Yes"],
    )]

    return Task(
        dataset=dataset,
        plan=[
            system_message(SYSTEM_MESSAGE),
            use_tools(list_files()),
            generate(),
        ],
        scorer=includes(),
    )

