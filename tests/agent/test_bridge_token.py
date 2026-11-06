"""The sandbox agent bridge's token inside a sandbox identity scope."""

import json
import posixpath
import re
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, NamedTuple, cast

import anyio
import pytest
from test_helpers.sandbox import CannedSandbox
from test_helpers.utils import skip_if_no_docker

import inspect_ai.agent._bridge.sandbox.bridge as bridge_module
import inspect_ai.agent._bridge.sandbox.service as service_module
import inspect_ai.tool._sandbox_tools_utils.sandbox as tools_module
import inspect_ai.util._sandbox.environment as environment_module
from inspect_ai import Task, eval
from inspect_ai.agent._bridge.sandbox.bridge import (
    BRIDGE_TOKEN_DIR,
    sandbox_agent_bridge,
)
from inspect_ai.agent._bridge.sandbox.service import MODEL_SERVICE
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool._mcp._tools_bridge import BridgedToolsSpec
from inspect_ai.tool._tool import Tool, tool
from inspect_ai.util import LimitExceededError, SandboxEnvironment, sandbox, time_limit
from inspect_ai.util._sandbox._framework_directory import (
    _MISSING_MARKER,
    _VERIFIED_MARKER,
    _VIOLATION_MARKER,
    FrameworkDirectoryError,
)
from inspect_ai.util._sandbox._privileged import SHELL_PATH
from inspect_ai.util._sandbox.context import (
    sandbox_default_context_var,
    sandbox_environments_context_var,
)
from inspect_ai.util._sandbox.exec_remote import (
    KILL_KEY_TIMEOUT,
    ExecCompleted,
    ExecOutput,
    ExecRemoteStreamingOptions,
    ExecStderr,
    exec_remote_streaming,
)
from inspect_ai.util._sandbox.identity import SandboxIdentityError, sandbox_identity
from inspect_ai.util._sandbox.service import REQUESTS_DIR, SERVICES_DIR
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


class _Verified(NamedTuple):
    """A command run inside a verified framework directory."""

    directory: str
    expected_uid: str
    mode: str
    cmd: list[str]


def _verified(cmd: list[str]) -> _Verified | None:
    """The directory and wrapped command of a verified-directory exec, if any."""
    if cmd[:2] != [SHELL_PATH, "-c"] or _VERIFIED_MARKER not in cmd[2]:
        return None
    return _Verified(posixpath.join(cmd[8], cmd[9]), cmd[4], cmd[7], cmd[10:])


class _BridgeSandbox(CannedSandbox):
    """A sandbox whose proxy publishes its token after `publish_after` checks.

    The token directory is missing at the first check and created by the
    proxy before the second, unless `token_dir` is "planted": another user
    created it, so it fails verification, and put a 64-byte file in it.
    """

    def __init__(
        self,
        *,
        tools_version: str = "1.5.0",
        publish_after: int | None = 2,
        exit_stderr: str | None = None,
        token_dir: Literal["proxy", "planted"] = "proxy",
    ) -> None:
        super().__init__(self._answer)
        self._tools_user = "root"
        self.tools_version = tools_version
        self.publish_after = publish_after
        self.token_dir = token_dir
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
        if cmd == ["check-tools"]:
            return ExecResult(True, 0, "", "")
        if cmd[-1] == "exec":
            result = json.dumps(
                {"jsonrpc": "2.0", "result": self.tools_version, "id": 1}
            )
            return ExecResult(True, 0, result, "")
        verified = _verified(cmd)
        if verified is None:
            if self.token_dir == "planted" and "wc -c" in cmd[2]:
                # an unverified size check finds the planted file
                return ExecResult(True, 0, "64\n", "")
            raise AssertionError(f"unexpected exec {cmd}")
        assert verified.directory == BRIDGE_TOKEN_DIR
        check = "wc -c" in verified.cmd[2] if verified.cmd[0] == "sh" else False
        if check:
            self.checks += 1
        else:
            assert verified.cmd[:3] == ["rm", "-f", "--"]
            self.removed.append((tuple(verified.cmd[3:]), user))
        if self.token_dir == "planted":
            return ExecResult(
                False, 3, "", f"{_VIOLATION_MARKER}: it is owned by uid 61000\n"
            )
        published = self.publish_after is not None and self.checks > self.publish_after
        if self.checks < 2 and not published:
            return ExecResult(False, 4, "", f"{_MISSING_MARKER}: no such directory\n")
        if check and published:
            return ExecResult(True, 0, "64\n", f"{_VERIFIED_MARKER}\n")
        return ExecResult(not check, int(check), "", f"{_VERIFIED_MARKER}\n")

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
    # the proxy listens only on IPv4; `localhost` could reach another user on ::1
    assert config.url == f"http://127.0.0.1:{bridge.port}/mcp/tools"
    # the checks and the removal run in the verified token directory, owned
    # by the tools user (uid 0) with mode 0711
    name = posixpath.basename(token_file)
    verified = [_verified(cmd) for cmd, _ in sandbox.exec_calls[1:]]
    assert len(verified) == 4
    for call in verified:
        assert call is not None
        assert (call.expected_uid, call.mode) == ("0", "711")
    assert all(call is not None and call.cmd[-1] == name for call in verified[:3])
    assert {user for cmd, user in sandbox.exec_calls} == {"root"}
    assert sandbox.proxy.killed.is_set()
    assert sandbox.removed == [((name, f".{name}.tmp"), "root")]


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
    assert (
        bridge.mcp_server_configs[0].url == f"http://localhost:{bridge.port}/mcp/tools"
    )
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


