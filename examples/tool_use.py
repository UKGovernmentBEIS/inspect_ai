from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes, match
from inspect_ai.solver import (
    ToolError,
    generate,
    system_message,
    tool,
    tool_environment,
    use_tools,
)


@tool(
    prompt="""
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
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0"])],
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
        result = await tool_environment().exec(["ls", dir])
        if result.success:
            return result.stdout
        else:
            raise ToolError(result.stderr)

    return execute


SYSTEM_MESSAGE = """
Please answer exactly Yes or No with no additional words.
"""


@task
def bash():
    dataset = [
        Sample(
            input=(
                "Please list the files in the /usr/bin directory. "
                + "Is there a file named 'python3' in the directory?"
            ),
            target=["Yes"],
        )
    ]

    return Task(
        dataset=dataset,
        plan=[
            system_message(SYSTEM_MESSAGE),
            use_tools(list_files()),
            generate(),
        ],
        tool_environment="local",
        scorer=includes(),
    )


@tool(prompt="If you need to read a file, use the read_file tool.")
def read_file():
    async def execute(file: str):
        """Read a file

        Args:
            file (str): File to read

        Returns:
            File contents
        """
        try:
            return await tool_environment().read_file(file)
        except FileNotFoundError:
            raise ToolError(f"File {file} not found.")

    return execute


@task
def read():
    return Task(
        dataset=[Sample(input="Please read the file 'foo.txt'")],
        plan=[use_tools([read_file()]), generate()],
        scorer=match(),
        tool_environment="local",
    )
