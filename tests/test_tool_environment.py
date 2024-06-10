from test_helpers.tools import list_files, read_file
from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools


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
