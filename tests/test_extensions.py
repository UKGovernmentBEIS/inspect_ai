# type: ignore

import subprocess
import sys

import pytest
from test_helpers.tools import list_files
from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval_async
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools


@pytest.mark.asyncio
async def test_extension_model():
    # ensure the package is installed
    ensure_package_installed()

    # call the model
    mdl = get_model("custom/gpt7")
    result = await mdl.generate({"role": "user", "content": "hello"}, [], "none", {})
    assert result.completion == "Hello from gpt7"


@skip_if_no_openai
@pytest.mark.asyncio
async def test_extension_toolenv():
    # ensure the package is installed
    ensure_package_installed()

    # run a task using the toolenv
    try:
        task = Task(
            dataset=[
                Sample(
                    input="Please use the list_files tool to list the files in the current directory"
                )
            ],
            plan=[use_tools(list_files()), generate()],
            scorer=includes(),
            tool_environment="podman",
        )
        await eval_async(task, model="openai/gpt-4")
    except Exception as ex:
        pytest.fail(f"Exception raised: {ex}")


def ensure_package_installed():
    try:
        import inspect_package  # noqa: F401
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--no-deps", "tests/test_package"]
        )
