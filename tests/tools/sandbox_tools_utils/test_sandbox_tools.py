import textwrap
from pathlib import Path

import pytest
from test_helpers.tool_call_utils import (
    get_tool_call,
    get_tool_calls,
    get_tool_response,
)
from test_helpers.utils import flaky_retry

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    get_model,
)
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer import match
from inspect_ai.solver import (
    Generate,
    TaskState,
    generate,
    solver,
    use_tools,
)
from inspect_ai.tool import ToolCallError, bash_session, text_editor
from inspect_ai.util import sandbox, store
from inspect_ai.util._sandbox._cli import SANDBOX_TOOLS_DIR

NONROOT_COMPOSE = str(Path(__file__).parent / ".." / "test_sandbox_compose.yaml")
ROOTLESS_COMPOSE = str(
    Path(__file__).parent / ".." / "test_sandbox_compose_rootless.yaml"
)
SERVER_DIR = f"{SANDBOX_TOOLS_DIR}/.server"


# The Alpine variant exercises the musl injectable: detection routes musl sandboxes
# to the -musl onedir bundle. See design/plans/sandbox-tools-onedir.md.
@pytest.mark.parametrize(
    "sandbox",
    [
        "docker",
        ("docker", NONROOT_COMPOSE),
        (
            "docker",
            str(Path(__file__).parent / ".." / "test_sandbox_compose_alpine.yaml"),
        ),
    ],
)
@pytest.mark.slow
@flaky_retry(max_retries=3)
def test_text_editor_read(sandbox: str | tuple[str, str]):
    task = Task(
        dataset=[Sample(input="Please read the file '/etc/passwd'")],
        solver=[use_tools([text_editor()]), generate()],
        scorer=match(),
        sandbox=sandbox,
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
def test_text_editor_read_missing():
    task = Task(
        dataset=[Sample(input="Please read the file '/missing.txt'")],
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


def _whoami_model():
    return get_model(
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


@pytest.mark.slow
def test_bash_session_root():
    task = Task(
        dataset=[
            Sample(
                input='What is the output of running the command echo "start $(whoami) end"?'
            )
        ],
        solver=[use_tools([bash_session()]), generate()],
        scorer=match(),
        sandbox="docker",
    )
    log = eval(task, model=_whoami_model())[0]

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
def test_bash_session_non_root():
    task = Task(
        dataset=[
            Sample(
                input='What is the output of running the command echo "start $(whoami) end"?'
            )
        ],
        solver=[use_tools([bash_session(user="nobody")]), generate()],
        scorer=match(),
        sandbox="docker",
    )
    log = eval(task, model=_whoami_model())[0]

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


_SOCKET_PROBE = textwrap.dedent(
    f"""
    import socket
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.connect("{SERVER_DIR}/sandbox-tools.sock")
        print("connected")
    except OSError as ex:
        print(f"refused errno={{ex.errno}}")
    """
)


@solver
def _probe_server_dir_access(tools_user: str | None, other_user: str | None):
    """Record who can reach the server's state directory and socket."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        owner = await sb.exec(["stat", "-c", "%u %a", SERVER_DIR], user=tools_user)
        as_tools_user = await sb.exec(["python3", "-c", _SOCKET_PROBE], user=tools_user)
        as_other_user = await sb.exec(["python3", "-c", _SOCKET_PROBE], user=other_user)
        listing = await sb.exec(["ls", SERVER_DIR], user=other_user)
        store().set(
            "probe",
            {
                "owner": owner.stdout.strip(),
                "as_tools_user": as_tools_user.stdout.strip(),
                "as_other_user": as_other_user.stdout.strip(),
                "listing_success": listing.success,
                "listing_stderr": listing.stderr,
            },
        )
        return state

    return solve


# Run from the agent's own shell: connect_ex prints the errno instead of raising.
_AGENT_SOCKET_PROBE = (
    'python3 -c "import socket; s = socket.socket(socket.AF_UNIX); '
    f"print('probe-result', s.connect_ex('{SERVER_DIR}/sandbox-tools.sock'))\""
)


@pytest.mark.slow
def test_root_server_state_is_private_to_root():
    # Root-capable sandbox with a non-root default user, agent shell running as
    # that user: the server's state lives inside the root-owned tools tree, so the
    # agent can neither reach the socket from its own shell nor (via a host-side
    # exec as the default user) list the directory, while root still connects.
    task = Task(
        dataset=[Sample(input="whoami")],
        solver=[
            use_tools([bash_session(user="nonroot")]),
            generate(),
            _probe_server_dir_access(tools_user="root", other_user=None),
        ],
        sandbox=("docker", NONROOT_COMPOSE),
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
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash_session",
                tool_arguments={"action": "type_submit", "input": _AGENT_SOCKET_PROBE},
            ),
            ModelOutput.from_content(model="mockllm/model", content="All done."),
        ],
    )

    log = eval(task, model=model)[0]

    assert log.status == "success", log.error
    assert log.samples
    messages = log.samples[0].messages
    whoami_call, probe_call = get_tool_calls(messages, "bash_session")
    whoami = get_tool_response(messages, whoami_call)
    assert whoami and "start nonroot end" in whoami.content, whoami
    agent_probe = get_tool_response(messages, probe_call)
    assert agent_probe and "probe-result 13" in agent_probe.content, agent_probe

    probe = log.samples[0].store["probe"]
    assert probe["owner"] == "0 700", probe
    assert probe["as_tools_user"] == "connected", probe
    assert probe["as_other_user"] == "refused errno=13", probe
    assert not probe["listing_success"], probe
    assert "Permission denied" in probe["listing_stderr"], probe


@pytest.mark.slow
def test_rootless_server_state_is_private_to_the_tools_user():
    # Rootless sandbox: the server runs as the default user (uid 1111). Another
    # uid in the container must not be able to reach its socket or list its
    # control files, while the tools user itself still connects.
    task = Task(
        dataset=[Sample(input="whoami")],
        solver=[
            use_tools([bash_session()]),
            generate(),
            _probe_server_dir_access(tools_user=None, other_user="nobody"),
        ],
        sandbox=("docker", ROOTLESS_COMPOSE),
    )

    log = eval(task, model=_whoami_model())[0]

    assert log.status == "success", log.error
    assert log.samples
    messages = log.samples[0].messages
    tool_call = get_tool_call(messages, "bash_session")
    assert tool_call
    response = get_tool_response(messages, tool_call)
    assert response
    assert response.error is None, f"Tool call returns error: {response.error}"
    assert "start nonroot end" in response.content, response.content

    probe = log.samples[0].store["probe"]
    assert probe["owner"] == "1111 700", probe
    assert probe["as_tools_user"] == "connected", probe
    assert probe["as_other_user"] == "refused errno=13", probe
    assert not probe["listing_success"], probe
    assert "Permission denied" in probe["listing_stderr"], probe


@pytest.mark.slow
def test_bash_session_missing_user():
    task = Task(
        dataset=[
            Sample(
                input='What is the output of running the command echo "start $(whoami) end"?'
            )
        ],
        solver=[use_tools([bash_session(user="foo")]), generate()],
        scorer=match(),
        sandbox="docker",
    )
    log = eval(task, model=_whoami_model())[0]

    # This eval should entirely fail to run as the tool cannot be set up correctly.
    # I.e., it's not that the model has called the tool wrong, but the user made a mistake.
    # Note that the sandbox exec helper doesn't log anything about the user being
    # the cause of this error, so there's unfortunately nothing more precise for us to check
    assert log.status == "error"


@pytest.mark.slow
def test_text_editor_user():
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
        sandbox="docker",
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


@pytest.mark.slow
@pytest.mark.parametrize(
    "setup, expected_error",
    [
        pytest.param(
            f"mkdir -p {SANDBOX_TOOLS_DIR}",
            "owned by uid 1111, expected uid 0",
            id="nonroot-owned-directory",
        ),
        pytest.param(
            f"ln -s /home/nonroot {SANDBOX_TOOLS_DIR}",
            "is a symbolic link",
            id="symlink",
        ),
        pytest.param(
            f"touch {SANDBOX_TOOLS_DIR}",
            "is not a directory",
            id="regular-file",
        ),
    ],
)
def test_injection_refuses_tools_dir_planted_by_default_user(
    setup: str, expected_error: str
):
    """A non-root default user pre-creates the tools path before injection.

    Root exec works in this sandbox, so injection must fail before extracting or
    running anything as root rather than adopting the planted entry (or quietly
    downgrading to a default-user install).
    """
    task = Task(
        dataset=[Sample(input="whoami", setup=f"#!/bin/sh\n{setup}\n")],
        solver=[use_tools([bash_session()]), generate()],
        scorer=match(),
        sandbox=("docker", NONROOT_COMPOSE),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash_session",
                tool_arguments={"action": "type_submit", "input": "whoami"},
            ),
            ModelOutput.from_content(model="mockllm/model", content="All done."),
        ],
    )
    log = eval(task, model=model)[0]

    assert log.status == "error"
    assert log.error
    assert "Failed to inject sandbox tools" in log.error.message
    assert SANDBOX_TOOLS_DIR in log.error.message
    assert expected_error in log.error.message


@pytest.mark.slow
def test_tools_tree_is_inaccessible_to_default_user_after_root_injection():
    task = Task(
        dataset=[Sample(input="probe the tools directory")],
        solver=[use_tools([bash_session(user="nonroot")]), generate()],
        scorer=match(),
        sandbox=("docker", NONROOT_COMPOSE),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash_session",
                tool_arguments={
                    "action": "type_submit",
                    "input": (
                        f"stat -c 'owner=%u mode=%a' {SANDBOX_TOOLS_DIR}; "
                        f"ls {SANDBOX_TOOLS_DIR} && echo LISTED; "
                        f"touch {SANDBOX_TOOLS_DIR}/planted && echo CREATED; "
                        f"mv {SANDBOX_TOOLS_DIR} {SANDBOX_TOOLS_DIR}.moved && echo MOVED; "
                        f"rm -rf {SANDBOX_TOOLS_DIR} && echo REMOVED; echo probe-done"
                    ),
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
    output = response.text
    assert "probe-done" in output
    assert "owner=0 mode=700" in output
    for marker in ("LISTED", "CREATED", "MOVED", "REMOVED"):
        assert marker not in output, f"default user could act on tools tree: {output}"


@pytest.mark.slow
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
                tool_arguments={"command": "view", "path": "tmp/test_relative.txt"},
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
