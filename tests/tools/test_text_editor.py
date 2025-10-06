from pathlib import Path

import pytest
from test_helpers.tool_call_utils import (
    get_tool_call,
    get_tool_response,
)

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import text_editor


@pytest.fixture(scope="session")
def inspect_tool_support_sandbox(local_inspect_tools) -> tuple[str, str]:
    """
    Return tuple of (docker, path to sandbox config) based on args.

    Return a path to a docker project configuration for a container
    with the inspect tools package installed. If pytest is run with
    --local-inspect-tools, build from source, otherwise pull from
    dockerhub.
    """
    base = Path(__file__).parent
    if local_inspect_tools:
        cfg = "test_inspect_tool_support.from_source.yaml"
    else:
        cfg = "test_inspect_tool_support.yaml"
    return "docker", (base / cfg).as_posix()


# @pytest.mark.slow
def test_text_editor_relative_path(inspect_tool_support_sandbox):
    task = Task(
        dataset=[Sample(input="Create and read a file using relative path")],
        solver=[use_tools([text_editor()]), generate()],
        scorer=match(),
        sandbox=inspect_tool_support_sandbox,
    )
    test_content = "test_relative_path_content"
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="text_editor",
                tool_arguments={"command": "view", "path": "../tmp/test_relative.txt"},
            ),
            ModelOutput.from_content(model="mockllm/model", content="All done."),
        ],
    )
    log = eval(task, model=model)[0]

    assert log.status == "success"
    assert log.samples
    messages = log.samples[0].messages

    editor_tool_call = get_tool_call(messages, "text_editor")
    assert editor_tool_call
    editor_response = get_tool_response(messages, editor_tool_call)
    assert editor_response
    assert editor_response.error is None, (
        f"Tool call should not return error for relative path: {editor_response.error}"
    )
    assert "not an absolute path" not in editor_response.content, (
        f"Tool should accept relative paths, but got error message: {editor_response.content}"
    )
    assert test_content in editor_response.content, (
        f"Expected content '{test_content}' in response: {editor_response.content}"
    )
