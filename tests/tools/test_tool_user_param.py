"""The sandbox tools send the sandbox's default identity unless a user is given."""

import json
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any, Callable, cast
from uuid import uuid4

import anyio
import pytest
from test_helpers.sandbox import CannedSandbox

from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool
from inspect_ai.tool import (
    Tool,
    ToolCall,
    ToolError,
    bash,
    grep,
    list_files,
    python,
    read_file,
    skill,
)
from inspect_ai.tool._sandbox_tools_utils._legacy_helpers import (
    LEGACY_SANDBOX_CLI,
    legacy_tool_support_sandbox,
)
from inspect_ai.tool._tools import _bash_session as bash_session_module
from inspect_ai.tool._tools import _text_editor as text_editor_module
from inspect_ai.tool._tools._skill.types import Skill
from inspect_ai.util import SandboxIdentityError, sandbox_identity
from inspect_ai.util._sandbox.context import (
    sandbox_default_context_var,
    sandbox_environments_context_var,
    sandbox_with_environments_context_var,
)
from inspect_ai.util._sandbox.environment import (
    SandboxDefaultUser,
    SandboxEnvironment,
)
from inspect_ai.util._subprocess import ExecResult

DEFAULT_USER = SandboxDefaultUser(uid=1111, gid=1111, groups=[1111], home="/h")


class FakeSandbox:
    _tools_user = "root"
    _tools_default_user = DEFAULT_USER


