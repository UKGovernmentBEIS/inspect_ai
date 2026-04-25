"""Tests for list_files tool."""

import pytest
from test_helpers.tasks import minimal_task_for_tool_use
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import skip_if_no_docker

from inspect_ai import eval
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.tool import list_files


def test_list_files_constructible() -> None:
    """Tool is constructible without a sandbox."""
    tool = list_files()
    assert tool is not None


@skip_if_no_docker
@pytest.mark.slow
def test_list_files_basic() -> None:
    task = minimal_task_for_tool_use(list_files())
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="list_files",
                    tool_arguments={"path": "/etc", "depth": 1},
                ),
            ],
        ),
    )[0]
    assert result.samples
    messages = result.samples[0].messages
    tool_call = get_tool_call(messages, "list_files")
    assert tool_call is not None
    response = get_tool_response(messages, tool_call)
    assert response is not None
    assert response.content  # should list files
