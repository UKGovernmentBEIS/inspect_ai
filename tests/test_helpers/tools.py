from inspect_ai.model import ContentText
from inspect_ai.solver import ToolError, tool, tool_environment


# define tool
@tool(
    prompt="""If you are given a math problem of any kind,
    please use the addition tool to compute the result.""",
    params={"color": "metadata.color"},
)
def addition():
    async def add(color: str, x: int, y: int):
        """
        Tool for adding two numbers.

        Args:
            color (str): Color
            x (int): First number to add.
            y (int): Second number to add.

        Returns:
            The sum of the two numbers.
        """
        # return as list[Content] to confirm that codepath works
        return [ContentText(text=str(x + y))]

    return add


@tool(prompt="If you need to read a file, use the read_file tool.")
def read_file():
    async def execute(file: str):
        """
        Read a file from the filesystem.

        Args:
          file (str): File to read.

        Returns:
          File contents
        """
        try:
            return await tool_environment().read_file(file)
        except FileNotFoundError:
            raise ToolError(f"File {file} not found.")

    return execute


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


@tool(prompt="Use the exec tool to run programs")
def exec():
    async def execute(program: str):
        """Run a program

        Args:
            program (str): Program to run

        Returns:
            Program output
        """
        result = await tool_environment().exec([program])
        if result.success:
            return result.stdout
        else:
            raise ToolError(result.stderr)

    return execute
