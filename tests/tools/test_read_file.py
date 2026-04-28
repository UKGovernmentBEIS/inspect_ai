"""Tests for read_file tool."""

import pytest
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import read_file


def test_read_file_constructible() -> None:
    """Tool is constructible without a sandbox."""
    tool = read_file()
    assert tool is not None


def _read_file_task(files: dict | None = None) -> Task:
    sample = Sample(
        input="Please use the tool",
        target="n/a",
        files=files or {"/tmp/test.txt": "line1\nline2\nline3\nline4\nline5"},
    )
    return Task(
        dataset=[sample],
        solver=[use_tools(read_file()), generate()],
        scorer=includes(),
        message_limit=3,
        sandbox="docker",
    )


def _run_read_file(tool_arguments: dict, files: dict | None = None) -> str:
    task = _read_file_task(files)
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="read_file",
                    tool_arguments=tool_arguments,
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
    return str(response.content)


@skip_if_no_docker
@pytest.mark.slow
def test_read_file_basic() -> None:
    content = _run_read_file({"file_path": "/tmp/test.txt"})
    assert "line1" in content
    assert "line5" in content


@skip_if_no_docker
@pytest.mark.slow
def test_read_file_with_offset() -> None:
    content = _run_read_file({"file_path": "/tmp/test.txt", "offset": 2})
    assert "line1" not in content
    assert "line2" not in content
    assert "line3" in content
    assert "line5" in content


@skip_if_no_docker
@pytest.mark.slow
def test_read_file_with_limit() -> None:
    content = _run_read_file({"file_path": "/tmp/test.txt", "limit": 2})
    assert "line1" in content
    assert "line2" in content
    assert "line3" not in content


@skip_if_no_docker
@pytest.mark.slow
def test_read_file_with_offset_and_limit() -> None:
    content = _run_read_file({"file_path": "/tmp/test.txt", "offset": 1, "limit": 2})
    assert "line1" not in content
    assert "line2" in content
    assert "line3" in content
    assert "line4" not in content


@skip_if_no_docker
@pytest.mark.slow
def test_read_file_not_found() -> None:
    task = _read_file_task()
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="read_file",
                    tool_arguments={"file_path": "/tmp/nonexistent.txt"},
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
    assert response.error is not None
    assert "not found" in response.error.message.lower()
