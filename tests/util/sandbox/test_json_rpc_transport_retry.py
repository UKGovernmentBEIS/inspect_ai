"""Tests for SandboxJSONRPCTransport retry logic.

Verifies that the transport retries transient sandbox.exec failures
(non-zero exit codes and raised exceptions) without affecting the
MCP server running inside the container.
"""

from __future__ import annotations

from typing import Any, NamedTuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from inspect_ai.util import ExecResult
from inspect_ai.util._sandbox._json_rpc_transport import (
    _MAX_RETRIES,
    SandboxJSONRPCTransport,
)


def _make_exec_result(
    success: bool, stdout: str = "", stderr: str = "", returncode: int = 0
) -> ExecResult[str]:
    return ExecResult(
        success=success, returncode=returncode, stdout=stdout, stderr=stderr
    )


class _TransportFixture(NamedTuple):
    transport: SandboxJSONRPCTransport
    exec_mock: AsyncMock


def _make_transport(side_effects: list[Any]) -> _TransportFixture:
    """Create a transport with a mocked sandbox.exec."""
    sandbox = MagicMock()
    exec_mock = AsyncMock(side_effect=side_effects)
    sandbox.exec = exec_mock
    return _TransportFixture(
        transport=SandboxJSONRPCTransport(sandbox=sandbox, cli="/usr/bin/sandbox-cli"),
        exec_mock=exec_mock,
    )


class TestSandboxJSONRPCTransportRetry:
    async def test_success_on_first_attempt(self) -> None:
        """Successful exec on first try returns stdout immediately."""
        transport, exec_mock = _make_transport(
            [
                _make_exec_result(
                    success=True, stdout='{"jsonrpc":"2.0","id":1,"result":42}'
                ),
            ]
        )
        result = await transport("test_method", {"key": "val"}, is_notification=False)
        assert '"result":42' in result
        assert exec_mock.call_count == 1

    async def test_retry_on_exec_failure_then_succeed(self) -> None:
        """Non-zero exit code on first attempt, success on second."""
        transport, exec_mock = _make_transport(
            [
                _make_exec_result(success=False, stderr="container busy", returncode=1),
                _make_exec_result(
                    success=True, stdout='{"jsonrpc":"2.0","id":1,"result":"ok"}'
                ),
            ]
        )
        result = await transport("test_method", None, is_notification=False)
        assert '"result":"ok"' in result
        assert exec_mock.call_count == 2

    async def test_retry_on_exception_then_succeed(self) -> None:
        """sandbox.exec raises an exception, then succeeds on retry."""
        transport, exec_mock = _make_transport(
            [
                OSError("connection refused"),
                _make_exec_result(
                    success=True, stdout='{"jsonrpc":"2.0","id":1,"result":"ok"}'
                ),
            ]
        )
        result = await transport("test_method", None, is_notification=False)
        assert '"result":"ok"' in result
        assert exec_mock.call_count == 2

    async def test_exhaust_all_retries(self) -> None:
        """All attempts fail — raises the last error."""
        transport, exec_mock = _make_transport(
            [
                _make_exec_result(success=False, stderr="fail 1", returncode=1),
                _make_exec_result(success=False, stderr="fail 2", returncode=1),
                _make_exec_result(success=False, stderr="fail 3", returncode=1),
            ]
        )
        with pytest.raises(RuntimeError, match="fail 3"):
            await transport("test_method", None, is_notification=False)
        assert exec_mock.call_count == _MAX_RETRIES + 1

    async def test_exhaust_retries_on_exception(self) -> None:
        """All attempts raise exceptions — re-raises the last one."""
        transport, exec_mock = _make_transport(
            [
                OSError("fail 1"),
                ConnectionError("fail 2"),
                OSError("fail 3"),
            ]
        )
        with pytest.raises(OSError, match="fail 3"):
            await transport("test_method", None, is_notification=False)
        assert exec_mock.call_count == _MAX_RETRIES + 1

    async def test_timeout_not_retried(self) -> None:
        """TimeoutError should propagate immediately without retry."""
        transport, exec_mock = _make_transport(
            [
                TimeoutError("timed out"),
            ]
        )
        with pytest.raises(TimeoutError, match="timed out"):
            await transport("test_method", None, is_notification=False)
        # Should NOT have retried
        assert exec_mock.call_count == 1

    async def test_mixed_failure_then_success(self) -> None:
        """Exception, then non-zero exit, then success on third attempt."""
        transport, exec_mock = _make_transport(
            [
                ConnectionError("network blip"),
                _make_exec_result(
                    success=False, stderr="temporary issue", returncode=1
                ),
                _make_exec_result(
                    success=True, stdout='{"jsonrpc":"2.0","id":1,"result":"ok"}'
                ),
            ]
        )
        result = await transport("test_method", None, is_notification=False)
        assert '"result":"ok"' in result
        assert exec_mock.call_count == 3

    async def test_notification_retries_on_failure(self) -> None:
        """Notifications (no response expected) also retry on failure."""
        transport, exec_mock = _make_transport(
            [
                _make_exec_result(success=False, stderr="busy", returncode=1),
                _make_exec_result(success=True, stdout=""),
            ]
        )
        result = await transport("notify_method", None, is_notification=True)
        assert result == ""
        assert exec_mock.call_count == 2
