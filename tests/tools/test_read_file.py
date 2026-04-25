"""Tests for read_file tool."""

import pytest
from test_helpers.tasks import minimal_task_for_tool_use
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import skip_if_no_docker

from inspect_ai import eval
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.tool import read_file


def test_read_file_constructible() -> None:
    """Tool is constructible without a sandbox."""
    tool = read_file()
    assert tool is not None


@skip_if_no_docker
@pytest.mark.slow
def test_read_file_basic() -> None:
    task = minimal_task_for_tool_use(read_file())
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="read_file",
                    tool_arguments={"file_path": "/etc/hostname"},
                ),
            ],
        ),
    )[0]
    assert result.samples
    messages = result.samples[0].messages
    tool_call = get_tool_call(messages, "read_file")
    assert tool_call is not None
    response = get_tool_response(messages, tool_call)
    assert response is not None
    assert response.content  # should have some content
