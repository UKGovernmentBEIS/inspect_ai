import json
import textwrap
import uuid
from pathlib import Path
from typing import Iterator

import anyio
import pytest
from test_helpers.tool_call_utils import (
    get_tool_call,
    get_tool_calls,
    get_tool_response,
)
from test_helpers.utils import flaky_retry

from inspect_ai import Task, eval, eval_async
from inspect_ai._util import logger as inspect_logger
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ContentText,
    get_model,
)
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer import match
from inspect_ai.solver import (
    Generate,
    Solver,
    TaskState,
    generate,
    solver,
    use_tools,
)
from inspect_ai.tool import (
    ToolCall,
    ToolCallError,
    ToolError,
    bash,
    bash_session,
    mcp_server_sandbox,
    python,
    text_editor,
)
from inspect_ai.tool._sandbox_tools_utils.sandbox import (
    _AMBIGUOUS_ROOT_ACCESS_WARNING,
)
from inspect_ai.util import (
    ExecRemoteAwaitableOptions,
    sandbox,
    store,
    tool_state_scope,
)
from inspect_ai.util._sandbox._cli import SANDBOX_TOOLS_DIR
from inspect_ai.util._sandbox.identity import sandbox_identity
from inspect_ai.util._sandbox.limits import override_max_exec_output_size

NONROOT_COMPOSE = str(Path(__file__).parent / ".." / "test_sandbox_compose.yaml")
ROOTLESS_COMPOSE = str(
    Path(__file__).parent / ".." / "test_sandbox_compose_rootless.yaml"
)
SERVER_DIR = f"{SANDBOX_TOOLS_DIR}/.server"


