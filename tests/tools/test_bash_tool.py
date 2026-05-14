import pytest
from test_helpers.tasks import minimal_task_for_tool_use
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import bash


@skip_if_no_docker
@pytest.mark.slow
def test_bash_simple_echo() -> None:
    task = minimal_task_for_tool_use(bash())
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name=bash.__name__,
                    tool_arguments={"command": "echo 'testing bash tool'"},
                ),
            ],
        ),
    )[0]
    assert result.samples
    messages = result.samples[0].messages
    tool_call = get_tool_call(messages, bash.__name__)
    assert tool_call is not None
    tool_call_response = get_tool_response(messages, tool_call)
    assert tool_call_response is not None
    assert tool_call_response.content == "testing bash tool\n"


@skip_if_no_docker
@pytest.mark.slow
def test_bash_profile() -> None:
    tool_task = Task(
        dataset=[
            Sample(
                input="Please use the tool",
                target="n/a",
                files={
                    "/etc/profile.d/test_bash_profile.sh": "export ENV_VAR=custom_value\n"
                },
            )
        ],
        solver=[use_tools(bash()), generate()],
        scorer=includes(),
        metadata={"task_idx": 1},
        message_limit=3,
        sandbox="docker",
    )
    result = eval(
        tool_task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name=bash.__name__,
                    tool_arguments={"command": "echo $ENV_VAR"},
                ),
            ],
        ),
        sandbox_cleanup=False,
    )[0]
    assert result.samples
    messages = result.samples[0].messages
    tool_call = get_tool_call(messages, bash.__name__)
    assert tool_call is not None
    tool_call_response = get_tool_response(messages, tool_call)
    assert tool_call_response is not None
    assert tool_call_response.content == "custom_value\n"


@skip_if_no_docker
@pytest.mark.slow
def test_bash_null_byte() -> None:
    """A null byte in a bash command surfaces as a tool error, not a sample crash."""
    task = minimal_task_for_tool_use(bash())
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name=bash.__name__,
                    tool_arguments={"command": "echo -n '\x00' > /tmp/poc"},
                ),
            ],
        ),
    )[0]
    assert result.samples
    sample = result.samples[0]
    assert sample.error is None
    tool_call = get_tool_call(sample.messages, bash.__name__)
    assert tool_call is not None
    tool_response = get_tool_response(sample.messages, tool_call)
    assert tool_response is not None
    assert tool_response.error is not None
    assert tool_response.error.type == "parsing"
    assert "embedded null byte" in tool_response.error.message


@skip_if_no_docker
@pytest.mark.slow
def test_bash_chmodless_script() -> None:
    """Running a non-executable script surfaces as a tool response with stderr, not a sample crash."""
    task = minimal_task_for_tool_use(bash())
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name=bash.__name__,
                    tool_arguments={
                        "command": "echo 'true' > /tmp/myscript && /tmp/myscript"
                    },
                ),
            ],
        ),
    )[0]
    assert result.samples
    sample = result.samples[0]
    assert sample.error is None, f"unexpected sample error: {sample.error}"
    tool_call = get_tool_call(sample.messages, bash.__name__)
    assert tool_call is not None
    tool_response = get_tool_response(sample.messages, tool_call)
    assert tool_response is not None
    assert "Permission denied" in str(tool_response.content)


@skip_if_no_docker
@pytest.mark.slow
def test_bash_invalid_utf8() -> None:
    """Non-UTF-8 command output does not crash the sample."""
    task = minimal_task_for_tool_use(bash())
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name=bash.__name__,
                    tool_arguments={"command": "printf '\\xff'"},
                ),
            ],
        ),
    )[0]
    assert result.samples
    sample = result.samples[0]
    assert sample.error is None
    tool_call = get_tool_call(sample.messages, bash.__name__)
    assert tool_call is not None
    tool_response = get_tool_response(sample.messages, tool_call)
    assert tool_response is not None
    # The sandbox interface allows `exec` to raise UnicodeDecodeError (which
    # the tool call framework converts to a friendly result), but built-in
    # sandboxes use lossy decoding instead of raising. Either is acceptable.
    assert (
        tool_response.error is not None and tool_response.error.type == "unicode_decode"
    ) or tool_response.content is not None
