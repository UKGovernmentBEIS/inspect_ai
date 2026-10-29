"""The sandbox tools send the sandbox's default identity unless a user is given."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Callable, cast

import pytest
from test_helpers.sandbox import CannedSandbox

from inspect_ai.tool import Tool, bash, grep, list_files, python, read_file
from inspect_ai.tool._tools import _bash_session as bash_session_module
from inspect_ai.tool._tools import _text_editor as text_editor_module
from inspect_ai.util import SandboxIdentityError, sandbox_identity
from inspect_ai.util._sandbox.context import (
    sandbox_default_context_var,
    sandbox_environments_context_var,
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
    new_session, _interact = calls
    assert new_session["params"]["user"] == "w-1"


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
            with pytest.raises(SandboxIdentityError, match="computer\\(\\)"):
                await computer_module.computer_sandbox()


async def test_web_browser_refuses_a_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from inspect_ai.tool._tools._web_browser import _web_browser as web_browser_module

    default = _RecordingSandbox()

    async def legacy_tool_support_sandbox(*_args: Any) -> tuple[Any, None]:
        return default, None

    monkeypatch.setattr(
        web_browser_module, "legacy_tool_support_sandbox", legacy_tool_support_sandbox
    )
    with _environments(default=default), sandbox_identity("w-1"):
        with pytest.raises(SandboxIdentityError, match="web_browser\\(\\)"):
            await web_browser_module.web_browser_go()(url="https://example.com")
    assert default.calls == []