def _patch_module(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_sandbox_with_injected_tools(**_kwargs: Any) -> FakeSandbox:
        return FakeSandbox()

    async def fake_request(*_args: Any, **kwargs: Any) -> Any:
        if kwargs["method"] == "version":
            return str(bash_session_module.BOUND_SHELL_TOOLS_VERSION)
        calls.append(kwargs)
        if kwargs["method"] == "bash_session_new_session":
            return bash_session_module.NewSessionResult(session_name="s")
        return "ok"

    monkeypatch.setattr(
        module, "sandbox_with_injected_tools", fake_sandbox_with_injected_tools
    )
    monkeypatch.setattr(module, "SandboxJSONRPCTransport", lambda *a, **k: None)
    for name in ("exec_model_request", "exec_scalar_request"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, fake_request)
    return calls


@pytest.mark.parametrize(
    "user, expected", [(None, DEFAULT_USER._asdict()), ("nobody", "nobody")]
)
async def test_text_editor_sends_user(
    monkeypatch: pytest.MonkeyPatch, user: str | None, expected: object
) -> None:
    calls = _patch_module(monkeypatch, text_editor_module)
    await text_editor_module.text_editor(user=user)(command="view", path="/x")
    [call] = calls
    assert call["params"]["_run_as"] == expected
    assert call["user"] == "root"


@pytest.mark.parametrize(
    "user, expected", [(None, DEFAULT_USER._asdict()), ("nobody", "nobody")]
)
async def test_bash_session_sends_user(
    monkeypatch: pytest.MonkeyPatch, user: str | None, expected: object
) -> None:
    from inspect_ai.util._store import Store, init_subtask_store

    init_subtask_store(Store())
    calls = _patch_module(monkeypatch, bash_session_module)
    await bash_session_module.bash_session(user=user)(action="read")
    new_session, _interact = calls
    assert new_session["method"] == "bash_session_new_session"
    assert new_session["params"]["user"] == expected
    assert new_session["user"] == "root"


# sandbox_identity() scopes


class _RecordingSandbox(CannedSandbox):
    """Records each exec's `(cmd, user, cwd)`; every exec succeeds."""

    def __init__(self) -> None:
        super().__init__(lambda _cmd, _user: ExecResult(True, 0, "out\n", ""))
        self.calls: list[tuple[list[str], str | None, str | None]] = []

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        self.calls.append((cmd, user, cwd))
        return await super().exec(
            cmd, input, cwd, env, user, timeout, timeout_retry, concurrency
        )


@contextmanager
def _environments(**environments: SandboxEnvironment) -> Iterator[None]:
    envs_token = sandbox_environments_context_var.set(environments)
    default_token = sandbox_default_context_var.set(next(iter(environments)))
    try:
        yield
    finally:
        sandbox_default_context_var.reset(default_token)
        sandbox_environments_context_var.reset(envs_token)


_EXEC_TOOLS: list[tuple[Callable[..., Tool], dict[str, Any]]] = [
    (bash, {"command": "ls"}),
    (python, {"code": "print(1)"}),
    (grep, {"pattern": "x"}),
    (list_files, {}),
    (read_file, {"file_path": "a.txt"}),
]


@pytest.mark.parametrize("factory, args", _EXEC_TOOLS)
async def test_exec_tools_run_as_the_scope_user(
    factory: Callable[..., Tool], args: dict[str, Any]
) -> None:
    default, workspace = _RecordingSandbox(), _RecordingSandbox()
    with (
        _environments(default=default, workspace=workspace),
        sandbox_identity("w-1", cwd="/home/w-1", sandbox="workspace"),
    ):
        await factory()(**args)
        await factory(user="w-1")(**args)
    assert default.calls == []
    assert [(user, cwd) for _cmd, user, cwd in workspace.calls] == [
        ("w-1", "/home/w-1"),
        ("w-1", "/home/w-1"),
    ]


@pytest.mark.parametrize("factory, args", _EXEC_TOOLS)
async def test_exec_tools_refuse_another_user_in_a_scope(
    factory: Callable[..., Tool], args: dict[str, Any]
) -> None:
    default = _RecordingSandbox()
    with _environments(default=default), sandbox_identity("w-1"):
        with pytest.raises(SandboxIdentityError, match="'root'"):
            await factory(user="root")(**args)
    assert default.calls == []


@pytest.mark.parametrize("factory, args", _EXEC_TOOLS)
async def test_exec_tools_keep_an_explicit_other_sandbox(
    factory: Callable[..., Tool], args: dict[str, Any]
) -> None:
    default, comparator = _RecordingSandbox(), _RecordingSandbox()
    with (
        _environments(default=default, comparator=comparator),
        sandbox_identity("w-1", cwd="/home/w-1"),
    ):
        await factory(user="root", sandbox="comparator")(**args)
    assert default.calls == []
    assert [(user, cwd) for _cmd, user, cwd in comparator.calls] == [("root", None)]


async def test_text_editor_runs_as_the_scope_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_module(monkeypatch, text_editor_module)
    sandbox = FakeSandbox()
    monkeypatch.setattr(
        text_editor_module, "sandbox_with_injected_tools", _returning(sandbox)
    )
    with _environments(default=cast(SandboxEnvironment, sandbox)):
        with sandbox_identity("w-1"):
            await text_editor_module.text_editor()(command="view", path="/x")
            with pytest.raises(SandboxIdentityError, match="'root'"):
                await text_editor_module.text_editor(user="root")(
                    command="view", path="/x"
                )
    [call] = calls
    assert call["params"]["_run_as"] == "w-1"
    assert call["user"] == "root"


def _returning(sandbox: Any) -> Callable[..., Any]:
    async def sandbox_with_injected_tools(**_kwargs: Any) -> Any:
        return sandbox

    return sandbox_with_injected_tools


@pytest.fixture
def bash_session_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[FakeSandbox, list[dict[str, Any]]]]:
    from inspect_ai.util._store import Store, init_subtask_store

    init_subtask_store(Store())
    calls = _patch_module(monkeypatch, bash_session_module)
    sandbox = FakeSandbox()
    monkeypatch.setattr(
        bash_session_module, "sandbox_with_injected_tools", _returning(sandbox)
    )
    with _environments(default=cast(SandboxEnvironment, sandbox)):
        yield sandbox, calls


async def test_bash_session_runs_as_the_scope_user(
    bash_session_sandbox: tuple[FakeSandbox, list[dict[str, Any]]],
) -> None:
    _sandbox, calls = bash_session_sandbox
    with sandbox_identity("w-1"):
        await bash_session_module.bash_session()(action="read")
        with pytest.raises(SandboxIdentityError, match="'root'"):
            await bash_session_module.bash_session(user="root", instance="other")(
                action="read"
            )
    new_session, interact = calls
    assert new_session["params"] == {"user": "w-1", "bind": True}
    assert interact["params"]["owner"] == "w-1"


async def test_bash_session_cannot_be_shared_between_scopes(
    bash_session_sandbox: tuple[FakeSandbox, list[dict[str, Any]]],
) -> None:
    tool = bash_session_module.bash_session(instance="team")
    with sandbox_identity("w-1"):
        await tool(action="read")
        await tool(action="read")
    with sandbox_identity("w-2"):
        with pytest.raises(SandboxIdentityError, match="created as 'w-1'"):
            await tool(action="read")


