"""The sandbox agent bridge's peer check inside a sandbox identity scope."""

import json
import posixpath
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

import anyio
import pytest
from test_helpers.sandbox import CannedSandbox
from test_helpers.utils import skip_if_no_docker

import inspect_ai.agent._bridge.sandbox.bridge as bridge_module
import inspect_ai.agent._bridge.sandbox.service as service_module
import inspect_ai.tool._sandbox_tools_utils.sandbox as tools_module
import inspect_ai.util._sandbox.environment as environment_module
from inspect_ai import Task, eval
from inspect_ai.agent._bridge.sandbox.bridge import sandbox_agent_bridge
from inspect_ai.agent._bridge.sandbox.service import MODEL_SERVICE
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._transcript import transcript
from inspect_ai.model import get_model
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool._mcp._tools_bridge import BridgedToolsSpec
from inspect_ai.tool._tool import Tool, tool
from inspect_ai.util import SandboxEnvironment, sandbox
from inspect_ai.util._sandbox._cli import SANDBOX_TOOLS_DIR
from inspect_ai.util._sandbox._framework_directory import _VERIFIED_MARKER
from inspect_ai.util._sandbox._privileged import SHELL_PATH
from inspect_ai.util._sandbox.context import (
    sandbox_default_context_var,
    sandbox_environments_context_var,
)
from inspect_ai.util._sandbox.exec_remote import (
    ExecCompleted,
    ExecOutput,
    ExecRemoteStreamingOptions,
    ExecStderr,
    ExecStdout,
)
from inspect_ai.util._sandbox.identity import SandboxIdentityError, sandbox_identity
from inspect_ai.util._sandbox.service import REQUESTS_DIR, SERVICES_DIR
from inspect_ai.util._subprocess import ExecResult

PEER_USER_ENV = "BRIDGE_MODEL_SERVICE_PEER_USER"
LISTENING = "model_proxy: listening on 127.0.0.1:13131 and [::1]:13131 for uid 1001\n"

Listen = Literal["now", "late", "split", "never"]


class _FakeProxy:
    """The proxy process: prints its listening line as told, runs until killed."""

    def __init__(self, listen: Listen, exit_code: int | None) -> None:
        self.listen = listen
        self.exit_code = exit_code
        self.printed = False
        self.killed = anyio.Event()

    def __aiter__(self) -> AsyncIterator[ExecOutput]:
        return self._events()

    async def _events(self) -> AsyncIterator[ExecOutput]:
        yield ExecStdout(data="starting\n")
        if self.exit_code is not None:
            yield ExecStderr(data="model_proxy: cannot listen on [::1]:13131\n")
            yield ExecCompleted(exit_code=self.exit_code)
            return
        if self.listen == "late":
            await anyio.sleep(0.3)
        if self.listen == "split":
            yield ExecStdout(data=LISTENING[:20])
            await anyio.sleep(0.1)
            self.printed = True
            yield ExecStdout(data=LISTENING[20:] + "2026 - request handled\n")
        elif self.listen != "never":
            self.printed = True
            yield ExecStdout(data=LISTENING)
        await self.killed.wait()

    async def kill(self) -> None:
        self.killed.set()


class _BridgeSandbox(CannedSandbox):
    """A sandbox with the tools installed and a proxy started as told."""

    def __init__(
        self,
        *,
        tools_version: str = "1.5.0",
        listen: Listen = "now",
        exit_code: int | None = None,
    ) -> None:
        super().__init__(self._answer)
        self._tools_user = "root"
        self.tools_version = tools_version
        self.proxy = _FakeProxy(listen, exit_code)
        self.launches: list[ExecRemoteStreamingOptions] = []
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
            # regression fails rather than hangs
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
        if cmd[:2] == [SHELL_PATH, "-c"] and _VERIFIED_MARKER in cmd[2]:
            # the installed launcher, a regular file in the tools directory
            assert posixpath.join(cmd[8], cmd[9]) == SANDBOX_TOOLS_DIR
            return ExecResult(True, 0, "81ed\n", f"{_VERIFIED_MARKER}\n")
        if "CapEff" in cmd[2]:  # the root probe
            status = "Uid: 0 0 0 0\nCapEff: 000001ffffffffff\nsetgroups: allow\n"
            return ExecResult(True, 0, status, "")
        if "HOME_SET" in cmd[2]:  # the default user
            status = "Uid: 1000\nGid: 1000\nGroups: 1000\nHOME: /home/u\nHOME_SET: 1\n"
            return ExecResult(True, 0, status, "")
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
    async def sandbox_with_injected_tools(**kwargs: Any) -> Any:
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


