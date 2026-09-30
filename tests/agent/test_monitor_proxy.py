"""Tests for the sandbox agent bridge's monitoring of its model proxy process."""

import contextlib
import json
from collections.abc import Callable, Iterator
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import anyio
import pytest

import inspect_ai.agent._bridge.sandbox.bridge as bridge_module
import inspect_ai.util._sandbox.exec_remote as exec_remote_module
from inspect_ai.agent._bridge.sandbox.bridge import _monitor_proxy, sandbox_agent_bridge
from inspect_ai.util._sandbox.events import SandboxTimeoutError
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
        await _monitor_proxy(proc)  # type: ignore[arg-type]


async def test_monitor_proxy_success() -> None:
    """Proxy exits with exit_code=0 → returns silently, no exception."""
    proc = FakeProcess(
        [
            ExecCompleted(exit_code=0),
        ]
    )

    await _monitor_proxy(proc)  # type: ignore[arg-type]


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
    monkeypatch: pytest.MonkeyPatch, answer_poll: Callable[[float], str]
) -> None:
    """Run `sandbox_agent_bridge` against a sandbox that answers its proxy's RPCs.

    Each poll of the proxy is answered by `answer_poll`, given the poll's exec
    timeout; it returns the JSON-RPC response or raises. The model service is
    replaced by a task that only reports that it started.
    """
    sandbox = AsyncMock()
    sandbox._tools_user = None
    sandbox._tools_default_user = None
    sandbox.no_events = _no_events

    async def exec(*args: Any, **kwargs: Any) -> ExecResult[str]:
        method = json.loads(kwargs["input"])["method"]
        if method == "exec_remote_start":
            stdout = _rpc({"pid": 42})
        elif method == "exec_remote_poll":
            stdout = answer_poll(kwargs["timeout"])
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