async def test_bash_session_opened_outside_a_scope_is_refused_in_one(
    bash_session_sandbox: tuple[FakeSandbox, list[dict[str, Any]]],
) -> None:
    tool = bash_session_module.bash_session(instance="team")
    await tool(action="read")
    with sandbox_identity("w-1"):
        with pytest.raises(SandboxIdentityError, match="outside a sandbox identity"):
            await tool(action="read")


async def test_bash_session_is_shared_outside_scopes(
    bash_session_sandbox: tuple[FakeSandbox, list[dict[str, Any]]],
) -> None:
    _sandbox, calls = bash_session_sandbox
    await bash_session_module.bash_session(instance="team")(action="read")
    await bash_session_module.bash_session(instance="team")(action="read")
    assert [call["method"] for call in calls] == [
        "bash_session_new_session",
        "bash_session",
        "bash_session",
    ]


async def test_computer_refuses_a_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from inspect_ai.tool._tools._computer import _common as computer_module

    default = _RecordingSandbox()

    async def sandbox_with(*_args: Any, **_kwargs: Any) -> SandboxEnvironment:
        return default

    monkeypatch.setattr(computer_module, "sandbox_with", sandbox_with)
    with _environments(default=default):
        assert await computer_module.computer_sandbox() is default
        with sandbox_identity("w-1"):
            with pytest.raises(SandboxIdentityError, match="The computer tool"):
                await computer_module.computer_sandbox()


_SKILL = Skill(name="example", description="Example.", instructions="Do it.")


async def test_skill_refuses_a_scope_before_any_sandbox_call() -> None:
    from inspect_ai.util._store import Store, init_subtask_store

    init_subtask_store(Store())
    default = _RecordingSandbox()
    with _environments(default=default), sandbox_identity("w-1"):
        with pytest.raises(SandboxIdentityError, match="The skill tool"):
            await skill([_SKILL])(command="example")
    assert default.calls == []
    assert default.written == []


async def test_skill_installs_in_a_sandbox_outside_the_scope() -> None:
    from inspect_ai.util._store import Store, init_subtask_store

    init_subtask_store(Store())
    default, other = _RecordingSandbox(), _RecordingSandbox()
    # every digest check answers "missing", so the skill is written
    other.policy = lambda _cmd, _user: ExecResult(True, 0, "missing\n", "")
    with (
        _environments(default=default, other=other),
        sandbox_identity("w-1"),
    ):
        result = await skill([_SKILL], sandbox="other", dir="/skills")(
            command="example"
        )
    assert "Base Path: /skills/example/SKILL.md" in str(result)
    assert default.calls == []
    assert other.written == ["/skills/example/SKILL.md"]


def _tool_support_sandbox() -> _RecordingSandbox:
    """A sandbox with `inspect-tool-support` on its PATH that reports version 1.0.0."""
    sandbox = _RecordingSandbox()
    sandbox.policy = lambda cmd, _user: ExecResult(
        True,
        0,
        '{"jsonrpc": "2.0", "result": "1.0.0", "id": 1}'
        if cmd[0] == LEGACY_SANDBOX_CLI
        else f"/usr/local/bin/{LEGACY_SANDBOX_CLI}\n",
        "",
    )
    return sandbox


def _tool_support_launches(sandbox: _RecordingSandbox) -> list[list[str]]:
    return [cmd for cmd, _user, _cwd in sandbox.calls if cmd[0] == LEGACY_SANDBOX_CLI]


@pytest.mark.parametrize("cached", [False, True], ids=["cold", "cached"])
async def test_web_browser_refuses_a_scope_before_running_tool_support(
    cached: bool,
) -> None:
    from inspect_ai.tool._tools._web_browser import _web_browser as web_browser_module

    default = _tool_support_sandbox()
    with _environments(default=default):
        sandbox_with_environments_context_var.set(
            {f":{LEGACY_SANDBOX_CLI}:True": default} if cached else {}
        )
        with sandbox_identity("w-1"):
            with pytest.raises(SandboxIdentityError, match="cannot run as a user"):
                await web_browser_module.web_browser_go()(url="https://example.com")
    assert _tool_support_launches(default) == []
    if cached:
        assert default.calls == []


async def test_web_browser_discovery_outside_the_scope_sandbox() -> None:
    default, browser = _RecordingSandbox(), _tool_support_sandbox()
    default.policy = lambda _cmd, _user: ExecResult(False, 1, "", "")
    with _environments(default=default, browser=browser):
        sandbox_with_environments_context_var.set({})
        with sandbox_identity("w-1"):
            sandbox_env, version = await legacy_tool_support_sandbox("web browser")
    assert sandbox_env is browser
    assert str(version) == "1.0.0"
    assert _tool_support_launches(default) == []