@pytest.mark.parametrize("listen", ["now", "late", "split"])
async def test_bridge_in_a_scope_yields_once_its_proxy_listens(
    monkeypatch: pytest.MonkeyPatch, listen: Listen
) -> None:
    sandbox = _BridgeSandbox(listen=listen)
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(20):
            async with sandbox_agent_bridge(
                bridged_tools=[BridgedToolsSpec(name="tools", tools=[_echo()])]
            ) as bridge:
                assert sandbox.proxy.printed

    [launch] = sandbox.launches
    assert launch.user == "root"
    assert launch.concurrency is False
    assert launch.env is not None
    assert launch.env[PEER_USER_ENV] == "w-1"
    # the scope's user is all the proxy is given beyond an unscoped launch
    assert set(launch.env) == {
        "BRIDGE_MODEL_SERVICE_PORT",
        "BRIDGE_MODEL_SERVICE_INSTANCE",
        PEER_USER_ENV,
    }
    [config] = bridge.mcp_server_configs
    assert config.url == f"http://localhost:{bridge.port}/mcp/tools"
    assert config.headers is None
    assert sandbox.proxy.killed.is_set()


async def test_bridge_outside_a_scope_passes_no_user_and_does_not_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _BridgeSandbox(listen="never")
    with _sandbox(monkeypatch, sandbox):
        with anyio.fail_after(20):
            async with sandbox_agent_bridge(
                bridged_tools=[BridgedToolsSpec(name="tools", tools=[_echo()])]
            ) as bridge:
                pass

    [launch] = sandbox.launches
    assert launch.env is not None
    assert set(launch.env) == {
        "BRIDGE_MODEL_SERVICE_PORT",
        "BRIDGE_MODEL_SERVICE_INSTANCE",
    }
    [config] = bridge.mcp_server_configs
    assert config.url == f"http://localhost:{bridge.port}/mcp/tools"
    assert config.headers is None
    # no version check
    assert sandbox.exec_calls == []


async def test_bridge_raises_when_the_proxy_never_reports_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge_module, "BRIDGE_LISTEN_TIMEOUT", 0.5)
    sandbox = _BridgeSandbox(listen="never")
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with pytest.raises(RuntimeError, match="did not report listening within 0.5"):
            with anyio.fail_after(20):
                async with sandbox_agent_bridge():
                    raise AssertionError("bridge yielded")

    assert sandbox.proxy.killed.is_set()


