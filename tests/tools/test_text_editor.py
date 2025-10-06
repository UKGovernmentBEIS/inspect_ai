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


# @pytest.mark.slow
def test_text_editor_relative_path():
    file_content = "here's the file contents"
    task = Task(
        dataset=[
            Sample(
                input="doesn't matter",
                files={"/tmp/test_relative.txt": file_content},
            )
        ],
        solver=[use_tools([text_editor()]), generate()],
        scorer=match(),
        sandbox="docker",
    )
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
    assert file_content in editor_response.text