async def test_scoped_bridge_control_does_not_wait_for_sandbox_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bridge starts while other commands hold the capacity.

    Its version check, token wait and token removal run outside the limits.
    """
    sandbox = _BridgeSandbox(publish_after=0)
    sandbox.saturated = True
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(10):
            async with sandbox_agent_bridge():
                assert sandbox.checks == 1

    assert sandbox.proxy.killed.is_set()
    assert len(sandbox.removed) == 1


async def test_bridge_refuses_a_token_directory_another_user_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file planted in a directory the tools user does not own is not the token."""
    sandbox = _BridgeSandbox(token_dir="planted")
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with pytest.raises(FrameworkDirectoryError, match="cannot be trusted"):
            with anyio.fail_after(10):
                async with sandbox_agent_bridge():
                    raise AssertionError("bridge yielded")

    assert sandbox.checks == 1
    assert sandbox.proxy.killed.is_set()
    # the removal is refused too, rather than run in that directory
    assert len(sandbox.removed) == 1


async def test_proxy_launch_does_not_check_tools_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public exec_remote() launches the proxy while the capacity is held.

    The bridge has already checked the sandbox's tools, so a second check, which
    waits for capacity, must not run inside the bounded launch.
    """
    monkeypatch.setattr(bridge_module, "BRIDGE_TOKEN_TIMEOUT", 0.5)
    sandbox = _BridgeSandbox(publish_after=0)
    tools_checks: list[SandboxEnvironment] = []
    launches: list[ExecRemoteStreamingOptions] = []

    async def check_tools(
        *, sandbox_name: str | None = None, sandbox: Any = None
    ) -> SandboxEnvironment:
        tools_checks.append(sandbox)
        await sandbox.exec(["check-tools"])
        return cast(SandboxEnvironment, sandbox)

    async def start(
        target: SandboxEnvironment,
        cmd: list[str],
        poll_interval: float,
        options: ExecRemoteStreamingOptions,
    ) -> _FakeProxy:
        launches.append(options)
        return sandbox.proxy

    async def run_model_service(*args: Any) -> None:
        sandbox.saturated = True
        started: anyio.Event = args[-1]
        started.set()
        await anyio.sleep_forever()

    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        monkeypatch.delattr(sandbox, "exec_remote")
        monkeypatch.setattr(tools_module, "sandbox_with_injected_tools", check_tools)
        monkeypatch.setattr(environment_module, "exec_remote_streaming", start)
        monkeypatch.setattr(bridge_module, "run_model_service", run_model_service)
        assert not sandbox._tools_injected
        with anyio.fail_after(10):
            async with sandbox_agent_bridge():
                assert sandbox.checks == 1

    assert tools_checks == []
    [launch] = launches
    assert launch.concurrency is False
    assert sandbox.proxy.killed.is_set()
    assert len(sandbox.removed) == 1


class _DelayedKillSandbox(_BridgeSandbox):
    """A sandbox with a real proxy process handle whose kill RPC takes a while.

    The proxy never publishes its token and its polls never return. A readiness
    check cancelled mid-flight finishes after a short delay, so on an enclosing
    cancellation the monitor's own kill of the proxy starts first. A kill by
    job key stops the started proxy, so `publish_late()` then publishes nothing.
    """

    def __init__(self) -> None:
        super().__init__(publish_after=None)
        self.events: list[str] = []
        self.on_submitted: Callable[[], None] = lambda: None
        self.start_delay = 0.0
        """Seconds the proxy's start reply (its pid) takes after submission."""
        self.job_key: str | None = None
        self.kill_key_args: dict[str, object] = {}
        self.proxy_killed_by_key = False
        self.late_tokens: list[str] = []

    def publish_late(self) -> None:
        """Publish the token, as a started proxy that was not killed would."""
        if self.job_key is not None and not self.proxy_killed_by_key:
            self.late_tokens.append(self.job_key)

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
        request = json.loads(input) if isinstance(input, str) else {}
        method = request.get("method")
        if method == "exec_remote_start":
            self.job_key = request["params"]["job_key"]
            self.events.append("submitted")
            self.on_submitted()
            await anyio.sleep(self.start_delay)
            return _rpc_result({"pid": 42})
        if method == "exec_remote_poll":
            await anyio.sleep_forever()
        if method == "exec_remote_kill_key":
            self.events.append("kill_key")
            self.kill_key_args = dict(
                job_key=request["params"]["job_key"],
                timeout=timeout,
                concurrency=concurrency,
            )
            self.proxy_killed_by_key = request["params"]["job_key"] == self.job_key
            return _rpc_result({"killed": self.proxy_killed_by_key})
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


