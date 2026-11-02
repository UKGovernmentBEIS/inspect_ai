"""The sandbox agent bridge's token inside a sandbox identity scope."""

import json
import re
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from typing import Any

import anyio
import pytest
from test_helpers.sandbox import CannedSandbox
from test_helpers.utils import skip_if_no_docker

import inspect_ai.agent._bridge.sandbox.bridge as bridge_module
from inspect_ai import Task, eval
from inspect_ai.agent._bridge.sandbox.bridge import (
    BRIDGE_TOKEN_DIR,
    sandbox_agent_bridge,
)
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool._mcp._tools_bridge import BridgedToolsSpec
from inspect_ai.tool._tool import Tool, tool
from inspect_ai.util import sandbox
from inspect_ai.util._sandbox.context import (
    sandbox_default_context_var,
    sandbox_environments_context_var,
)
from inspect_ai.util._sandbox.exec_remote import (
    ExecCompleted,
    ExecOutput,
    ExecRemoteStreamingOptions,
    ExecStderr,
    exec_remote_streaming,
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
        self.removed: list[tuple[tuple[str, ...], str | None]] = []
        self.saturated = False
        """Commands that respect the sandbox's concurrency limits find no capacity."""

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
        if concurrency and self.saturated:
            # stands in for a provider waiting for capacity; bounded so a
            # regression fails rather than hangs the shielded cleanup
            with anyio.fail_after(2):
                await anyio.sleep_forever()
        return await super().exec(
            cmd, input, cwd, env, user, timeout, timeout_retry, concurrency
        )

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
        if "rm" in cmd:
            start = cmd.index("rm")
            assert cmd[start : start + 3] == ["rm", "-f", "--"]
            self.removed.append((tuple(cmd[start + 3 :]), user))
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
    temp_file = f"{BRIDGE_TOKEN_DIR}/.{token_file.rsplit('/', 1)[1]}.tmp"
    assert sandbox.removed == [((token_file, temp_file), "root")]


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


async def test_token_removal_does_not_wait_for_sandbox_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup is shielded, so the removal must not queue behind other commands."""
    sandbox = _BridgeSandbox()
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(10):
            with anyio.move_on_after(0.5) as scope:
                async with sandbox_agent_bridge():
                    sandbox.saturated = True
                    await anyio.sleep_forever()

    assert scope.cancelled_caught
    assert len(sandbox.removed) == 1


class _DelayedKillSandbox(_BridgeSandbox):
    """A sandbox with a real proxy process handle whose kill RPC takes a while.

    The proxy never publishes its token and its polls never return. A readiness
    check cancelled mid-flight finishes after a short delay, so on an enclosing
    cancellation the monitor's own kill of the proxy starts first.
    """

    def __init__(self) -> None:
        super().__init__(publish_after=None)
        self.events: list[str] = []
        self.on_submitted: Callable[[], None] = lambda: None
        self.start_delay = 0.0
        """Seconds the proxy's start reply (its pid) takes after submission."""

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
        method = json.loads(input)["method"] if isinstance(input, str) else None
        if method == "exec_remote_start":
            self.events.append("submitted")
            self.on_submitted()
            await anyio.sleep(self.start_delay)
            return _rpc_result({"pid": 42})
        if method == "exec_remote_poll":
            await anyio.sleep_forever()
        if method == "exec_remote_kill":
            self.events.append("kill_started")
            await anyio.sleep(0.5)
            self.events.append("kill_finished")
            return _rpc_result({"seq": 0, "stdout": "", "stderr": ""})
        if "wc -c" in " ".join(cmd):
            try:
                await anyio.sleep_forever()
            finally:
                with anyio.CancelScope(shield=True):
                    await anyio.sleep(0.1)
        if "rm" in cmd:
            self.events.append("remove")
        return await super().exec(
            cmd, input, cwd, env, user, timeout, timeout_retry, concurrency
        )

    async def fake_exec_remote(
        self, cmd: list[str], options: ExecRemoteStreamingOptions
    ) -> Any:
        self.launches.append(options)
        return await exec_remote_streaming(self, cmd, 5, options)

    def no_events(self) -> AbstractContextManager[None]:
        return nullcontext()


def _rpc_result(result: dict[str, object]) -> ExecResult[str]:
    return ExecResult(
        True, 0, json.dumps({"jsonrpc": "2.0", "result": result, "id": 1}), ""
    )


async def test_token_removal_waits_for_the_monitors_kill_of_the_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy still being killed could publish after an earlier removal."""
    sandbox = _DelayedKillSandbox()
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(10):
            with anyio.move_on_after(0.5) as scope:
                async with sandbox_agent_bridge():
                    raise AssertionError("bridge yielded")

    assert scope.cancelled_caught
    assert sandbox.events == ["submitted", "kill_started", "kill_finished", "remove"]


async def test_cancellation_while_the_proxy_starts_still_kills_it_before_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy started but not yet acquired must not outlive the token removal."""
    sandbox = _DelayedKillSandbox()
    sandbox.start_delay = 0.3
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(10):
            with anyio.CancelScope() as scope:
                sandbox.on_submitted = scope.cancel
                async with sandbox_agent_bridge():
                    raise AssertionError("bridge yielded")

    assert scope.cancelled_caught
    assert sandbox.events == ["submitted", "kill_started", "kill_finished", "remove"]


async def test_a_proxy_start_that_never_answers_ends_the_bridge_within_the_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shielded launch does not hold a cancellation past its bound."""
    monkeypatch.setattr(bridge_module, "BRIDGE_TOKEN_TIMEOUT", 0.5)
    sandbox = _DelayedKillSandbox()
    sandbox.start_delay = 60
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(10):
            with pytest.raises((TimeoutError, ExceptionGroup)) as excinfo:
                with anyio.CancelScope() as scope:
                    sandbox.on_submitted = scope.cancel
                    async with sandbox_agent_bridge():
                        raise AssertionError("bridge yielded")

    # under trio the cancelled scope strips its own cancellation from the
    # bridge's task group, leaving the timeout in a group
    error = excinfo.value
    if isinstance(error, ExceptionGroup):
        [error] = error.exceptions
    assert isinstance(error, TimeoutError)
    assert sandbox.events == ["submitted", "remove"]


async def test_bridge_in_a_scope_refuses_tools_that_cannot_mint_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _BridgeSandbox(tools_version="1.3.0")
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with pytest.raises(SandboxIdentityError, match="needs version 1.4.0"):
            async with sandbox_agent_bridge():
                raise AssertionError("bridge yielded")

    assert sandbox.launches == []


# ============================================================================
# End to end, with the injected tools in Docker
# ============================================================================

_NONROOT_COMPOSE = str(
    Path(__file__).parent.parent / "tools" / "test_sandbox_compose.yaml"
)

_SCOPED_CLIENT = """
import json, sys, urllib.error, urllib.request

def post(path, body, headers):
    request = urllib.request.Request(
        "http://localhost:13131" + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code

with open(sys.argv[1]) as file:
    token = file.read()
chat = {"model": "inspect", "messages": [{"role": "user", "content": "hi"}]}
mcp = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
print(json.dumps({
    "token_length": len(token),
    "chat": post("/v1/chat/completions", chat, {"Authorization": "Bearer " + token}),
    "chat_dummy": post("/v1/chat/completions", chat, {"Authorization": "Bearer sk-x"}),
    "messages": post("/v1/messages", {**chat, "max_tokens": 5}, {"x-api-key": token}),
    "mcp": post("/mcp/tools", mcp, {"Authorization": "Bearer " + token}),
    "mcp_none": post("/mcp/tools", mcp, {}),
}))
"""


@solver
def _scoped_bridge_in_docker() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        for user in ("w1", "w2"):
            created = await sb.exec(["useradd", "-m", user], user="root")
            assert created.success, created.stderr
        with sandbox_identity("w1", cwd="/home/w1"):
            async with sandbox_agent_bridge(
                bridged_tools=[BridgedToolsSpec(name="tools", tools=[_echo()])]
            ) as bridge:
                token_file = bridge.token_file
                assert token_file is not None
                # the first request is served: no retry until the proxy listens
                result = await sb.exec(
                    ["python3", "-c", _SCOPED_CLIENT, token_file], user="w1"
                )
                assert result.success, result.stderr
                assert json.loads(result.stdout) == {
                    "token_length": 64,
                    "chat": 200,
                    "chat_dummy": 401,
                    "messages": 200,
                    "mcp": 200,
                    "mcp_none": 401,
                }
                peer = await sb.exec(["cat", token_file], user="w2")
                assert not peer.success and "Permission denied" in peer.stderr
                listing = await sb.exec(["ls", BRIDGE_TOKEN_DIR], user="w2")
                assert not listing.success
                modes = await sb.exec(
                    ["stat", "-c", "%U %a", BRIDGE_TOKEN_DIR, token_file],
                    user="root",
                )
                assert modes.stdout.split("\n")[:2] == ["root 711", "w1 400"]
        gone = await sb.exec(["test", "-e", token_file], user="root")
        assert not gone.success
        return state

    return solve


@skip_if_no_docker
@pytest.mark.slow
def test_scoped_bridge_in_docker_requires_its_token() -> None:
    task = Task(
        dataset=[Sample(input="x")],
        solver=_scoped_bridge_in_docker(),
        sandbox=("docker", _NONROOT_COMPOSE),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error