async def test_bash_session_cannot_move_to_another_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.util._sandbox.identity import sandbox_identity_environment
    from inspect_ai.util._store import Store, init_subtask_store

    init_subtask_store(Store())
    # every new session is named "s", as the first shell in each sandbox would be
    calls = _patch_module(monkeypatch, bash_session_module)

    async def scope_sandbox(**_kwargs: Any) -> Any:
        return sandbox_identity_environment()

    monkeypatch.setattr(
        bash_session_module, "sandbox_with_injected_tools", scope_sandbox
    )
    a, b = FakeSandbox(), FakeSandbox()
    tool = bash_session_module.bash_session(instance="team")
    with _environments(a=cast(SandboxEnvironment, a), b=cast(SandboxEnvironment, b)):
        with sandbox_identity("w-1", sandbox="a"):
            await tool(action="read")
        with sandbox_identity("w-1", sandbox="b"):
            with pytest.raises(SandboxIdentityError, match="in sandbox 'a'"):
                await tool(action="read")
        with sandbox_identity("w-1", sandbox="a"):
            await tool(action="read")
    assert [call["method"] for call in calls] == [
        "bash_session_new_session",
        "bash_session",
        "bash_session",
    ]


def _select_by_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select bash_session()'s sandbox with the real injection code, all injected."""
    from inspect_ai.util._sandbox.context import (
        SandboxInjectable,
        sandbox_with_injection,
    )

    async def injected(_sandbox: SandboxEnvironment) -> bool:
        return True

    async def never_inject(_sandbox: SandboxEnvironment) -> None:
        raise AssertionError("the sandboxes already have the tools")

    async def select_sandbox(**_kwargs: Any) -> SandboxEnvironment:
        return await sandbox_with_injection(SandboxInjectable(injected, never_inject))

    monkeypatch.setattr(
        bash_session_module, "sandbox_with_injected_tools", select_sandbox
    )


class _ToolsServer(CannedSandbox):
    """A sandbox whose tools answer bash_session requests as the tools server does.

    A shell created with `bind` gets a unique name and answers only requests that
    name its owner; other shells get counted names (`BashSession`, `BashSession_1`).
    `replace_server()` drops every shell, as a replaced server starts empty.
    `hold_version()` holds the next `version` request until the returned event
    is set. `lose_next_shell` replaces the server just after it opens a shell.
    """

    def __init__(self, version: str = "1.3.0") -> None:
        super().__init__(lambda _cmd, _user: ExecResult(True, 0, "", ""))
        self.version = version
        self.shells: dict[str, str | None] = {}
        """Owner of each shell, by name (None when unbound)."""
        self.received: list[tuple[str, dict[str, Any]]] = []
        """Each request a shell acted on: its name and the request's params."""
        self.methods: list[str] = []
        self.version_requested = anyio.Event()
        self.lose_next_shell = False
        self._version_hold: anyio.Event | None = None

    def replace_server(self) -> None:
        self.shells = {}

    def hold_version(self) -> anyio.Event:
        self._version_hold = anyio.Event()
        return self._version_hold

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        assert isinstance(input, str)
        request = json.loads(input)
        self.methods.append(request["method"])
        if request["method"] == "version" and self._version_hold is not None:
            hold, self._version_hold = self._version_hold, None
            self.version_requested.set()
            await hold.wait()
        response = {"jsonrpc": "2.0", "id": request["id"]}
        response.update(self._answer(request["method"], request.get("params", {})))
        return ExecResult(True, 0, json.dumps(response), "")

    def _answer(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "version":
            return {"result": self.version}
        if method == "bash_session_new_session":
            if params.get("bind"):
                name = f"BashSession_{uuid4().hex}"
            else:
                count = len(self.shells)
                name = f"BashSession_{count}" if count else "BashSession"
            self.shells[name] = params["user"] if params.get("bind") else None
            if self.lose_next_shell:
                self.lose_next_shell = False
                self.replace_server()
            return {"result": {"session_name": name}}
        assert method == "bash_session"
        name, owner = params["session_name"], params.get("owner")
        if name not in self.shells:
            code = -32097 if owner is not None else -32098
            return {"error": {"code": code, "message": f"no shell {name}"}}
        if self.shells[name] != owner:
            return {"error": {"code": -32096, "message": f"{name} is not {owner}'s"}}
        self.received.append((name, params))
        return {"result": "restarted" if params.get("restart") else "out"}


def _received_by(server: _ToolsServer, shells: set[str]) -> list[dict[str, Any]]:
    return [params for name, params in server.received if name in shells]


def _session_name(instance: str) -> str:
    from inspect_ai.util import store_as

    return store_as(bash_session_module.BashSessionStore, instance=instance).session_id


async def test_bash_session_keeps_its_sandbox_after_the_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.util._store import Store, init_subtask_store

    init_subtask_store(Store())
    _select_by_injection(monkeypatch)
    a, b = _ToolsServer(), _ToolsServer()
    team = bash_session_module.bash_session(instance="team")
    with _environments(a=a, b=b):
        await bash_session_module.bash_session(instance="unscoped")(action="read")
        with sandbox_identity("w-1", sandbox="b"):
            await team(action="read")
        with pytest.raises(ToolError, match="no longer have that shell"):
            await team(action="type_submit", input="id")
        with sandbox_identity("w-1", sandbox="b"):
            await team(action="read")
    assert a.received == [("BashSession", a.received[0][1])]
    assert [name for name, _ in b.received] == [_session_name("team")] * 2


async def _call_tool(tool: Tool, **arguments: Any) -> ChatMessageTool:
    """Call `tool` as a model's tool call, through the tool executor."""
    call = ToolCall(id="1", function="bash_session", arguments=arguments)
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])], [tool]
    )
    [message] = messages
    assert isinstance(message, ChatMessageTool)
    return message


