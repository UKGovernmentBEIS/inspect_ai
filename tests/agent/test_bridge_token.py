"""The sandbox agent bridge's token inside a sandbox identity scope."""

import json
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any

import anyio
import pytest
from test_helpers.sandbox import CannedSandbox

import inspect_ai.agent._bridge.sandbox.bridge as bridge_module
from inspect_ai.agent._bridge.sandbox.bridge import (
    BRIDGE_TOKEN_DIR,
    sandbox_agent_bridge,
)
from inspect_ai.tool._mcp._tools_bridge import BridgedToolsSpec
from inspect_ai.tool._tool import Tool, tool
from inspect_ai.util._sandbox.context import (
    sandbox_default_context_var,
    sandbox_environments_context_var,
)
from inspect_ai.util._sandbox.exec_remote import (
    ExecCompleted,
    ExecOutput,
    ExecRemoteStreamingOptions,
    ExecStderr,
)
from inspect_ai.util._sandbox.identity import SandboxIdentityError, sandbox_identity
from inspect_ai.util._subprocess import ExecResult

TOKEN_FILE_ENV = "BRIDGE_MODEL_SERVICE_TOKEN_FILE"
TOKEN_USER_ENV = "BRIDGE_MODEL_SERVICE_TOKEN_USER"


class _FakeProxy:
    """The proxy process: runs until killed, or exits at once with an error."""

    def __init__(self, exit_stderr: str | None) -> None:
        self.exit_stderr = exit_stderr
        self.killed = anyio.Event()

    def __aiter__(self) -> AsyncIterator[ExecOutput]:
        return self._events()

    async def _events(self) -> AsyncIterator[ExecOutput]:
        if self.exit_stderr is not None:
            yield ExecStderr(data=self.exit_stderr)
            yield ExecCompleted(exit_code=1)
            return
        await self.killed.wait()

    async def kill(self) -> None:
        self.killed.set()


class _BridgeSandbox(CannedSandbox):
    """A sandbox whose proxy publishes its token after `publish_after` checks."""

    def __init__(
        self,
        *,
        tools_version: str = "1.4.0",
        publish_after: int | None = 2,
        exit_stderr: str | None = None,
    ) -> None:
        super().__init__(self._answer)
        self._tools_user = "root"
        self.tools_version = tools_version
        self.publish_after = publish_after
        self.checks = 0
        self.proxy = _FakeProxy(exit_stderr)
        self.launches: list[ExecRemoteStreamingOptions] = []
        self.removed: list[tuple[str, str | None]] = []

    def _answer(self, cmd: list[str], user: str | None) -> ExecResult[str]:
        if cmd[-1] == "exec":
            result = json.dumps(
                {"jsonrpc": "2.0", "result": self.tools_version, "id": 1}
            )
            return ExecResult(True, 0, result, "")
        if "wc -c" in cmd[2]:
            self.checks += 1
            if self.publish_after is not None and self.checks > self.publish_after:
                return ExecResult(True, 0, "64\n", "")
            return ExecResult(False, 1, "", "")
        if cmd[-4:-1] == ["rm", "-f", "--"]:
            self.removed.append((cmd[-1], user))
            return ExecResult(True, 0, "", "")
        raise AssertionError(f"unexpected exec {cmd}")

    async def fake_exec_remote(
        self, cmd: list[str], options: ExecRemoteStreamingOptions
    ) -> _FakeProxy:
        self.launches.append(options)
        return self.proxy


@contextmanager
def _sandbox(
    monkeypatch: pytest.MonkeyPatch, sandbox: _BridgeSandbox
) -> Iterator[None]:
    async def sandbox_with_injected_tools(*, sandbox_name: str | None = None) -> Any:
        return sandbox

    async def run_model_service(*args: Any) -> None:
        started: anyio.Event = args[-1]
        started.set()
        await anyio.sleep_forever()

    monkeypatch.setattr(
        bridge_module, "sandbox_with_injected_tools", sandbox_with_injected_tools
    )
    monkeypatch.setattr(bridge_module, "run_model_service", run_model_service)
    monkeypatch.setattr(sandbox, "exec_remote", sandbox.fake_exec_remote)
    envs_token = sandbox_environments_context_var.set({"default": sandbox})
    default_token = sandbox_default_context_var.set("default")
    try:
        yield
    finally:
        sandbox_default_context_var.reset(default_token)
        sandbox_environments_context_var.reset(envs_token)


