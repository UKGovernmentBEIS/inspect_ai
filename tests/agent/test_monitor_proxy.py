"""Tests for the sandbox agent bridge's monitoring of its model proxy process."""

import contextlib
import json
import traceback
from collections.abc import Awaitable, Callable, Iterator
from typing import Any, AsyncIterator, NoReturn
from unittest.mock import AsyncMock

import anyio
import pytest

import inspect_ai.agent._bridge.sandbox.bridge as bridge_module
import inspect_ai.util._sandbox.exec_remote as exec_remote_module
from inspect_ai._util.constants import (
    DEFAULT_LOG_LEVEL,
)
from inspect_ai.agent._bridge.sandbox.bridge import _monitor_proxy, sandbox_agent_bridge
from inspect_ai.util._sandbox.environment import SandboxTimeoutError
from inspect_ai.util._sandbox.exec_remote import (
    ExecCompleted,
    ExecOutput,
    ExecRemoteProcess,
    ExecRemoteStreamingOptions,
    ExecStderr,
    exec_remote_streaming,
)
from inspect_ai.util._subprocess import ExecResult


class FakeProcess:
    """Minimal async iterator standing in for ExecRemoteProcess."""

    def __init__(self, events: list[ExecOutput]) -> None:
        self._events = iter(events)

    def __aiter__(self) -> AsyncIterator[ExecOutput]:
        return self

    async def __anext__(self) -> ExecOutput:
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration


async def test_monitor_proxy_failure() -> None:
    """Proxy exits with exit_code=1 → raises RuntimeError with 'failure'."""
    proc = FakeProcess(
        [
            ExecStderr(data="something went wrong"),
            ExecCompleted(exit_code=1),
        ]
    )

    with pytest.raises(RuntimeError, match="failure"):
        await _monitor_proxy(proc)


async def test_monitor_proxy_keeps_a_bounded_stderr_tail() -> None:
    """A proxy's stderr is kept as a bounded tail for the error it raises."""
    line = "x" * 1023 + "\n"
    events: list[ExecOutput] = [ExecStderr(data="first output\n")]
    events += [ExecStderr(data=line) for _ in range(256)]
    events += [ExecStderr(data="last output\n"), ExecCompleted(exit_code=1)]
    proc = FakeProcess(events)

    with pytest.raises(RuntimeError, match="failure") as excinfo:
        await _monitor_proxy(proc)

    message = str(excinfo.value)
    assert "last output" in message
    assert "first output" not in message
    assert "[earlier output truncated]" in message
    assert len(message) < bridge_module._PROXY_STDERR_TAIL_CHARS + 200


async def test_monitor_proxy_success() -> None:
    """Proxy exits with exit_code=0 → returns silently, no exception."""
    proc = FakeProcess(
        [
            ExecCompleted(exit_code=0),
        ]
    )

    await _monitor_proxy(proc)


# ============================================================================
# The bridge's polls of its proxy, against a sandbox that answers them
# ============================================================================


def _rpc(result: dict[str, object]) -> str:
    return json.dumps({"jsonrpc": "2.0", "result": result, "id": 1})


def _running_poll() -> str:
    return _rpc(
        {"state": "running", "exit_code": None, "seq": 0, "stdout": "", "stderr": ""}
    )


@contextlib.contextmanager
def _no_events() -> Iterator[None]:
    yield