@pytest.mark.parametrize("restore", [False, True], ids=["replaced", "restored"])
async def test_bash_session_refuses_a_scoped_shell_its_server_no_longer_has(
    monkeypatch: pytest.MonkeyPatch, restore: bool
) -> None:
    from inspect_ai.util import store_as
    from inspect_ai.util._store import Store, init_subtask_store, store, store_jsonable

    init_subtask_store(Store())
    _select_by_injection(monkeypatch)
    team = bash_session_module.bash_session(instance="team")
    server = _ToolsServer()
    with _environments(b=server):
        with sandbox_identity("w-1", sandbox="b"):
            await team(action="read")
        # with its server, the shell keeps working, scoped or not
        await team(action="read")
        with sandbox_identity("w-1", sandbox="b"):
            await team(action="read")
    stale = _session_name("team")
    assert server.received == [(stale, server.received[0][1])] * 3
    assert all(params["owner"] == "w-1" for _, params in server.received)

    if restore:
        # a checkpoint restore: the store in a fresh sandbox of the same name
        init_subtask_store(Store(json.loads(json.dumps(store_jsonable(store())))))
        server = _ToolsServer()
    else:
        # the tools server is replaced within the same sandbox object
        server.replace_server()
        server.received.clear()
    with _environments(b=server):
        # the first shell the new server opens, as the default user
        await bash_session_module.bash_session(instance="setup")(action="read")
        setup = _session_name("setup")
        # outside its scope, the model is told the shell is gone; no new shell
        for arguments in (
            {"action": "type_submit", "input": "id"},
            {"action": "read"},
            {"action": "restart"},
        ):
            message = await _call_tool(team, **arguments)
            assert message.error is not None
            assert "only inside the sandbox identity scope for 'w-1'" in (
                message.error.message
            )
        assert _session_name("team") == stale
        # in its scope, the model is told to restart, and restart recovers
        with sandbox_identity("w-1", sandbox="b"):
            message = await _call_tool(team, action="interrupt")
            assert message.error is not None
            assert "Use the 'restart' action" in message.error.message
            assert (await _call_tool(team, action="restart")).error is None
            assert (
                await _call_tool(team, action="type_submit", input="id")
            ).error is None
        # the new shell is bound to w-1, outside the scope as well
        assert (await _call_tool(team, action="read")).error is None
    fresh = _session_name("team")
    assert fresh not in (stale, setup)
    assert server.shells[fresh] == "w-1"
    saved = store_as(bash_session_module.BashSessionStore, instance="team")
    assert (saved.identity, saved.identity_sandbox) == ("w-1", "b")
    restart, typed, read = _received_by(server, {fresh})
    assert restart["restart"] is True and typed["input"] == "id\n"
    assert {restart["owner"], typed["owner"], read["owner"]} == {"w-1"}
    assert _received_by(server, {setup}) == [server.received[0][1]]


