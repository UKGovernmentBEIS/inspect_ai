"""Tests for list_files tool."""

import pytest
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import list_files

TEST_FILES = {
    "/tmp/testdir/a.txt": "a",
    "/tmp/testdir/b.txt": "b",
    "/tmp/testdir/sub/c.txt": "c",
}


def test_list_files_constructible() -> None:
    """Tool is constructible without a sandbox."""
    tool = list_files()
    assert tool is not None


def _run_list_files(tool_arguments: dict) -> str:
    task = Task(
        dataset=[
            Sample(
                input="Please use the tool",
                target="n/a",
                files=TEST_FILES,
            )
        ],
        solver=[use_tools(list_files()), generate()],
        scorer=includes(),
        message_limit=3,
        sandbox="docker",
    )
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="list_files",
                    tool_arguments=tool_arguments,
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
    return str(response.content)


@skip_if_no_docker
@pytest.mark.slow
def test_list_files_basic() -> None:
    content = _run_list_files({"path": "/tmp/testdir"})
    assert "a.txt" in content
    assert "b.txt" in content
    assert "c.txt" in content


@skip_if_no_docker
@pytest.mark.slow
def test_list_files_with_depth() -> None:
    content = _run_list_files({"path": "/tmp/testdir", "depth": 1})
    assert "a.txt" in content
    assert "b.txt" in content
    assert "sub" in content
    # c.txt is at depth 2, should not appear with depth=1
    assert "c.txt" not in content


@skip_if_no_docker
@pytest.mark.slow
def test_list_files_dash_path_safe() -> None:
    """Path starting with - must not be interpreted as a find predicate."""
    task = Task(
        dataset=[
            Sample(
                input="Please use the tool",
                target="n/a",
                files=TEST_FILES,
            )
        ],
        solver=[use_tools(list_files()), generate()],
        scorer=includes(),
        message_limit=3,
        sandbox="docker",
    )
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="list_files",
                    tool_arguments={"path": "-delete"},
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
    # Should get an error (path not found), not execute -delete
    assert response.error is not None
