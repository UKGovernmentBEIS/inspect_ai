from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import ToolError, tool
from inspect_ai.util import sandbox


@tool
def list_files():
    async def execute(dir: str):
        """List the files in a directory.

        Args:
            dir: Directory

        Returns:
            File listing of the directory
        """
        result = await sandbox().exec(["ls", dir])
        if result.success:
            return result.stdout
        else:
            raise ToolError(result.stderr)

    return execute


@task
def file_probe():
    return Task(
        dataset=[
            Sample(
                input='Is there a file named "foo.txt" in the current directory?',
                target="Yes",
                files={"foo.txt": "hello"},
            ),
        ],
        solver=[use_tools([list_files()]), generate()],
        scorer=includes(),
        sandbox="docker",
    )