async def test_bash_session_recovers_a_lost_shell_once_per_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.util._store import Store, init_subtask_store

    init_subtask_store(Store())
    _select_by_injection(monkeypatch)
    server = _ToolsServer()
    team = bash_session_module.bash_session(instance="team")
    with _environments(b=server), sandbox_identity("w-1", sandbox="b"):
        await team(action="read")
        stale = _session_name("team")
        server.replace_server()
        await bash_session_module.bash_session(instance="setup")(action="read")
        setup = _session_name("setup")
        # the server is replaced again between the new shell and its restart
        server.lose_next_shell = True
        message = await _call_tool(team, action="restart")
        assert message.error is not None
        assert "Use the 'restart' action" in message.error.message
        assert [name for name, _ in server.received] == [stale, setup]
        # the next restart recovers
        assert (await _call_tool(team, action="restart")).error is None
        assert server.received[-1][0] == _session_name("team")
        assert server.shells[_session_name("team")] == "w-1"


@pytest.mark.parametrize("version", ["1.2.1", "1.3.0"])
async def test_bash_session_saved_scoped_shell_on_other_tools_outside_the_scope(
    monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    from inspect_ai.util._store import Store, init_subtask_store

    init_subtask_store(Store())
    _select_by_injection(monkeypatch)
    a, b = _ToolsServer(version=version), _ToolsServer()
    team = bash_session_module.bash_session(instance="team")
    with _environments(a=a, b=b):
        with sandbox_identity("w-1", sandbox="b"):
            await team(action="read")
        # unnamed injection outside the scope selects `a`
        message = await _call_tool(team, action="type_submit", input="id")
    assert message.error is not None
    expected = (
        "This sandbox's tools cannot use the saved shell"
        if version == "1.2.1"
        else "no longer have that shell"
    )
    assert expected in message.error.message
    assert "only inside the sandbox identity scope for 'w-1' in sandbox 'b'" in (
        message.error.message
    )
    assert a.methods == (
        ["version"] if version == "1.2.1" else ["version", "bash_session"]
    )
    assert a.received == []


@pytest.mark.parametrize("other", ["w-2", None], ids=["other-scope", "unscoped"])
async def test_bash_session_first_call_keeps_its_identity_when_another_wins(
    monkeypatch: pytest.MonkeyPatch, other: str | None
) -> None:
    from inspect_ai.util._store import Store, init_subtask_store

    init_subtask_store(Store())
    _select_by_injection(monkeypatch)
    server = _ToolsServer()
    release = server.hold_version()
    team = bash_session_module.bash_session(instance="team")
    refused: list[BaseException] = []

    async def first() -> None:
        with sandbox_identity("w-1", sandbox="b"):
            try:
                await team(action="type_submit", input="w-1 command")
            except SandboxIdentityError as ex:
                refused.append(ex)

    with _environments(b=server):
        async with anyio.create_task_group() as tg:
            tg.start_soon(first)
            # w-1's call waits on the tools version while another caller opens
            # the instance's shell
            await server.version_requested.wait()
            with sandbox_identity(other, sandbox="b") if other else nullcontext():
                await team(action="type_submit", input="other command")
            release.set()
    [error] = refused
    assert ("created as 'w-2'" if other else "outside a sandbox identity") in str(error)
    [(name, params)] = server.received
    assert name == _session_name("team") and params["input"] == "other command\n"
    assert params.get("owner") == other


async def test_bash_session_refuses_an_owner_the_server_does_not_have(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.util import store_as
    from inspect_ai.util._store import Store, init_subtask_store

    init_subtask_store(Store())
    _select_by_injection(monkeypatch)
    server = _ToolsServer()
    team = bash_session_module.bash_session(instance="team")
    with _environments(b=server):
        with sandbox_identity("w-1", sandbox="b"):
            await team(action="read")
        store_as(bash_session_module.BashSessionStore, instance="team").identity = "w-2"
        with pytest.raises(SandboxIdentityError, match="not w-2's"):
            await team(action="read")
    assert len(server.received) == 1


async def test_bash_session_refuses_a_scope_on_tools_without_bound_shells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.util._store import Store, init_subtask_store

    init_subtask_store(Store())
    _select_by_injection(monkeypatch)
    server = _ToolsServer(version="1.2.1")
    with _environments(b=server):
        with sandbox_identity("w-1", sandbox="b"):
            with pytest.raises(
                SandboxIdentityError, match="1.2.1.*needs version 1.3.0"
            ):
                await bash_session_module.bash_session(instance="team")(action="read")
        await bash_session_module.bash_session(instance="other")(action="read")
    assert server.methods == ["version", "bash_session_new_session", "bash_session"]
    assert server.shells == {"BashSession": None}