@pytest.mark.slow
@pytest.mark.parametrize("victim", ["root", "nobody"])
async def test_text_editor_history_is_private_to_effective_user(victim: str) -> None:
    @solver
    def check_history() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            sb = sandbox()
            uid = (await sb.exec(["id", "-u"], user=victim)).stdout.strip()
            attacker_uid = (await sb.exec(["id", "-u"])).stdout.strip()
            assert uid != attacker_uid and attacker_uid != "0"
            directory = f"/tmp/inspect-editor-{uid}"
            history = f"{directory}/history.json"
            target = f"/tmp/editor-{uuid.uuid4().hex}"
            editor = text_editor(user=victim)

            # A different non-root account wins the predictable-name race.
            assert (await sb.exec(["mkdir", "-m", "777", directory])).success
            await sb.write_file(history, json.dumps({target: ["forged"]}))
            with pytest.raises(ToolError, match="Cannot access text_editor history"):
                await editor(command="create", path=target, file_text="original")
            assert not (await sb.exec(["test", "-e", target])).success
            assert json.loads(await sb.read_file(history)) == {target: ["forged"]}
            assert (await sb.exec(["rm", "-r", directory])).success

            assert (await sb.exec(["ln", "-s", "/tmp", directory])).success
            with pytest.raises(ToolError, match="Cannot access text_editor history"):
                await editor(command="create", path=target, file_text="original")
            assert (await sb.exec(["rm", directory])).success

            # The legacy shared pickle must never be read, even by root.
            marker = f"{target}.executed"
            payload = f"cos\nsystem\n(S'touch {marker}'\ntR."
            await sb.write_file("/tmp/inspect_editor_history.pkl", payload)
            await editor(command="create", path=target, file_text="original")
            await editor(
                command="str_replace",
                path=target,
                old_str="original",
                new_str="replaced",
            )
            await editor(
                command="insert", path=target, insert_line=0, new_str="inserted"
            )
            assert not (await sb.exec(["test", "-e", marker])).success
            assert await sb.read_file("/tmp/inspect_editor_history.pkl") == payload
            ownership = await sb.exec(
                ["stat", "-c", "%u:%a", directory, history], user=victim
            )
            assert ownership.stdout.splitlines() == [f"{uid}:700", f"{uid}:600"]

            # Sticky permissions are insufficient when another user owns /tmp;
            # without the sticky bit, any user could replace our directory.
            for change, restore in [
                (["chown", attacker_uid, "/tmp"], ["chown", "0", "/tmp"]),
                (["chmod", "777", "/tmp"], ["chmod", "1777", "/tmp"]),
            ]:
                assert (await sb.exec(change, user="root")).success
                try:
                    with pytest.raises(
                        ToolError, match="History parent.*cannot be trusted"
                    ):
                        await editor(command="undo_edit", path=target)
                finally:
                    assert (await sb.exec(restore, user="root")).success

            for command in [
                ["sh", "-c", f"echo '{{}}' > {history}"],
                ["rm", history],
                ["ln", "-s", "/tmp/inspect_editor_history.pkl", f"{directory}/planted"],
                ["mv", directory, f"{directory}.stolen"],
            ]:
                result = await sb.exec(command)
                assert not result.success, command

            await editor(command="undo_edit", path=target)
            assert await sb.read_file(target) == "replaced"
            await editor(command="undo_edit", path=target)
            assert await sb.read_file(target) == "original"
            # Root plants a foreign-owned file to exercise the file-owner check
            # inside a correctly owned private directory.
            assert (
                await sb.exec(["chown", attacker_uid, history], user="root")
            ).success
            with pytest.raises(ToolError, match="Cannot read text_editor history"):
                await editor(command="undo_edit", path=target)
            assert await sb.read_file(target) == "original"
            assert (await sb.exec(["chown", uid, history], user="root")).success
            await editor(command="undo_edit", path=target)
            assert not (await sb.exec(["test", "-e", target])).success

            # The default account gets its own history after the same CLI imports.
            await text_editor()(command="create", path=target, file_text="default")
            own_history = f"/tmp/inspect-editor-{attacker_uid}/history.json"
            assert json.loads(await sb.read_file(own_history)) == {target: [-1]}
            await text_editor()(command="undo_edit", path=target)
            return state

        return solve

    [log] = await eval_async(
        Task(
            dataset=[Sample(input="Check private undo history")],
            solver=check_history(),
            sandbox=("docker", NONROOT_COMPOSE),
        ),
        model="mockllm/model",
    )
    assert log.status == "success", log.error


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


