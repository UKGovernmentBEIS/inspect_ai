# type: ignore

import subprocess
import sys

import pytest

from inspect_ai.model import get_model


@pytest.mark.asyncio
async def test_model_package():
    # ensure the package is installed
    try:
        import inspect_package  # noqa: F401
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "tests/test_package"]
        )

    # call the model
    mdl = get_model("custom/gpt7")
    result = await mdl.generate({"role": "user", "content": "hello"}, [], "none", {})
    assert result.completion == "Hello from gpt7"
