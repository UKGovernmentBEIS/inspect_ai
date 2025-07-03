from pathlib import Path

import pytest
from test_helpers.tool_call_utils import (
    get_tool_call,
    get_tool_response,
)

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    get_model,
)
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer import match
from inspect_ai.solver import (
    generate,
    use_tools,
)
from inspect_ai.tool import ToolCallError, bash_session, text_editor


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


@pytest.mark.slow
def test_text_editor_read(inspect_tool_support_sandbox):
    task = Task(
        dataset=[Sample(input="Please read the file '/etc/passwd'")],
        solver=[use_tools([text_editor()]), generate()],
        scorer=match(),
        sandbox=inspect_tool_support_sandbox,
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="text_editor",
                tool_arguments={
                    "command": "view",
                    "path": "/etc/passwd",
                },
            ),
            ModelOutput.from_content(model="mockllm/model", content="All done."),
        ],
    )
    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.samples
    messages = log.samples[0].messages
    tool_call = get_tool_call(messages, "text_editor")
    assert tool_call
    response = get_tool_response(messages, tool_call)
    assert response
    assert response.error is None, f"Tool call returns error: {response.error}"
    assert "root:x:0:0:root" in response.content, (
        f"Unexpected output from file read: {response.content}"
    )


@pytest.mark.slow
def test_text_editor_read_missing(inspect_tool_support_sandbox):
    task = Task(
        dataset=[Sample(input="Please read the file '/missing.txt'")],
        solver=[use_tools([text_editor()]), generate()],
        scorer=match(),
        sandbox=inspect_tool_support_sandbox,
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="text_editor",
                tool_arguments={
                    "command": "view",
                    "path": "/missing.txt",
                },
            ),
            ModelOutput.from_content(model="mockllm/model", content="All done."),
        ],
    )
    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.samples
    messages = log.samples[0].messages
    tool_call = get_tool_call(messages, "text_editor")
    assert tool_call

    response = get_tool_response(messages, tool_call)
    assert response
    assert response.error  # Expect ToolError as file is missing
    assert isinstance(response.error, ToolCallError), (
        f"Expected ToolCallError, got {type(response.error)}"
    )


@pytest.mark.slow
def test_bash_session_root(inspect_tool_support_sandbox):
    task = Task(
        dataset=[
            Sample(
                input='What is the output of running the command echo "start $(whoami) end"?'
            )
        ],
        solver=[use_tools([bash_session()]), generate()],
        scorer=match(),
        sandbox=inspect_tool_support_sandbox,
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash_session",
                tool_arguments={
                    "action": "type_submit",
                    "input": 'echo "start $(whoami) end"',
                },
            ),
            ModelOutput.from_content(model="mockllm/model", content="All done."),
        ],
    )
    log = eval(task, model=model)[0]

    assert log.status == "success"
    assert log.samples
    messages = log.samples[0].messages
    tool_call = get_tool_call(messages, "bash_session")
    assert tool_call
    response = get_tool_response(messages, tool_call)
    assert response
    assert response.error is None, f"Tool call returns error: {response.error}"
    assert "start root end" in response.content, (
        f"Unexpected output from whoami: {response.content}"
    )


@pytest.mark.slow
def test_bash_session_non_root(inspect_tool_support_sandbox):
    task = Task(
        dataset=[
            Sample(
                input='What is the output of running the command echo "start $(whoami) end"?'
            )
        ],
        solver=[use_tools([bash_session(user="nobody")]), generate()],
        scorer=match(),
        sandbox=inspect_tool_support_sandbox,
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash_session",
                tool_arguments={
                    "action": "type_submit",
                    "input": 'echo "start $(whoami) end"',
                },
            ),
            ModelOutput.from_content(model="mockllm/model", content="All done."),
        ],
    )
    log = eval(task, model=model)[0]

    assert log.status == "success"
    assert log.samples
    messages = log.samples[0].messages
    tool_call = get_tool_call(messages, "bash_session")
    assert tool_call
    response = get_tool_response(messages, tool_call)
    assert response
    assert response.error is None, f"Tool call returns error: {response.error}"
    assert "start nobody end" in response.content, (
        f"Unexpected output from whoami: {response.content}"
    )


@pytest.mark.slow
def test_bash_session_missing_user(inspect_tool_support_sandbox):
    task = Task(
        dataset=[
            Sample(
                input='What is the output of running the command echo "start $(whoami) end"?'
            )
        ],
        solver=[use_tools([bash_session(user="foo")]), generate()],
        scorer=match(),
        sandbox=inspect_tool_support_sandbox,
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash_session",
                tool_arguments={
                    "action": "type_submit",
                    "input": 'echo "start $(whoami) end"',
                },
            ),
            ModelOutput.from_content(model="mockllm/model", content="All done."),
        ],
    )
    log = eval(task, model=model)[0]

    # This eval should entirely fail to run as the tool cannot be set up correctly.
    # I.e., it's not that the model has called the tool wrong, but the user made a mistake.
    # Note that the sandbox exec helper doesn't log anything about the user being
    # the cause of this error, so there's unfortunately nothing more precise for us to check
    assert log.status == "error"


@pytest.mark.slow
def test_text_editor_user(inspect_tool_support_sandbox):
    task = Task(
        dataset=[
            Sample(
                input="Create a file /flag only readable by root. Then read it with the text editor",
            )
        ],
        solver=[
            use_tools([bash_session(user="root"), text_editor(user="nobody")]),
            generate(),
        ],
        scorer=match(),
        sandbox=inspect_tool_support_sandbox,
    )
    flag = "this_is_it"
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash_session",
                tool_arguments={
                    "action": "type_submit",
                    "input": f"echo {flag} > /flag && chmod 400 /flag; ls -al /flag && cat /flag",
                },
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="text_editor",
                tool_arguments={"command": "view", "path": "/flag"},
            ),
            ModelOutput.from_content(model="mockllm/model", content="All done."),
        ],
    )
    log = eval(task, model=model)[0]

    assert log.status == "success"
    assert log.samples
    messages = log.samples[0].messages

    bash_tool_call = get_tool_call(messages, "bash_session")
    bash_response = get_tool_response(messages, bash_tool_call)
    editor_tool_call = get_tool_call(messages, "text_editor")
    editor_response = get_tool_response(messages, editor_tool_call)

    assert "-r--------" in bash_response.content  # Expect read only flag
    assert "root root" in bash_response.content  # Expect flag owned by root

    assert editor_response
    assert flag not in editor_response.content
