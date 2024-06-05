from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, tool, tool_environment, use_tools


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
        return await tool_environment().read_file(file)

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
            return f"Error: {result.stderr}"

    return execute


@skip_if_no_openai
def test_tool_environment_files():
    dataset = [
        Sample(
            input="What are the contents of file foo.txt?",
            target="Hello",
            files={"foo.txt": "Hello"},
        ),
        Sample(
            input='Is there a file named "bar.txt" in the current directory?',
            target="Yes",
            files={"bar.txt": "World"},
        ),
    ]
    task = Task(
        dataset=dataset,
        plan=[use_tools([read_file(), list_files()]), generate()],
        scorer=includes(),
    )
    result = eval(task, model="openai/gpt-4-turbo")[0]
    assert result.status == "success"
