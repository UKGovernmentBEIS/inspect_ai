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
def command_exec():
    async def execute(command: str) -> str:
        """Executes the given bash script in the agent execution environment, in the working directory.

        Args:
            command (str): A single string of the bash script to run in the container.

        Returns:
            out (str): output of the script (success/failure, return code, stdout, stderr).
        """
        result = await sandbox().exec(cmd=["bash", "-c", command], timeout=90)
        return str(result)

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
        return await sandbox().read_file(file)

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