@tool
def _echo() -> Tool:
    async def execute(text: str) -> str:
        """Echo.

        Args:
            text: Text.
        """
        return text

    return execute


async def test_bridge_in_a_scope_waits_for_its_token_and_removes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _BridgeSandbox()
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(20):
            async with sandbox_agent_bridge(
                bridged_tools=[BridgedToolsSpec(name="tools", tools=[_echo()])]
            ) as bridge:
                assert sandbox.checks == 3
                assert sandbox.removed == []
                token_file = bridge.token_file

    [launch] = sandbox.launches
    assert launch.user == "root"
    assert launch.env is not None
    assert launch.env[TOKEN_FILE_ENV] == token_file
    assert launch.env[TOKEN_USER_ENV] == "w-1"
    assert token_file is not None
    assert re.fullmatch(rf"{BRIDGE_TOKEN_DIR}/proxy_\w+", token_file)
    # the host never has a token to send
    for value in [*launch.env.values(), *map(str, sandbox.exec_calls)]:
        assert not re.search(r"[0-9a-f]{64}", value)
    [config] = bridge.mcp_server_configs
    assert config.headers == {"Authorization": "Bearer ${INSPECT_BRIDGE_TOKEN}"}
    checks = [cmd for cmd, _ in sandbox.exec_calls if "wc -c" in " ".join(cmd)]
    assert all(cmd[-1] == token_file for cmd in checks)
    assert {user for cmd, user in sandbox.exec_calls} == {"root"}
    assert sandbox.proxy.killed.is_set()
    assert sandbox.removed == [(token_file, "root")]


async def test_bridge_outside_a_scope_asks_for_no_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _BridgeSandbox()
    with _sandbox(monkeypatch, sandbox):
        async with sandbox_agent_bridge(
            bridged_tools=[BridgedToolsSpec(name="tools", tools=[_echo()])]
        ) as bridge:
            assert bridge.token_file is None

    [launch] = sandbox.launches
    assert launch.env is not None
    assert TOKEN_FILE_ENV not in launch.env and TOKEN_USER_ENV not in launch.env
    assert bridge.mcp_server_configs[0].headers is None
    assert sandbox.exec_calls == []


async def test_bridge_raises_when_the_token_never_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge_module, "BRIDGE_TOKEN_TIMEOUT", 0.5)
    sandbox = _BridgeSandbox(publish_after=None)
    entered = False
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with pytest.raises(RuntimeError, match="did not publish its bridge token"):
            with anyio.fail_after(20):
                async with sandbox_agent_bridge():
                    entered = True

    assert not entered
    assert sandbox.proxy.killed.is_set()
    assert [user for _, user in sandbox.removed] == ["root"]


async def test_bridge_raises_with_stderr_when_the_proxy_exits_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _BridgeSandbox(publish_after=None, exit_stderr="cannot publish token")
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with pytest.raises(RuntimeError, match="cannot publish token"):
            with anyio.fail_after(20):
                async with sandbox_agent_bridge():
                    raise AssertionError("bridge yielded")

    assert len(sandbox.removed) == 1


async def test_cancellation_ends_the_wait_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _BridgeSandbox(publish_after=None)
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(5):
            with anyio.move_on_after(0.5) as scope:
                async with sandbox_agent_bridge():
                    raise AssertionError("bridge yielded")

    assert scope.cancelled_caught
    assert sandbox.proxy.killed.is_set()
    assert len(sandbox.removed) == 1


async def test_bridge_in_a_scope_refuses_tools_that_cannot_mint_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _BridgeSandbox(tools_version="1.3.0")
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with pytest.raises(SandboxIdentityError, match="needs version 1.4.0"):
            async with sandbox_agent_bridge():
                raise AssertionError("bridge yielded")

    assert sandbox.launches == []
