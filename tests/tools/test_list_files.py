"""Tests for list_files tool."""

import pytest
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageTool, ModelOutput, get_model
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


def _run_list_files_local(calls: list[dict], files: dict[str, str]) -> list[str]:
    task = Task(
        dataset=[Sample(input="Please use the tool", target="n/a", files=files)],
        solver=[use_tools(list_files()), generate()],
        scorer=includes(),
        message_limit=1 + 2 * len(calls),
        sandbox="local",
    )
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="list_files",
                    tool_arguments=args,
                )
                for args in calls
            ],
        ),
    )[0]
    assert result.status == "success"
    assert result.samples
    responses = [
        m for m in result.samples[0].messages if isinstance(m, ChatMessageTool)
    ]
    assert len(responses) == len(calls)
    return [m.error.message if m.error else m.text for m in responses]


@pytest.mark.parametrize("path", ["-delete", "-print", "!", "("])
def test_list_files_expression_path_not_evaluated(path: str) -> None:
    """A path that looks like a find expression is treated as a path."""
    files = {"keep.txt": "x", "sub/keep2.txt": "y"}
    first, second = _run_list_files_local([{"path": path}, {"path": "."}], files)
    assert "No such file or directory" in first
    assert "keep.txt" not in first
    # the working directory is untouched
    assert "keep.txt" in second
    assert "keep2.txt" in second


def test_list_files_dash_directory() -> None:
    """A directory whose name starts with - can be listed."""
    (content,) = _run_list_files_local(
        [{"path": "-dir"}], {"-dir/inside.txt": "x", "outside.txt": "y"}
    )
    assert "inside.txt" in content
    assert "outside.txt" not in content