@pytest.mark.parametrize("exit_code", [0, 1])
async def test_bridge_raises_with_stderr_when_the_proxy_exits_first(
    monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    sandbox = _BridgeSandbox(exit_code=exit_code)
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with pytest.raises(RuntimeError, match=r"cannot listen on \[::1\]:13131"):
            with anyio.fail_after(20):
                async with sandbox_agent_bridge():
                    raise AssertionError("bridge yielded")


async def test_cancellation_ends_the_wait_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _BridgeSandbox(listen="never")
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(5):
            with anyio.move_on_after(0.5) as scope:
                async with sandbox_agent_bridge():
                    raise AssertionError("bridge yielded")

    assert scope.cancelled_caught
    assert sandbox.proxy.killed.is_set()


async def test_bridge_in_a_scope_refuses_tools_without_the_peer_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _BridgeSandbox(tools_version="1.4.1")
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with pytest.raises(SandboxIdentityError, match="needs version 1.5.0"):
            async with sandbox_agent_bridge():
                raise AssertionError("bridge yielded")

    assert sandbox.launches == []


async def test_scoped_bridge_control_does_not_wait_for_sandbox_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bridge starts while other commands hold the capacity.

    Its version check and the proxy launch run outside the limits.
    """
    sandbox = _BridgeSandbox()
    sandbox.saturated = True
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        with anyio.fail_after(10):
            async with sandbox_agent_bridge():
                pass

    assert sandbox.concurrency == [False]
    assert sandbox.proxy.killed.is_set()


async def test_bridge_verifies_the_sandbox_tools_without_waiting_for_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bridge's own tools check bypasses capacity, as its other commands do.

    The real check runs on a sandbox with no recorded tools user or root
    access, so it probes root, checks the installation and reads the default
    user, while other commands hold the capacity.
    """
    sandbox = _BridgeSandbox()
    sandbox._tools_user = None
    sandbox.saturated = True
    with _sandbox(monkeypatch, sandbox), sandbox_identity("w-1"):
        monkeypatch.setattr(
            bridge_module,
            "sandbox_with_injected_tools",
            tools_module.sandbox_with_injected_tools,
        )
        with anyio.fail_after(10):
            async with sandbox_agent_bridge():
                pass

    assert sandbox._tools_user == "root"
    assert sandbox._root_access is not None
    assert sandbox._root_access.state == "usable"
    assert sandbox._tools_default_user is not None
    assert sandbox.launches and sandbox.proxy.killed.is_set()
    assert not any(sandbox.concurrency)


async def test_proxy_launch_does_not_check_tools_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public exec_remote() launches the proxy while the capacity is held.

    The bridge has already checked the sandbox's tools, so a second check,
    which would wait for capacity, must not run at launch.
    """
    sandbox = _BridgeSandbox()
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
                pass

    assert tools_checks == []
    [launch] = launches
    assert launch.concurrency is False
    assert sandbox.proxy.killed.is_set()


@pytest.mark.parametrize("tools_user", ["root", None])
async def test_every_bridge_gives_its_service_queue_to_the_tools_user(
    monkeypatch: pytest.MonkeyPatch, tools_user: str | None
) -> None:
    """Otherwise another user could submit requests past the proxy's check."""
    calls: list[dict[str, Any]] = []

    async def sandbox_service(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(service_module, "sandbox_service", sandbox_service)
    sandbox = _BridgeSandbox()
    sandbox._tools_user = tools_user
    await service_module.run_model_service(
        sandbox, None, None, cast(Any, SimpleNamespace()), "proxy_x", anyio.Event()
    )

    [call] = calls
    assert call["user"] == tools_user


# ============================================================================
# End to end, with the injected tools in Docker
# ============================================================================

_TOOLS_DIR = Path(__file__).parent.parent / "tools"
_NONROOT_COMPOSE = str(_TOOLS_DIR / "test_sandbox_compose.yaml")
_NO_IPV6_COMPOSE = str(Path(__file__).parent / "compose.bridge-no-ipv6.yaml")

_CLIENT = r"""
import errno, json, socket, sys, time

def post(host, port, path, family, content, retry=False):
    if path.startswith("/mcp/"):
        body = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    else:
        body = {"model": "inspect", "messages": [{"role": "user", "content": content}]}
    data = json.dumps(body).encode()
    request = (
        f"POST {path} HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(data)}\r\n\r\n"
    ).encode() + data
    for attempt in range(100 if retry else 1):
        try:
            if family == "any":
                sock = socket.create_connection((host, port), timeout=30)
            else:
                sock = socket.socket(socket.AF_INET6 if family == "6" else socket.AF_INET)
                sock.settimeout(30)
                sock.connect((host, port))
            break
        except OSError as ex:
            error = {"error": errno.errorcode[ex.errno]}
            time.sleep(0.1)
    else:
        return error
    with sock:
        sock.sendall(request)
        response = b""
        while chunk := sock.recv(65536):
            response += chunk
    head, _, body = response.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    message = json.loads(body)["error"]["message"] if status == 403 else None
    return {"status": status, "message": message}

def bind(host, port, reuseport):
    sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
    with sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if reuseport:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        try:
            sock.bind((host, port))
            sock.listen()
            return "bound"
        except OSError as ex:
            return errno.errorcode[ex.errno]

results = []
for action in json.loads(sys.argv[1]):
    if action[0] == "post":
        results.append(post(*action[1:]))
    else:
        results.append(bind(*action[1:]))
print(json.dumps(results))
"""

_LISTENER = r"""
import socket, sys, time
host, port, reuseport = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1"
sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
if reuseport:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
sock.bind((host, port))
sock.listen()
open("/tmp/listener-" + sys.argv[4], "w").close()
sock.settimeout(60)
try:
    sock.accept()
    open("/tmp/listener-accepted-" + sys.argv[4], "w").close()
except OSError:
    pass
"""

_RETIRED_CLIENT = r"""
import json, socket, struct, sys, os
host, port, local_port, content, mode = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
family = socket.AF_INET6 if ":" in host else socket.AF_INET
body = json.dumps({"model": "inspect", "messages": [{"role": "user", "content": content}]}).encode()
request = (
    f"POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n"
    f"Content-Length: {len(body)}\r\n\r\n"
).encode() + body
sock = socket.socket(family)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((host, local_port))
sock.connect((host, port))
sock.sendall(request)
if mode == "reset":
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    sock.close()
else:
    open(f"/tmp/{content}.sent", "w").close()
    sock.settimeout(60)
    response = b""
    while chunk := sock.recv(65536):
        response += chunk
    with open(f"/tmp/{content}.json.tmp", "w") as file:
        file.write(response.split(b" ", 2)[1].decode())
    os.rename(f"/tmp/{content}.json.tmp", f"/tmp/{content}.json")
"""


async def _client(user: str, actions: list[list[Any]]) -> list[Any]:
    result = await sandbox().exec(
        ["python3", "-c", _CLIENT, json.dumps(actions)], user=user
    )
    assert result.success, result.stderr
    return cast(list[Any], json.loads(result.stdout))


async def _wait_for_file(path: str) -> None:
    with anyio.fail_after(30):
        while not (await sandbox().exec(["test", "-e", path], user="root")).success:
            await anyio.sleep(0.2)


def _served_only(user: str, uid: str, owner: str) -> str:
    return (
        f"This model proxy serves only user '{user}' (uid {uid}); this "
        f"connection's socket belongs to uid {owner}."
    )


async def _uid(user: str) -> str:
    result = await sandbox().exec(["id", "-u", user])
    return result.stdout.strip()


@solver
def _bridges_in_docker() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        for user in ("w1", "w2"):
            created = await sb.exec(["useradd", "-m", user], user="root")
            assert created.success, created.stderr
        w1, w2 = await _uid("w1"), await _uid("w2")
        chat = "/v1/chat/completions"

        # an unscoped bridge serves anyone, on 127.0.0.1 only
        async with sandbox_agent_bridge(port=13131):
            assert await _client(
                "w2",
                [
                    # this bridge yields before its proxy listens
                    ["post", "127.0.0.1", 13131, chat, "4", "x", True],
                    ["post", "::1", 13131, chat, "6", "x"],
                ],
            ) == [{"status": 200, "message": None}, {"error": "ECONNREFUSED"}]

        # a scoped bridge, started after it, serves only its user
        with sandbox_identity("w1", cwd="/home/w1"):
            async with sandbox_agent_bridge(
                port=13132,
                bridged_tools=[BridgedToolsSpec(name="tools", tools=[_echo()])],
            ) as bridge:
                [config] = bridge.mcp_server_configs
                assert config.url == "http://localhost:13132/mcp/tools"
                requests = [
                    ["post", host, 13132, path, family, "x"]
                    for host, family in [("127.0.0.1", "4"), ("::1", "6")]
                    for path in (chat, "/mcp/tools")
                ]
                served = {"status": 200, "message": None}
                assert (
                    await _client(
                        "w1",
                        requests + [["post", "localhost", 13132, chat, "any", "x"]],
                    )
                    == [served] * 5
                )
                for other, uid in [("w2", w2), ("root", "0")]:
                    refused = {"status": 403, "message": _served_only("w1", w1, uid)}
                    assert await _client(other, requests) == [refused] * 4
                # an IPv6 socket reaching the IPv4 listener is in the other table
                [mapped] = await _client(
                    "w1", [["post", "::ffff:127.0.0.1", 13132, chat, "6", "x"]]
                )
                assert mapped["status"] == 403
                assert "no single socket in /proc/net/tcp matched" in mapped["message"]
                # no one else can listen where `localhost` leads
                binds = [
                    ["bind", host, 13132, reuseport]
                    for host in ("::1", "127.0.0.1", "::", "0.0.0.0")
                    for reuseport in (False, True)
                ]
                assert await _client("w2", binds) == ["EADDRINUSE"] * 8
                # nor submit requests to the service queue behind the proxy
                queues = await sb.exec(
                    ["find", posixpath.join(SERVICES_DIR, MODEL_SERVICE)]
                    + ["-mindepth", "2", "-maxdepth", "2", "-name", REQUESTS_DIR],
                    user="root",
                )
                # (every bridge's queue so far, this one's included)
                for queue in queues.stdout.split():
                    for attacker in ("nonroot", "w1", "w2"):
                        attack = await sb.exec(
                            ["sh", "-c", 'printf x > "$1/attack.json"', "sh", queue],
                            user=attacker,
                        )
                        assert not attack.success, attacker
                    owner = await sb.exec(
                        ["stat", "-c", "%U %a", posixpath.dirname(queue), queue],
                        user="root",
                    )
                    assert owner.stdout.split("\n")[:2] == ["root 700", "root 700"]

        # and an unscoped bridge started after a scoped one shares its queue's parent
        async with sandbox_agent_bridge(port=13133):
            assert await _client(
                "w2", [["post", "127.0.0.1", 13133, chat, "4", "x", True]]
            ) == [{"status": 200, "message": None}]
        return state

    return solve


@skip_if_no_docker
@pytest.mark.slow
def test_scoped_bridge_in_docker_serves_only_its_user() -> None:
    task = Task(
        dataset=[Sample(input="x")],
        solver=_bridges_in_docker(),
        sandbox=("docker", _NONROOT_COMPOSE),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error


@solver
def _peer_holding_the_port_in_docker() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        for user in ("w1", "w2"):
            created = await sb.exec(["useradd", "-m", user], user="root")
            assert created.success, created.stderr
        cases = [("::1", 13141, "0"), ("127.0.0.1", 13142, "1")]
        for host, port, reuseport in cases:
            name = str(port)
            started = await sb.exec(
                [
                    "sh",
                    "-c",
                    'python3 -c "$1" "$2" "$3" "$4" "$5" >/dev/null 2>&1 &',
                    "sh",
                    _LISTENER,
                    host,
                    str(port),
                    reuseport,
                    name,
                ],
                user="w2",
            )
            assert started.success, started.stderr
            await _wait_for_file(f"/tmp/listener-{name}")
            display = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
            with sandbox_identity("w1", cwd="/home/w1"):
                with pytest.raises(
                    RuntimeError,
                    match=re.escape(f"cannot listen on {display}: Address"),
                ):
                    async with sandbox_agent_bridge(port=port):
                        raise AssertionError("bridge yielded")
            accepted = await sb.exec(["test", "-e", f"/tmp/listener-accepted-{name}"])
            assert not accepted.success
        return state

    return solve


@skip_if_no_docker
@pytest.mark.slow
def test_scoped_bridge_in_docker_fails_when_a_peer_holds_its_port() -> None:
    task = Task(
        dataset=[Sample(input="x")],
        solver=_peer_holding_the_port_in_docker(),
        sandbox=("docker", _NONROOT_COMPOSE),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error


@solver
def _retired_connection_in_docker() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        for user in ("w1", "w2"):
            created = await sb.exec(["useradd", "-m", user], user="root")
            assert created.success, created.stderr
        proxy = "inspect-sandbox-tools model_proxy$"
        with sandbox_identity("w1", cwd="/home/w1"):
            async with sandbox_agent_bridge(port=13151):
                for host, local_port in [("127.0.0.1", 45001), ("::1", 45002)]:
                    tag = f"w1-{local_port}"
                    stopped = await sb.exec(
                        ["pkill", "-STOP", "-f", proxy], user="root"
                    )
                    assert stopped.success, stopped.stderr
                    # w2 sends a request from a fixed port and resets the connection
                    args = [host, "13151", str(local_port)]
                    reset = await sb.exec(
                        [
                            "python3",
                            "-c",
                            _RETIRED_CLIENT,
                            *args,
                            f"w2-{local_port}",
                            "reset",
                        ],
                        user="w2",
                    )
                    assert reset.success, reset.stderr
                    # w1 connects from the same port before the proxy accepts
                    sent = await sb.exec(
                        [
                            "sh",
                            "-c",
                            'python3 -c "$1" "$2" "$3" "$4" "$5" "$6" >/dev/null 2>&1 &',
                            "sh",
                            _RETIRED_CLIENT,
                            *args,
                            tag,
                            "wait",
                        ],
                        user="w1",
                    )
                    assert sent.success, sent.stderr
                    await _wait_for_file(f"/tmp/{tag}.sent")
                    continued = await sb.exec(
                        ["pkill", "-CONT", "-f", proxy], user="root"
                    )
                    assert continued.success, continued.stderr
                    await _wait_for_file(f"/tmp/{tag}.json")
                    status = await sb.exec(["cat", f"/tmp/{tag}.json"], user="root")
                    assert status.stdout == "200"
        inputs = [
            str(event.input)
            for event in transcript().events
            if isinstance(event, ModelEvent)
        ]
        for local_port in (45001, 45002):
            assert any(f"w1-{local_port}" in text for text in inputs)
            assert not any(f"w2-{local_port}" in text for text in inputs)
        return state

    return solve


@skip_if_no_docker
@pytest.mark.slow
def test_scoped_bridge_in_docker_does_not_serve_a_retired_connection() -> None:
    task = Task(
        dataset=[Sample(input="x")],
        solver=_retired_connection_in_docker(),
        sandbox=("docker", _NONROOT_COMPOSE),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error


@solver
def _ipv4_only_bridge_in_docker() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        for user in ("w1", "w2"):
            created = await sb.exec(["useradd", "-m", user], user="root")
            assert created.success, created.stderr
        chat = "/v1/chat/completions"
        with sandbox_identity("w1", cwd="/home/w1"):
            async with sandbox_agent_bridge(port=13161):
                assert (
                    await _client(
                        "w1",
                        [
                            ["post", "localhost", 13161, chat, "any", "x"],
                            ["post", "127.0.0.1", 13161, chat, "4", "x"],
                        ],
                    )
                    == [{"status": 200, "message": None}] * 2
                )
                [refused] = await _client(
                    "w2", [["post", "127.0.0.1", 13161, chat, "4", "x"]]
                )
                assert refused["status"] == 403
        return state

    return solve


@skip_if_no_docker
@pytest.mark.slow
def test_scoped_bridge_in_docker_without_an_ipv6_loopback() -> None:
    task = Task(
        dataset=[Sample(input="x")],
        solver=_ipv4_only_bridge_in_docker(),
        sandbox=("docker", _NO_IPV6_COMPOSE),
    )
    log = eval(task, model=get_model("mockllm/model"))[0]
    assert log.status == "success", log.error
