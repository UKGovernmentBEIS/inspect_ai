"""Tests for grep tool."""

import pytest
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import grep

TEST_FILES = {
    "/tmp/testdir/hello.py": "def hello():\n    print('hello world')\n",
    "/tmp/testdir/goodbye.txt": "goodbye world\nfarewell\n",
    "/tmp/testdir/data.csv": "name,value\nalpha,1\nbeta,2\n",
}


def test_grep_constructible() -> None:
    """Tool is constructible without a sandbox."""
    tool = grep()
    assert tool is not None


def _run_grep(tool_arguments: dict) -> str:
    task = Task(
        dataset=[
            Sample(
                input="Please use the tool",
                target="n/a",
                files=TEST_FILES,
            )
        ],
        solver=[use_tools(grep()), generate()],
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
                    tool_name="grep",
                    tool_arguments=tool_arguments,
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
    return str(response.content)


@skip_if_no_docker
@pytest.mark.slow
def test_grep_basic() -> None:
    content = _run_grep({"pattern": "hello", "path": "/tmp/testdir"})
    assert "hello" in content


@skip_if_no_docker
@pytest.mark.slow
def test_grep_with_glob() -> None:
    content = _run_grep({"pattern": "world", "path": "/tmp/testdir", "glob": "*.py"})
    assert "hello.py" in content
    assert "goodbye.txt" not in content


@skip_if_no_docker
@pytest.mark.slow
def test_grep_fixed_strings() -> None:
    content = _run_grep(
        {
            "pattern": "print('hello world')",
            "path": "/tmp/testdir",
            "fixed_strings": True,
        }
    )
    assert "hello.py" in content


@skip_if_no_docker
@pytest.mark.slow
def test_grep_no_matches() -> None:
    content = _run_grep({"pattern": "zzz_nonexistent_zzz", "path": "/tmp/testdir"})
    assert "no matches" in content.lower()


@skip_if_no_docker
@pytest.mark.slow
def test_grep_files_with_matches_mode() -> None:
    content = _run_grep(
        {
            "pattern": "world",
            "path": "/tmp/testdir",
            "output_mode": "files_with_matches",
        }
    )
    assert "hello.py" in content
    assert "goodbye.txt" in content
    # Should only show file paths, not line content
    assert "print" not in content


@skip_if_no_docker
@pytest.mark.slow
def test_grep_count_mode() -> None:
    content = _run_grep(
        {"pattern": "world", "path": "/tmp/testdir", "output_mode": "count"}
    )
    # Should show counts, not full lines
    assert ":" in content