def _use_proxy_sandbox(
    monkeypatch: pytest.MonkeyPatch,
    answer_poll: Callable[[float], str],
    kill_stderr: str = "",
    before_reply: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    """Run `sandbox_agent_bridge` against a sandbox that answers its proxy's RPCs.

    Each poll of the proxy is answered by `answer_poll`, given the poll's exec
    timeout; it returns the JSON-RPC response or raises. The kill returns
    `kill_stderr` as the proxy's last output. `before_reply`, given the RPC
    method, is awaited before each answer. The model service is replaced by a
    task that only reports that it started.
    """
    sandbox = AsyncMock()
    sandbox._tools_user = None
    sandbox._tools_default_user = None
    sandbox.no_events = _no_events

    async def exec(*args: Any, **kwargs: Any) -> ExecResult[str]:
        method = json.loads(kwargs["input"])["method"]
        if before_reply is not None:
            await before_reply(method)
        if method == "exec_remote_start":
            stdout = _rpc({"pid": 42})
        elif method == "exec_remote_poll":
            stdout = answer_poll(kwargs["timeout"])
        elif method == "exec_remote_kill":
            stdout = _rpc({"seq": 1, "stdout": "", "stderr": kill_stderr})
        else:
            stdout = _rpc({"seq": 0, "stdout": "", "stderr": ""})
        return ExecResult(success=True, returncode=0, stdout=stdout, stderr="")

    async def exec_remote(
        cmd: list[str], options: ExecRemoteStreamingOptions
    ) -> ExecRemoteProcess:
        return await exec_remote_streaming(sandbox, cmd, 5, options)

    sandbox.exec = AsyncMock(side_effect=exec)
    sandbox.exec_remote = exec_remote

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


async def test_proxy_poll_the_sandbox_answers_within_600s_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy poll that takes the sandbox longer than 90s but under 600s still succeeds."""
    answered = anyio.Event()

    def answer_poll(timeout: float) -> str:
        # the sandbox takes 590s to answer, so a shorter exec timeout expires first
        if timeout < 590:
            raise SandboxTimeoutError(f"exec timed out after {timeout}s")
        answered.set()
        return _running_poll()

    _use_proxy_sandbox(monkeypatch, answer_poll)

    with anyio.fail_after(20):
        async with sandbox_agent_bridge():
            await answered.wait()


def _time_out_first_poll(answered: anyio.Event) -> Callable[[float], str]:
    """The sandbox stalls for the first proxy poll, then answers."""
    polls = 0

    def answer_poll(timeout: float) -> str:
        nonlocal polls
        polls += 1
        if polls == 1:
            raise SandboxTimeoutError(f"exec timed out after {timeout}s")
        answered.set()
        return _running_poll()

    return answer_poll


async def test_timed_out_proxy_poll_fails_the_sample_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answered = anyio.Event()
    _use_proxy_sandbox(monkeypatch, _time_out_first_poll(answered))

    with pytest.raises(SandboxTimeoutError):
        with anyio.fail_after(20):
            async with sandbox_agent_bridge():
                await answered.wait()

    assert not answered.is_set()


async def test_bridge_user_can_opt_in_to_proxy_poll_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(exec_remote_module, "POLL_TIMEOUT_RECOVERY_WAIT_SECONDS", 0.0)
    answered = anyio.Event()
    _use_proxy_sandbox(monkeypatch, _time_out_first_poll(answered))

    with anyio.fail_after(20):
        async with sandbox_agent_bridge(poll_timeout_recovery=60):
            await answered.wait()


def _poll_with_stderr(pieces: list[str], sent: anyio.Event) -> Callable[[float], str]:
    """Answer polls with one piece of stderr each, then set `sent` and answer empty."""
    remaining = list(pieces)

    def answer_poll(timeout: float) -> str:
        if not remaining:
            sent.set()
            return _running_poll()
        return _rpc(
            {
                "state": "running",
                "exit_code": None,
                "seq": 0,
                "stdout": "",
                "stderr": remaining.pop(0),
            }
        )

    return answer_poll


def _bridge_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == bridge_module.__name__]


async def test_proxy_stderr_is_a_warning_first_and_when_the_bridge_stops(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Proxy stderr is a warning when it first arrives and once more at the end."""
    caplog.set_level(DEFAULT_LOG_LEVEL.upper())
    sent = anyio.Event()
    pieces = ["failure 1\n", "failure 2\n", "failure 3\n"]
    _use_proxy_sandbox(
        monkeypatch,
        _poll_with_stderr(pieces, sent),
        kill_stderr="failure at stop\n",
    )

    with anyio.fail_after(20):
        async with sandbox_agent_bridge():
            await sent.wait()

    first, at_stop = _bridge_warnings(caplog)
    assert "failure 1" in first
    assert "failure 2" not in first
    assert "failure 3" in at_stop
    assert "failure at stop" in at_stop


async def test_proxy_stderr_warnings_are_bounded(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """However much stderr the proxy writes, its warnings stay bounded."""
    caplog.set_level(DEFAULT_LOG_LEVEL.upper())
    sent = anyio.Event()
    first_piece = "x" * bridge_module._PROXY_STDERR_WARNING_CHARS + "\nfirst failure\n"
    pieces = [first_piece] + ["y" * 1023 + "\n"] * 256
    _use_proxy_sandbox(
        monkeypatch, _poll_with_stderr(pieces, sent), kill_stderr="last failure\n"
    )

    with anyio.fail_after(20):
        async with sandbox_agent_bridge():
            await sent.wait()

    first, at_stop = _bridge_warnings(caplog)
    assert "first failure" in first
    assert "[earlier output truncated]" in first
    assert len(first) < bridge_module._PROXY_STDERR_WARNING_CHARS + 200
    assert "last failure" in at_stop
    assert "[earlier output truncated]" in at_stop
    assert len(at_stop) < bridge_module._PROXY_STDERR_TAIL_CHARS + 200


async def test_proxy_stderr_returned_by_the_kill_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Stderr written after the last poll is logged when the bridge stops."""
    caplog.set_level(DEFAULT_LOG_LEVEL.upper())
    polled = anyio.Event()

    def answer_poll(timeout: float) -> str:
        polled.set()
        return _running_poll()

    _use_proxy_sandbox(
        monkeypatch,
        answer_poll,
        kill_stderr="OSError: [Errno 28] No space left on device\n",
    )

    with anyio.fail_after(20):
        async with sandbox_agent_bridge():
            await polled.wait()

    assert "No space left on device" in caplog.text


@pytest.mark.parametrize("poll_answers_first", [True, False])
async def test_proxy_stderr_returned_by_a_kill_during_a_poll_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    poll_answers_first: bool,
) -> None:
    """The kill's stderr is logged whether a poll in flight answers before it or not."""
    caplog.set_level(DEFAULT_LOG_LEVEL.upper())
    polling, killing = anyio.Event(), anyio.Event()
    answer_poll, answer_kill = anyio.Event(), anyio.Event()
    monitor_returned = anyio.Event()

    async def before_reply(method: str) -> None:
        if method == "exec_remote_poll":
            polling.set()
            await answer_poll.wait()
        elif method == "exec_remote_kill":
            killing.set()
            await answer_kill.wait()

    monitor = bridge_module._monitor_proxy

    async def monitor_then_report(*args: Any) -> None:
        await monitor(*args)
        monitor_returned.set()

    monkeypatch.setattr(bridge_module, "_monitor_proxy", monitor_then_report)
    _use_proxy_sandbox(
        monkeypatch,
        lambda timeout: _running_poll(),
        kill_stderr="OSError: [Errno 28] No space left on device\n",
        before_reply=before_reply,
    )

    async def answer_in_order() -> None:
        await killing.wait()
        if poll_answers_first:
            # the poll's empty answer ends the monitor, the kill being pending
            answer_poll.set()
            await monitor_returned.wait()
        answer_kill.set()

    with anyio.fail_after(20):
        async with anyio.create_task_group() as tg:
            tg.start_soon(answer_in_order)
            async with sandbox_agent_bridge():
                await polling.wait()

    assert "No space left on device" in caplog.text


def _raise_wrapped() -> NoReturn:
    raise RuntimeError("wrapped")


async def test_bridge_error_keeps_its_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error raised in the bridge's body keeps its own context."""
    _use_proxy_sandbox(monkeypatch, lambda timeout: _running_poll())

    with pytest.raises(RuntimeError, match="wrapped") as excinfo:
        with anyio.fail_after(20):
            async with sandbox_agent_bridge():
                try:
                    raise ValueError("context")
                except ValueError:
                    _raise_wrapped()
    error = excinfo.value
    assert repr(error.__context__) == "ValueError('context')"
    assert not error.__suppress_context__
    text = "".join(traceback.format_exception(error))
    assert "Exception Group Traceback" not in text
    assert text.count("RuntimeError: wrapped") == 1