def _assert_killed_by_key_before_removal(sandbox: _DelayedKillSandbox) -> None:
    sandbox.publish_late()
    assert sandbox.events == ["submitted", "kill_key", "remove"]
    assert sandbox.kill_key_args == dict(
        job_key=sandbox.job_key, timeout=KILL_KEY_TIMEOUT, concurrency=False
    )
    assert sandbox.late_tokens == []


async def test_a_proxy_start_that_times_out_is_killed_by_key_before_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy whose pid never arrives must not publish after the token removal."""
    monkeypatch.setattr(bridge_module, "BRIDGE_TOKEN_TIMEOUT", 0.5)
    sandbox = _DelayedKillSandbox()
    sandbox.start_delay = 60
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(10):
            with pytest.raises(RuntimeError, match="did not start within 0.5 seconds"):
                async with sandbox_agent_bridge():
                    raise AssertionError("bridge yielded")

    _assert_killed_by_key_before_removal(sandbox)


async def test_a_cancellation_while_the_proxy_start_times_out_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge_module, "BRIDGE_TOKEN_TIMEOUT", 0.5)
    sandbox = _DelayedKillSandbox()
    sandbox.start_delay = 60
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(10):
            with anyio.CancelScope() as scope:
                sandbox.on_submitted = scope.cancel
                async with sandbox_agent_bridge():
                    raise AssertionError("bridge yielded")

    assert scope.cancel_called
    _assert_killed_by_key_before_removal(sandbox)


async def test_a_time_limit_while_the_proxy_start_times_out_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge_module, "BRIDGE_TOKEN_TIMEOUT", 1)
    sandbox = _DelayedKillSandbox()
    sandbox.start_delay = 60
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(10):
            with pytest.raises(LimitExceededError) as excinfo:
                with time_limit(0.3):
                    async with sandbox_agent_bridge():
                        raise AssertionError("bridge yielded")

    assert excinfo.value.type == "time"
    _assert_killed_by_key_before_removal(sandbox)


@pytest.mark.parametrize(
    "token_file,user", [(None, None), (f"{BRIDGE_TOKEN_DIR}/proxy_x", "root")]
)
async def test_a_bridge_requiring_a_token_keeps_its_service_queue_to_the_tools_user(
    monkeypatch: pytest.MonkeyPatch, token_file: str | None, user: str | None
) -> None:
    """Otherwise the default user could submit requests to it without the token."""
    calls: list[dict[str, Any]] = []

    async def sandbox_service(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(service_module, "sandbox_service", sandbox_service)
    bridge = SimpleNamespace(token_file=token_file)
    await service_module.run_model_service(
        _BridgeSandbox(), None, None, cast(Any, bridge), "proxy_x", anyio.Event()
    )

    [call] = calls
    assert call["user"] == user


async def test_bridge_in_a_scope_refuses_tools_that_cannot_mint_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _BridgeSandbox(tools_version="1.4.0")
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with pytest.raises(SandboxIdentityError, match="needs version 1.5.0"):
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
        "http://127.0.0.1:13131" + path,
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
                [config] = bridge.mcp_server_configs
                assert config.url == "http://127.0.0.1:13131/mcp/tools"
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
                # the service queue the proxy forwards to takes no token, so
                # neither the default user nor the member may write to it
                queue = posixpath.join(
                    SERVICES_DIR,
                    MODEL_SERVICE,
                    posixpath.basename(token_file),
                    REQUESTS_DIR,
                )
                request = json.dumps(
                    {"id": "attack", "method": "generate_completions", "params": {}}
                )
                for attacker in ("nonroot", "w1"):
                    attack = await sb.exec(
                        ["sh", "-c", 'printf %s "$2" > "$1/attack.json"', "sh"]
                        + [queue, request],
                        user=attacker,
                    )
                    assert not attack.success, attacker
                owner = await sb.exec(
                    ["stat", "-c", "%U %a", posixpath.dirname(queue), queue],
                    user="root",
                )
                assert owner.stdout.split("\n")[:2] == ["root 700", "root 700"]
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


@solver
def _planted_token_dir_in_docker() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        for user in ("w1", "w2"):
            created = await sb.exec(["useradd", "-m", user], user="root")
            assert created.success, created.stderr
        # a peer creates the token directory and puts a 64-byte file in it
        # under the bridge's instance name (fixed by the test)
        planted = await sb.exec(
            [
                "sh",
                "-c",
                'mkdir -m 711 "$1" && printf "%064d" 0 > "$1/$2" && chmod 444 "$1/$2"',
                "sh",
                BRIDGE_TOKEN_DIR,
                "proxy_planted",
            ],
            user="w2",
        )
        assert planted.success, planted.stderr
        # the host's wait refuses it, whatever the proxy does
        tools_sandbox = await tools_module.sandbox_with_injected_tools()
        with pytest.raises(FrameworkDirectoryError, match="cannot be trusted"):
            await bridge_module._wait_for_token_file(
                tools_sandbox, f"{BRIDGE_TOKEN_DIR}/proxy_planted", []
            )
        # and the bridge never yields: the host or the proxy refuses first
        yielded = False
        with sandbox_identity("w1", cwd="/home/w1"):
            with pytest.raises(RuntimeError, match="inspect-bridge"):
                async with sandbox_agent_bridge():
                    yielded = True
        assert not yielded
        listing = await sb.exec(["ls", "-A", BRIDGE_TOKEN_DIR], user="root")
        assert listing.stdout.split() == ["proxy_planted"]
        return state

    return solve


@skip_if_no_docker
@pytest.mark.slow
def test_scoped_bridge_in_docker_refuses_a_planted_token_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge_module, "uuid", lambda: "planted")
    task = Task(
        dataset=[Sample(input="x")],
        solver=_planted_token_dir_in_docker(),
        sandbox=("docker", _NONROOT_COMPOSE),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error
