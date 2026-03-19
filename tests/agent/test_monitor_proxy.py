"""Tests for _monitor_proxy proxy death detection."""

import contextlib
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest

from inspect_ai.agent._bridge.sandbox.bridge import _monitor_proxy
from inspect_ai.util._sandbox.exec_remote import (
    exec_remote_streaming,
)
from inspect_ai.util._subprocess import ExecResult

# ============================================================================
# Helpers (same patterns as tests/util/sandbox/test_exec_remote.py)
# ============================================================================


@contextlib.contextmanager
def _no_events_context() -> Iterator[None]:
    yield


def _rpc(result: dict[str, Any], id: int = 1) -> str:
    return json.dumps({"jsonrpc": "2.0", "result": result, "id": id})


def _start_response(pid: int = 42) -> str:
    return _rpc({"pid": pid})


def _poll_response(
    state: str = "completed",
    exit_code: int | None = 0,
    stdout: str = "",
    stderr: str = "",
) -> str:
    return _rpc(
        {"state": state, "exit_code": exit_code, "stdout": stdout, "stderr": stderr}
    )


def _make_sandbox_mock(responses: list[str]) -> AsyncMock:
    sandbox = AsyncMock()
    sandbox.default_polling_interval.return_value = 5
    sandbox.no_events = _no_events_context

    response_iter = iter(responses)

    async def fake_exec(*args: Any, **kwargs: Any) -> ExecResult[str]:
        try:
            stdout = next(response_iter)
        except StopIteration:
            raise RuntimeError("Mock sandbox ran out of canned responses")
        return ExecResult(success=True, returncode=0, stdout=stdout, stderr="")

    sandbox.exec = AsyncMock(side_effect=fake_exec)
    return sandbox


# ============================================================================
# Tests
# ============================================================================


async def test_monitor_proxy_failure() -> None:
    """Proxy exits with exit_code=1 → raises RuntimeError with 'failure'."""
    sandbox = _make_sandbox_mock(
        [
            _start_response(),
            _poll_response(exit_code=1, stderr="something went wrong"),
        ]
    )

    proc = await exec_remote_streaming(sandbox, ["proxy"], 5)

    with pytest.raises(RuntimeError, match="failure"):
        await _monitor_proxy(proc)


async def test_monitor_proxy_stream_ends() -> None:
    """Stream ends without ExecCompleted (killed) → raises RuntimeError."""
    sandbox = _make_sandbox_mock(
        [
            _start_response(),
            _poll_response(state="killed", exit_code=None, stderr="killed output"),
        ]
    )

    proc = await exec_remote_streaming(sandbox, ["proxy"], 5)

    with pytest.raises(RuntimeError, match="stream ended"):
        await _monitor_proxy(proc)


async def test_monitor_proxy_success() -> None:
    """Proxy exits with exit_code=0 → returns silently, no exception."""
    sandbox = _make_sandbox_mock(
        [
            _start_response(),
            _poll_response(exit_code=0),
        ]
    )

    proc = await exec_remote_streaming(sandbox, ["proxy"], 5)

    # Should not raise
    await _monitor_proxy(proc)
