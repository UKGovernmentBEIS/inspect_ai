from inspect_ai.tool import ContentText, ToolError, tool
from inspect_ai.util import sandbox


# define tool
@tool(
    prompt="""If you are given a math problem of any kind,
    please use the addition tool to compute the result."""
)
def addition():
    async def execute(x: int, y: int):
        """
        Tool for adding two numbers.

        Args:
            x (int): First number to add.
            y (int): Second number to add.

        Returns:
            The sum of the two numbers.
        """
        # return as list[Content] to confirm that codepath works
        return [ContentText(text=str(x + y))]

    return execute


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
            return await sandbox().read_file(file)
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
        result = await sandbox().exec(["ls", dir])
        if result.success:
            return result.stdout
        else:
            raise ToolError(result.stderr)

    return execute


@tool(prompt="Use the raise_error tool if asked to raise an error.")
def raise_error():
    async def execute():
        """Raise an error."""
        raise RuntimeError("Raising an error.")

    return execute
