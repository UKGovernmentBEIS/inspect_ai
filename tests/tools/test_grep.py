"""Tests for grep tool."""

import pytest
from test_helpers.tasks import minimal_task_for_tool_use
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import skip_if_no_docker

from inspect_ai import eval
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.tool import grep


def test_grep_constructible() -> None:
    """Tool is constructible without a sandbox."""
    tool = grep()
    assert tool is not None


@skip_if_no_docker
@pytest.mark.slow
def test_grep_basic() -> None:
    task = minimal_task_for_tool_use(grep())
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="grep",
                    tool_arguments={
                        "pattern": "root",
                        "path": "/etc/passwd",
                    },
                ),
            ],
        ),
    )[0]
    assert result.samples
    messages = result.samples[0].messages
    tool_call = get_tool_call(messages, "grep")
    assert tool_call is not None
    response = get_tool_response(messages, tool_call)
    assert response is not None
    assert "root" in str(response.content)
