from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes, match
from inspect_ai.solver import (
    generate,
    system_message,
    use_tools,
)
from inspect_ai.tool import ToolError, tool
from inspect_ai.util import sandbox


@tool
def add():
    async def execute(x: int, y: int):
        """
        Add two numbers.

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
        solver=[use_tools(add()), generate()],
        scorer=match(numeric=True),
    )


@tool
def list_files():
    async def execute(dir: str):
        """List the files in a directory.

        Args:
            dir (str): Directory

        Returns:
            File listing of the directory
        """
        result = await sandbox().exec(["ls", dir])
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
        solver=[
            system_message(SYSTEM_MESSAGE),
            use_tools(list_files()),
            generate(),
        ],
        sandbox="local",
        scorer=includes(),
    )


@tool
def read_file():
    async def execute(file: str):
        """Read the contents of a file.

        Args:
            file (str): File to read

        Returns:
            File contents
        """
        return await sandbox().read_file(file)

    return execute


@task
def read():
    return Task(
        dataset=[Sample(input="Please read the file 'foo.txt'")],
        solver=[use_tools([read_file()]), generate()],
        scorer=match(),
        sandbox="local",
    )


@tool
def write_file():
    async def execute(file: str, contents: str):
        """Write content to a file.

        Args:
            file (str): File to write
            contents (str): Contents of file
        """
        return await sandbox().write_file(file, contents)

    return execute


@task
def write():
    return Task(
        dataset=[Sample(input="Please write 'bar' to a file named 'foo.txt'.")],
        solver=[
            use_tools([write_file()]),
            generate(),
        ],
        scorer=match(),
        sandbox="local",
    )


@task
def parallel_add():
    return Task(
        dataset=[
            Sample(
                input="Please add the numbers 1+1 and 2+2, and then print the results of those computations side by side as just two numbers (with no additional text). You should use the add tool to do this, and you should make the two required calls to add in parallel so the results are computed faster.",
                target=["2 4"],
            )
        ],
        solver=[use_tools([add()]), generate()],
        scorer=includes(),
    )
