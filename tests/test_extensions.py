import pytest
from test_helpers.tools import list_files
from test_helpers.utils import ensure_test_package_installed

from inspect_ai import Task, eval_async
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools


@pytest.mark.asyncio
async def test_extension_model():
    # ensure the package is installed
    ensure_test_package_installed()

    # call the model
    mdl = get_model("custom/gpt7")
    result = await mdl.generate([{"role": "user", "content": "hello"}], [], "none", {})
    assert result.completion == "Hello from gpt7"


@pytest.mark.asyncio
async def test_extension_sandboxenv():
    # ensure the package is installed
    ensure_test_package_installed()

    # run a task using the sandboxenv
    try:
        task = Task(
            dataset=[
                Sample(
                    input="Please use the list_files tool to list the files in the current directory"
                )
            ],
            solver=[use_tools(list_files()), generate()],
            scorer=includes(),
            sandbox="podman",
        )
        await eval_async(task, model="mockllm/model")
    except Exception as ex:
        pytest.fail(f"Exception raised: {ex}")
