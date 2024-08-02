from inspect_ai.tool import ContentText, ToolError, tool
from inspect_ai.util import sandbox


# define tool
@tool
def addition():
    async def execute(x: int, y: int):
        """
        Add two numbers.

        Args:
            x (int): First number to add.
            y (int): Second number to add.

        Returns:
            The sum of the two numbers.
        """
        # return as list[Content] to confirm that codepath works
        return [ContentText(text=str(x + y))]

    return execute


@tool
def read_file():
    async def execute(file: str):
        """
        Read the contents of a file.

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


@tool
def raise_error():
    async def execute():
        """Raise an error."""
        raise RuntimeError("Raising an error.")

    return execute