@pytest.mark.parametrize(
    "sandbox_config",
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
async def test_text_editor_directory_path_is_literal(
    sandbox_config: str | tuple[str, str],
) -> None:
    @solver
    def check_directory_view() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            sb = sandbox()
            directory = await sb.exec(["mktemp", "-d"])
            assert directory.success, directory.stderr
            base = directory.stdout.strip()
            marker = f"inspect-463-{uuid.uuid4().hex}"
            target = f"{base}/x$(touch {marker})"
            created = await sb.exec(["mkdir", target])
            assert created.success, created.stderr
            await sb.write_file(f"{target}/child.txt", "hello")
            link = f"{base}/link"
            linked = await sb.exec(["ln", "-s", target, link])
            assert linked.success, linked.stderr

            for user in [None, "root"]:
                for path in [target, link]:
                    result = str(
                        await text_editor(user=user)(command="view", path=path)
                    )
                    assert f"{target}/child.txt" in result
                    assert not (await sb.exec(["test", "-e", marker])).success
            return state

        return solve

    [log] = await eval_async(
        Task(
            dataset=[Sample(input="View a directory containing shell syntax")],
            solver=check_directory_view(),
            sandbox=sandbox_config,
        ),
        model="mockllm/model",
    )
    assert log.status == "success", log.error


@pytest.mark.slow
async def test_exec_remote_delivers_output_written_after_leader_exits() -> None:
    """A background child that writes after the leader exits is not lost.

    Fails on main when the first poll sees the exit before the child writes.
    """

    @solver
    def check_late_output() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            result = await sandbox().exec_remote(
                ["sh", "-c", "(sleep 0.5; echo late) & echo early"], stream=False
            )
            assert result.success, result.stderr
            assert result.stdout == "early\nlate\n", result.stdout
            return state

        return solve

    [log] = await eval_async(
        Task(
            dataset=[Sample(input="Run a command with late background output")],
            solver=check_late_output(),
            sandbox="docker",
        ),
        model="mockllm/model",
    )
    assert log.status == "success", log.error


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


_ID_CMD = "id -u; id -g; id -G; echo $HOME"
_CONTEXT = (Path(__file__).parent / ".." / "docker-compose-context").resolve()
_ALPINE_COMPOSE = str(Path(__file__).parent / ".." / "test_sandbox_compose_alpine.yaml")

# Minimal stdio MCP server (the image has no `mcp` package) with one tool that
# reports the identity it runs as via the same command the other checks use.
_MINI_MCP_SERVER = f"""
import json, subprocess, sys
for line in sys.stdin:
    msg = json.loads(line)
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        continue
    if method == "initialize":
        result = {{"protocolVersion": msg["params"]["protocolVersion"],
                  "capabilities": {{"tools": {{}}}},
                  "serverInfo": {{"name": "mini", "version": "0"}}}}
    elif method == "tools/list":
        result = {{"tools": [{{"name": "whoami", "description": "identity",
                              "inputSchema": {{"type": "object", "properties": {{}}}}}}]}}
    elif method == "tools/call":
        out = subprocess.run(["sh", "-c", {_ID_CMD!r}], capture_output=True, text=True)
        result = {{"content": [{{"type": "text", "text": out.stdout}}], "isError": False}}
    else:
        result = {{}}
    print(json.dumps({{"jsonrpc": "2.0", "id": mid, "result": result}}), flush=True)
"""


def _compose(
    tmp_path: Path, user: str | None, group_add: str | None, cap_drop: bool = False
) -> tuple[str, str]:
    extra = (
        (f"    user: '{user}'\n" if user else "")
        + (f"    group_add: ['{group_add}']\n" if group_add else "")
        + ("    cap_drop: [ALL]\n" if cap_drop else "")
    )
    compose = tmp_path / "compose.yaml"
    compose.write_text(
        f"services:\n  default:\n    build: {_CONTEXT}\n    command: tail -f /dev/null\n"
        f"{extra}    init: true\n    network_mode: none\n    stop_grace_period: 1s\n"
    )
    return ("docker", str(compose))


@solver
def _identity_parity(check_root: bool = True) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        ref = (await sb.exec(["sh", "-c", _ID_CMD])).stdout
        uid, gid = ref.split()[:2]
        expected = " ".join(ref.split())
        bash_id = f"({_ID_CMD}) | tr '\\n' ' '; stat -c T:%u:E \"$(tty)\""

        assert (await sb.exec_remote(["sh", "-c", _ID_CMD], stream=False)).stdout == ref

        out = str(await bash_session()(action="type_submit", input=bash_id))
        assert expected in out and "no job control" not in out, out
        assert f"T:{uid}:E" in out, out
        await bash_session()(action="restart")
        await bash_session()(action="read")
        out = str(await bash_session()(action="type_submit", input=bash_id))
        assert expected in out, out

        path = f"/tmp/{uuid.uuid4().hex}"
        await text_editor()(command="create", path=path, file_text="x")
        owner = (await sb.exec(["stat", "-c", "%u:%g", path])).stdout.strip()
        assert owner == f"{uid}:{gid}", owner

        await sb.write_file("/tmp/mini_mcp.py", _MINI_MCP_SERVER)
        async with mcp_server_sandbox(
            command="python3", args=["/tmp/mini_mcp.py"]
        ) as srv:
            [whoami] = await srv.tools()
            result = await whoami()
        assert isinstance(result, list) and isinstance(result[0], ContentText), result
        assert " ".join(result[0].text.split()) == expected, result

        if not check_root:
            return state

        # Responses over the exec output limit spill into root's private chunk
        # directory, which the CLI reserves a file in before switching to the
        # default user. (The limit is lowered because the editor clips its output
        # at 16k chars.)
        big = f"{path}.big"
        await sb.write_file(big, "".join(f"line {i}\n" for i in range(800)))
        with override_max_exec_output_size(4096):
            view = str(await text_editor()(command="view", path=big))
        assert "line 799" in view, view[-200:]
        spilled = await sb.exec(
            ["stat", "-c", "%u %a", f"{SERVER_DIR}/chunks"], user="root"
        )
        assert spilled.success and spilled.stdout.strip() == "0 700", spilled
        sibling = await sb.exec(["test", "-e", f"{SANDBOX_TOOLS_DIR}-json-rpc-chunks"])
        assert not sibling.success, "no shared chunk root beside the tools dir"

        # explicit user= still overrides the default
        root = ExecRemoteAwaitableOptions(user="root")
        assert (
            await sb.exec_remote(["id", "-u"], options=root, stream=False)
        ).stdout == "0\n"
        out = str(
            await bash_session(user="root", instance="root")(
                action="type_submit", input='echo "R:$(id -u):E"'
            )
        )
        assert "R:0:E" in out, out
        await text_editor(user="root")(
            command="create", path=f"{path}.r", file_text="x"
        )
        owner = (await sb.exec(["stat", "-c", "%u:%g", f"{path}.r"])).stdout.strip()
        assert owner == "0:0", owner
        return state

    return solve


# Run from the agent's own shell: connect_ex prints the errno instead of raising.
_AGENT_SOCKET_PROBE = (
    'python3 -c "import socket; s = socket.socket(socket.AF_UNIX); '
    f"print('probe-result', s.connect_ex('{SERVER_DIR}/sandbox-tools.sock'))\""
)


# Every injected tool must run as the same identity as `sandbox().exec()` with no
# user: uid, gid, supplementary groups and HOME, across the compose `user:` forms.
@pytest.mark.parametrize(
    "user,group_add",
    [
        (None, None),
        ("nonroot", None),
        ("1234:5678", None),
        ("0:1000", None),
        (None, "2000"),
        ("nonroot", "2000"),
    ],
)
@pytest.mark.slow
def test_tools_match_default_exec_identity(
    tmp_path: Path, user: str | None, group_add: str | None
) -> None:
    task = Task(
        dataset=[Sample(input="x")],
        solver=_identity_parity(),
        sandbox=_compose(tmp_path, user, group_add),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error


# `cap_drop: [ALL]` leaves root unable to switch users, so injection must take the
# rootless path: the server runs as the default user and no user switching happens.
@pytest.mark.slow
def test_tools_match_default_exec_identity_without_setuid_caps(tmp_path: Path) -> None:
    task = Task(
        dataset=[Sample(input="x")],
        solver=_identity_parity(check_root=False),
        sandbox=_compose(tmp_path, "nonroot", None, cap_drop=True),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error


@pytest.fixture
def _warn_once_messages() -> Iterator[list[str]]:
    # warn_once dedupes via a module-level list; clear it and yield it so the test
    # can assert on what was emitted.
    inspect_logger._warned.clear()
    yield inspect_logger._warned
    inspect_logger._warned.clear()


@solver
def _record_root_access() -> Solver:
    """Store the root-access decision as the solver first sees it, before any tool runs."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        access = sandbox()._root_access
        store().set("root_access", None if access is None else access.state)
        return state

    return solve


# The root-access decision is made at sample init, before the solver runs. On Docker
# it is definitive except when `root` cannot be resolved at all (no passwd entry:
# the rootless fixture), which gives no verdict; the tools then still install as
# the default user, but with a warning.
@pytest.mark.slow
@pytest.mark.parametrize(
    "fixture, expected, warned",
    [
        pytest.param("nonroot", "usable", False, id="root-can-switch-users"),
        pytest.param("cap_drop", "unusable", False, id="root-without-setuid-caps"),
        pytest.param("rootless", "ambiguous", True, id="root-not-in-passwd"),
    ],
)
def test_root_access_is_decided_before_the_solver_runs(
    tmp_path: Path,
    _warn_once_messages: list[str],
    fixture: str,
    expected: str,
    warned: bool,
) -> None:
    sandbox_spec = {
        "nonroot": ("docker", NONROOT_COMPOSE),
        "cap_drop": _compose(tmp_path, "nonroot", None, cap_drop=True),
        "rootless": ("docker", ROOTLESS_COMPOSE),
    }[fixture]
    task = Task(
        dataset=[Sample(input="whoami")],
        solver=[_record_root_access(), use_tools([bash_session()]), generate()],
        scorer=match(),
        sandbox=sandbox_spec,
    )

    log = eval(task, model=_whoami_model())[0]

    assert log.status == "success", log.error
    assert log.samples
    assert log.samples[0].store["root_access"] == expected
    tool_call = get_tool_call(log.samples[0].messages, "bash_session")
    assert tool_call
    response = get_tool_response(log.samples[0].messages, tool_call)
    assert response and "start nonroot end" in response.content, response
    assert (_AMBIGUOUS_ROOT_ACCESS_WARNING in _warn_once_messages) is warned


@solver
def _create_denied(path: str) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        try:
            await text_editor()(command="create", path=path, file_text="x")
        except Exception as ex:
            assert "Permission denied" in str(ex), ex
        else:
            raise AssertionError("create succeeded")
        return state

    return solve


@pytest.mark.slow
def test_text_editor_default_user_denied_root_path_alpine() -> None:
    task = Task(
        dataset=[Sample(input="x")],
        solver=_create_denied("/etc/x.txt"),
        sandbox=("docker", _ALPINE_COMPOSE),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error


_KILL_TOOLS_SERVER = (
    "kill -9 \"$(python3 -c 'import json, sys; "
    f'print(json.load(open(sys.argv[1]))["pid"])\' {SERVER_DIR}/server.pid)"'
)


@solver
def _scoped_shell_across_a_server_restart() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        assert (await sb.exec(["useradd", "-m", "w1"], user="root")).success
        team = bash_session(instance="team")
        with sandbox_identity("w1"):
            out = str(await team(action="type_submit", input="id -un"))
        assert "w1" in out, out
        out = str(await team(action="type_submit", input="id -un"))
        assert "w1" in out, out

        kill = await sb.exec(["sh", "-c", _KILL_TOOLS_SERVER], user="root")
        assert kill.success, kill.stderr
        # the next request starts a new server; its first shell is the default user's
        setup = bash_session(instance="setup")
        out = str(await setup(action="type_submit", input="id -un"))
        assert "nonroot" in out, out

        async def call(**arguments: str) -> ChatMessageTool:
            tool_call = ToolCall(id="1", function="bash_session", arguments=arguments)
            messages, _ = await execute_tools(
                [ChatMessageAssistant(content=[], tool_calls=[tool_call])], [team]
            )
            assert isinstance(messages[-1], ChatMessageTool)
            return messages[-1]

        # the model is told the shell is gone, outside its scope and in it
        stale = await call(action="type_submit", input="touch /tmp/stale")
        assert stale.error and "only inside the sandbox identity scope" in (
            stale.error.message
        ), stale
        with sandbox_identity("w1"):
            stale = await call(action="type_submit", input="touch /tmp/stale")
            assert stale.error and "Use the 'restart' action" in stale.error.message
            assert not (await sb.exec(["test", "-e", "/tmp/stale"])).success
            # and recovers with restart, in the same scoped flow
            restarted = await call(action="restart")
            assert restarted.error is None, restarted
            out = (await call(action="type_submit", input="id -un")).text
        assert "w1" in out, out
        out = str(await setup(action="type_submit", input="id -un"))
        assert "nonroot" in out and "w1" not in out, out
        return state

    return solve


# Trees an older release left in a reused container: one from before per-version
# directories and one from an older version, each with a launcher that fails.
_OLD_TOOLS_TREES = ["/var/tmp/.da7be258e003d428", "/var/tmp/.da7be258e003d428-v1"]
_FAILING_LAUNCHER = "#!/bin/sh\nexit 99\n"


@solver
def _tools_from_other_releases_are_left_alone() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        for tree in _OLD_TOOLS_TREES:
            planted = await sb.exec(
                [
                    "sh",
                    "-c",
                    'mkdir -m 700 "$1" "$1/.server" && printf "$2" > "$1/$3" && '
                    'chmod 700 "$1/$3"',
                    "sh",
                    tree,
                    _FAILING_LAUNCHER,
                    "inspect-sandbox-tools",
                ],
                user="root",
            )
            assert planted.success, planted.stderr

        out = str(await bash_session()(action="type_submit", input="id -un"))
        assert "nonroot" in out, out

        for tree in _OLD_TOOLS_TREES:
            listing = await sb.exec(["ls", "-A", tree], user="root")
            assert listing.stdout.split() == [".server", "inspect-sandbox-tools"]
            launcher = await sb.exec(
                ["cat", f"{tree}/inspect-sandbox-tools"], user="root"
            )
            assert launcher.stdout == "#!/bin/sh\nexit 99\n"
        return state

    return solve


# A reused container may hold trees other releases installed. This release installs
# and uses its own version's tree and leaves theirs alone.
@pytest.mark.slow
def test_tools_from_other_releases_are_left_alone() -> None:
    task = Task(
        dataset=[Sample(input="x")],
        solver=_tools_from_other_releases_are_left_alone(),
        sandbox=("docker", NONROOT_COMPOSE),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error


# A scoped shell is bound to its tools server: after the server is replaced
# mid-sample, the shell is refused (never reaching the new server's first shell)
# and `restart` opens a new one.
@pytest.mark.slow
def test_scoped_bash_session_across_a_tools_server_restart() -> None:
    task = Task(
        dataset=[Sample(input="x")],
        solver=_scoped_shell_across_a_server_restart(),
        sandbox=("docker", NONROOT_COMPOSE),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error


@solver
def _two_scoped_users_share_one_bash_session() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        for user in ("w1", "w2"):
            created = await sb.exec(
                ["sh", "-c", f"useradd -m {user} && chmod 700 /home/{user}"],
                user="root",
            )
            assert created.success, created.stderr
        shared = bash_session()
        opened = {"w1": anyio.Event(), "w2": anyio.Event()}

        async def worker(user: str, other: str) -> None:
            # $M keeps the echoed input from matching the output
            home = f"/home/{user}"
            with tool_state_scope(user), sandbox_identity(user, cwd=home):
                out = str(
                    await shared(
                        action="type_submit",
                        input=f'M=ok MARK={user}-shell; echo "user-$M=$(id -un) '
                        'cwd-$M=$(pwd)"',
                    )
                )
                assert f"user-ok={user} cwd-ok={home}" in out, out
                await text_editor()(command="create", path="notes", file_text=user)
                opened[user].set()
                await opened[other].wait()
                out = str(
                    await shared(
                        action="type_submit",
                        input=f"touch /home/{user}/mine; "
                        f'ls /home/{other} >/dev/null 2>&1 || echo "denied-$M"',
                    )
                )
                assert "denied-ok" in out, out
                out = str(
                    await shared(
                        action="type_submit",
                        input='echo "mark-$M=$MARK user-$M=$(id -un)"',
                    )
                )
                assert f"mark-ok={user}-shell user-ok={user}" in out, out

        async with anyio.create_task_group() as tg:
            tg.start_soon(worker, "w1", "w2")
            tg.start_soon(worker, "w2", "w1")
        for user in ("w1", "w2"):
            for name in ("mine", "notes"):
                owner = await sb.exec(
                    ["stat", "-c", "%U", f"/home/{user}/{name}"], user="root"
                )
                assert owner.stdout.strip() == user, owner
        # a shell cannot start in a directory its user cannot enter, including
        # one reached through a symlink into another user's private home
        linked = await sb.exec(
            [
                "sh",
                "-c",
                "mkdir -m 755 /home/w2/pub && ln -s /home/w2/pub /home/w1/link",
            ],
            user="root",
        )
        assert linked.success, linked.stderr
        for cwd in ("/home/w2", "/home/w1/link"):
            with sandbox_identity("w1", cwd=cwd):
                with pytest.raises(ToolError, match=f"cannot start in '{cwd}'"):
                    await bash_session(instance=f"w1-in-{cwd}")(action="read")
        return state

    return solve


# The swarm shape: two users in one sample, each in its own tool state scope and
# sandbox identity, share one bash_session() at the default instance and each
# gets its own shell, starting in its home; text_editor() resolves a relative
# path against the home.
@pytest.mark.slow
def test_two_scoped_users_share_one_bash_session() -> None:
    task = Task(
        dataset=[Sample(input="x")],
        solver=_two_scoped_users_share_one_bash_session(),
        sandbox=("docker", NONROOT_COMPOSE),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error


@solver
def _custom_tools_run_as_the_scope_user() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        default_uid = (await sb.exec(["id", "-u"])).stdout.strip()
        for user in ("w1", "w2"):
            created = await sb.exec(
                [
                    "sh",
                    "-c",
                    f"useradd -m {user} && chmod 700 /home/{user} && "
                    f"echo {user} > /home/{user}/secret && "
                    f"chown {user} /home/{user}/secret",
                ],
                user="root",
            )
            assert created.success, created.stderr

        # what a custom tool does: sandbox operations with no user
        async def custom_tool(user: str, other: str) -> None:
            assert (await sandbox().exec(["id", "-un"])).stdout.strip() == user
            await sandbox().write_file(f"/home/{user}/note", user)
            assert await sandbox().read_file(f"/home/{user}/secret") == f"{user}\n"
            with pytest.raises(PermissionError):
                await sandbox().read_file(f"/home/{other}/secret")

        for user, other in (("w1", "w2"), ("w2", "w1")):
            with sandbox_identity(user):
                await custom_tool(user, other)
                # injects the sandbox tools inside the first scope
                result = await sandbox().exec_remote(["id", "-un"], stream=False)
                assert result.stdout.strip() == user, result
        for user in ("w1", "w2"):
            owner = await sb.exec(
                ["stat", "-c", "%U", f"/home/{user}/note"], user="root"
            )
            assert owner.stdout.strip() == user, owner
        assert sb._tools_default_user is not None
        assert str(sb._tools_default_user.uid) == default_uid
        assert (await sb.exec(["id", "-u"])).stdout.strip() == default_uid
        return state

    return solve


# A custom tool's exec(), read_file() and write_file() with no user run as the
# scope's user; injection first triggered inside a scope still records the
# sandbox's default identity.
@pytest.mark.slow
def test_custom_tools_run_as_the_scope_user() -> None:
    task = Task(
        dataset=[Sample(input="x")],
        solver=_custom_tools_run_as_the_scope_user(),
        sandbox=("docker", NONROOT_COMPOSE),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error


@solver
def _scoped_tools_report_the_user_home() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        assert (await sb.exec(["useradd", "-m", "w1"], user="root")).success
        # outside a scope, a tool's own user keeps the container's HOME (and
        # its login shell fails to read root's profile)
        out = str(await bash(user="w1")(command="echo home=$HOME"))
        assert out.endswith("home=/root\n"), out
        with sandbox_identity("w1"):
            out = str(await bash()(command="echo home=$HOME"))
            assert out == "home=/home/w1\n", out
            code = "import os; print('home=' + os.environ['HOME'])"
            out = str(await python()(code=code))
            assert out == "home=/home/w1\n", out
            out = str(
                await bash_session()(
                    action="type_submit", input='echo "h-$((1))=$HOME"'
                )
            )
            assert "h-1=/home/w1" in out, out
            result = await sb.exec_remote(["sh", "-c", "echo $HOME"], stream=False)
            assert result.stdout == "/home/w1\n", result
        return state

    return solve


# The container sets HOME for its default user (root); inside a scope for w1,
# bash() and python() see w1's home, as bash_session() and exec_remote() do.
@pytest.mark.slow
def test_scoped_tools_get_the_user_home_over_a_preset_home(tmp_path: Path) -> None:
    compose = tmp_path / "compose.yaml"
    compose.write_text(
        f"services:\n  default:\n    build: {_CONTEXT}\n"
        "    command: tail -f /dev/null\n    environment:\n      HOME: /root\n"
        "    init: true\n    network_mode: none\n    stop_grace_period: 1s\n"
    )
    task = Task(
        dataset=[Sample(input="x")],
        solver=_scoped_tools_report_the_user_home(),
        sandbox=("docker", str(compose)),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error


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
def test_injection_ignores_archive_planted_at_former_staging_path():
    """A non-root default user plants files where older releases staged the archive.

    The archive travels to `tar` on stdin, so injection must neither read nor touch
    the planted files, and the genuine tools must come up.
    """
    planted = [f"{SANDBOX_TOOLS_DIR}.pkg.tgz", f"{SANDBOX_TOOLS_DIR}.pkg.tar"]
    setup = "".join(f"printf planted > {path}\n" for path in planted)
    probe = "; ".join(f"cat {path}" for path in planted)
    task = Task(
        dataset=[Sample(input="probe", setup=f"#!/bin/sh\n{setup}")],
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
                tool_arguments={
                    "action": "type_submit",
                    "input": f"{probe}; echo; echo probe-done",
                },
            ),
            ModelOutput.from_content(model="mockllm/model", content="All done."),
        ],
    )
    log = eval(task, model=model)[0]

    assert log.status == "success", log.error
    assert log.samples
    messages = log.samples[0].messages
    tool_call = get_tool_call(messages, "bash_session")
    assert tool_call
    response = get_tool_response(messages, tool_call)
    assert response
    assert response.error is None, f"Tool call returns error: {response.error}"
    assert "plantedplanted\nprobe-done" in response.text


@pytest.mark.slow
def test_injection_falls_back_to_uncompressed_tar_without_gzip():
    """Injection falls back to the uncompressed tar when `tar` cannot gunzip.

    The first `tar xzf` exits without reading its stdin, which is the case where an
    unhandled broken stdin write would abort injection instead of falling back.
    """
    task = Task(
        dataset=[Sample(input="probe")],
        solver=[use_tools([bash_session()]), generate()],
        scorer=match(),
        sandbox=(
            "docker",
            str(Path(__file__).parent / ".." / "test_sandbox_compose_nogzip.yaml"),
        ),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash_session",
                tool_arguments={
                    "action": "type_submit",
                    "input": "command -v gzip || echo no-gzip; echo probe-done",
                },
            ),
            ModelOutput.from_content(model="mockllm/model", content="All done."),
        ],
    )
    log = eval(task, model=model)[0]

    assert log.status == "success", log.error
    assert log.samples
    messages = log.samples[0].messages
    tool_call = get_tool_call(messages, "bash_session")
    assert tool_call
    response = get_tool_response(messages, tool_call)
    assert response
    assert response.error is None, f"Tool call returns error: {response.error}"
    assert "no-gzip\nprobe-done" in response.text


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
