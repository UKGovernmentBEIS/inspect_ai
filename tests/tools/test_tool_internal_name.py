from typing import Any

from test_helpers.utils import skip_if_no_anthropic, skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import bash_session


@skip_if_no_docker
@skip_if_no_anthropic
def test_anthropic_internal_tool_name():
    log = eval(
        Task(
            dataset=[
                Sample(
                    input="Please use the bash tool to list the contents of the current directory. What are its contents?"
                )
            ],
            solver=[use_tools(bash_session()), generate()],
            sandbox="docker",
        ),
        model="anthropic/claude-3-7-sonnet-latest",
    )[0]
    assert log.status == "success"
    assert log.samples

    # tool call was mapped to bash_session and internal_name "bash was tracked"
    def check_tool_call(tool_call: Any) -> None:
        assert tool_call.function == "bash_session"
        assert tool_call.internal == "bash"

    # check tool call in assistant message
    assistant_message = log.samples[0].messages[1]
    assert assistant_message.tool_calls
    check_tool_call(assistant_message.tool_calls[0])

    # check that we use the internal name for the raw interaction w/ the model
    model_event = next(
        (event for event in log.samples[0].events if event.event == "model")
    )
    model_bash_tool = model_event.call.request["tools"][0]
    assert model_bash_tool["type"] == "bash_20250124"
    assert model_bash_tool["name"] == "bash"
    model_tool_call = model_event.call.response["content"][1]
    assert model_tool_call["name"] == "bash"

    # check that our tool event maps back to bash_session
    tool_event = next(
        (event for event in log.samples[0].events if event.event == "tool")
    )
    assert tool_event.function == "bash_session"
    assert tool_event.internal == "bash"

    # check tool call in tool message
    tool_message = log.samples[0].messages[2]
    check_tool_call(tool_message)
