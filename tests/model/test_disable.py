import pytest

from inspect_ai import Task, eval
from inspect_ai._util.environ import environ_var


def test_disable_model_api():
    with environ_var("INSPECT_DISABLE_MODEL_API", "1"):
        with pytest.raises(RuntimeError) as excinfo:
            eval(Task(), model="openai/gpt-4o")
        assert "INSPECT_DISABLE_MODEL_API" in str(excinfo.value)


def test_disable_model_api_mockllm():
    with environ_var("INSPECT_DISABLE_MODEL_API", "1"):
        eval(Task(), model="mockllm/model")
