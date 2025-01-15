import pytest
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import skip_if_no_docker, skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import tool


@tool
def complete_task():
    async def complete_task():
        """This is a test. Please call this tool to complete the task."""
        # Return a very long output to trigger truncation.
        return "TEST\n" * 100_000

    return complete_task


@skip_if_no_docker
@skip_if_no_openai
@pytest.mark.slow
def test_tool_truncate():
    task = Task(
        dataset=[
            Sample(
                input="This is a test. To complete the task, simply call the complete_task tool."
            )
        ],
        solver=[use_tools(complete_task()), generate()],
    )

    log = eval(task, model="openai/gpt-4o")[0]
    response = get_tool_response(
        log.samples[0].messages,
        get_tool_call(log.samples[0].messages, "complete_task"),
    )

    # Output should not contain leading/trailing whitespace on any line.
    assert all(line.strip() == line for line in response.content.split("\n"))
