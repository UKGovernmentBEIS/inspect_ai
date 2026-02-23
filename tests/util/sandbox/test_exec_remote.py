"""Tests for host-side exec_remote implementation.

These tests mock the sandbox's exec() method to test the host-side polling loop,
event assembly, kill behavior, and awaitable mode without needing a real sandbox.
"""

import asyncio
import contextlib
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from inspect_ai.util._sandbox.exec_remote import (
    ExecRemoteAwaitableOptions,
    ExecRemoteCommonOptions,
    ExecRemoteEvent,
    ExecRemoteProcess,
    ExecRemoteStreamingOptions,
    exec_remote_awaitable,
    exec_remote_streaming,
)
from inspect_ai.util._subprocess import ExecResult

# ============================================================================
# Helpers
# ============================================================================


def _rpc(result: dict[str, Any], id: int = 1) -> str:
    """Create a JSON-RPC success response string."""
    return json.dumps({"jsonrpc": "2.0", "result": result, "id": id})


def _start_response(pid: int = 42) -> str:
    """Create a JSON-RPC start response with the given PID."""
    return _rpc({"pid": pid})


def _poll_response(
    state: str = "completed",
    exit_code: int | None = 0,
    stdout: str = "",
    stderr: str = "",
) -> str:
    """Create a JSON-RPC poll response."""
    return _rpc(
        {"state": state, "exit_code": exit_code, "stdout": stdout, "stderr": stderr}
    )


def _kill_response(stdout: str = "", stderr: str = "") -> str:
    """Create a JSON-RPC kill response."""
    return _rpc({"stdout": stdout, "stderr": stderr})


@contextlib.contextmanager
def _no_events_context() -> Iterator[None]:
    """A no-op context manager to stand in for SandboxEnvironmentProxy.no_events()."""
    yield


def _make_sandbox_mock(responses: list[str]) -> AsyncMock:
    """Create a mock SandboxEnvironment whose exec() returns canned responses.

    Each call to sandbox.exec() pops the next response from the list.
    """
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


def _make_never_completing_sandbox() -> AsyncMock:
    """Create a mock sandbox that starts successfully then polls forever as 'running'.

    Useful for testing timeout and cancellation behavior.
    """
    sandbox = AsyncMock()
    sandbox.default_polling_interval.return_value = 5
    sandbox.no_events = _no_events_context

    call_count = 0

    async def fake_exec(*args: Any, **kwargs: Any) -> ExecResult[str]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ExecResult(
                success=True, returncode=0, stdout=_start_response(), stderr=""
            )
        else:
            return ExecResult(
                success=True,
                returncode=0,
                stdout=_poll_response(state="running", exit_code=None),
                stderr="",
            )

    sandbox.exec = AsyncMock(side_effect=fake_exec)
    return sandbox


# ============================================================================
# Start RPC params (env, cwd)
# ============================================================================


class TestStartRpcParams:
    """Verify that env and cwd are sent as separate RPC params (not baked into command)."""

    @pytest.mark.asyncio
    async def test_command_is_just_the_command(self) -> None:
        """Without env/cwd, the command string is just the shell-joined cmd."""
        sandbox = _make_sandbox_mock([_start_response()])

        await exec_remote_streaming(
            sandbox, ["echo", "hello world"], 5, ExecRemoteCommonOptions()
        )

        rpc_payload = json.loads(sandbox.exec.call_args_list[0].kwargs.get("input", ""))
        assert rpc_payload["params"]["command"] == "echo 'hello world'"
        assert "env" not in rpc_payload["params"]
        assert "cwd" not in rpc_payload["params"]

    @pytest.mark.asyncio
    async def test_env_sent_as_rpc_param(self) -> None:
        """Env dict is sent as a top-level RPC param, not embedded in command."""
        sandbox = _make_sandbox_mock([_start_response()])

        await exec_remote_streaming(
            sandbox,
            ["my_cmd"],
            5,
            ExecRemoteCommonOptions(env={"FOO": "bar", "BAZ": "qux"}),
        )

        rpc_payload = json.loads(sandbox.exec.call_args_list[0].kwargs.get("input", ""))
        assert rpc_payload["params"]["command"] == "my_cmd"
        assert rpc_payload["params"]["env"] == {"FOO": "bar", "BAZ": "qux"}

    @pytest.mark.asyncio
    async def test_cwd_sent_as_rpc_param(self) -> None:
        """Working directory is sent as a top-level RPC param, not embedded in command."""
        sandbox = _make_sandbox_mock([_start_response()])

        await exec_remote_streaming(
            sandbox, ["my_cmd"], 5, ExecRemoteCommonOptions(cwd="/tmp/work")
        )

        rpc_payload = json.loads(sandbox.exec.call_args_list[0].kwargs.get("input", ""))
        assert rpc_payload["params"]["command"] == "my_cmd"
        assert rpc_payload["params"]["cwd"] == "/tmp/work"

    @pytest.mark.asyncio
    async def test_env_and_cwd_sent_together(self) -> None:
        """Both env and cwd are sent as separate RPC params."""
        sandbox = _make_sandbox_mock([_start_response()])

        await exec_remote_streaming(
            sandbox,
            ["my_cmd"],
            5,
            ExecRemoteCommonOptions(env={"FOO": "bar"}, cwd="/tmp/work"),
        )

        rpc_payload = json.loads(sandbox.exec.call_args_list[0].kwargs.get("input", ""))
        assert rpc_payload["params"]["command"] == "my_cmd"
        assert rpc_payload["params"]["env"] == {"FOO": "bar"}
        assert rpc_payload["params"]["cwd"] == "/tmp/work"


# ============================================================================
# Streaming iteration
# ============================================================================


class TestStreamingIteration:
    @pytest.mark.parametrize(
        "poll_response, expected_events",
        [
            (
                {
                    "state": "completed",
                    "exit_code": 0,
                    "stdout": "output",
                    "stderr": "",
                },
                [
                    ExecRemoteEvent.Stdout(data="output"),
                    ExecRemoteEvent.Completed(exit_code=0),
                ],
            ),
            (
                {"state": "completed", "exit_code": 1, "stdout": "", "stderr": "error"},
                [
                    ExecRemoteEvent.Stderr(data="error"),
                    ExecRemoteEvent.Completed(exit_code=1),
                ],
            ),
            (
                {
                    "state": "completed",
                    "exit_code": 0,
                    "stdout": "out",
                    "stderr": "err",
                },
                [
                    ExecRemoteEvent.Stdout(data="out"),
                    ExecRemoteEvent.Stderr(data="err"),
                    ExecRemoteEvent.Completed(exit_code=0),
                ],
            ),
            (
                {"state": "completed", "exit_code": 0, "stdout": "", "stderr": ""},
                [ExecRemoteEvent.Completed(exit_code=0)],
            ),
            (
                {"state": "completed", "exit_code": 1, "stdout": "", "stderr": ""},
                [ExecRemoteEvent.Completed(exit_code=1)],
            ),
        ],
        ids=[
            "stdout_only",
            "stderr_only",
            "both_streams",
            "success_no_output",
            "failure_no_output",
        ],
    )
    @pytest.mark.asyncio
    async def test_single_poll_completion(
        self,
        poll_response: dict[str, Any],
        expected_events: list[ExecRemoteEvent],
    ) -> None:
        sandbox = _make_sandbox_mock([_start_response(), _rpc(poll_response)])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        events = [event async for event in proc]

        assert events == expected_events

    @pytest.mark.asyncio
    async def test_multiple_polls_before_completion(self) -> None:
        """Test that running polls with output yield chunks, then completion."""
        sandbox = _make_sandbox_mock(
            [
                _start_response(),
                _poll_response(state="running", exit_code=None, stdout="chunk1"),
                _poll_response(state="running", exit_code=None, stdout="chunk2"),
                _poll_response(stdout="chunk3"),
            ]
        )

        proc = ExecRemoteProcess(sandbox, ["cmd"], ExecRemoteCommonOptions(), 5)
        proc._poll_interval = 0
        await proc._start()

        events = [event async for event in proc]

        assert events == [
            ExecRemoteEvent.Stdout(data="chunk1"),
            ExecRemoteEvent.Stdout(data="chunk2"),
            ExecRemoteEvent.Stdout(data="chunk3"),
            ExecRemoteEvent.Completed(exit_code=0),
        ]

    @pytest.mark.asyncio
    async def test_empty_polls_skipped(self) -> None:
        """Running polls with no output should not yield events."""
        sandbox = _make_sandbox_mock(
            [
                _start_response(),
                _poll_response(state="running", exit_code=None),
                _poll_response(stdout="final"),
            ]
        )

        proc = ExecRemoteProcess(sandbox, ["cmd"], ExecRemoteCommonOptions(), 5)
        proc._poll_interval = 0
        await proc._start()

        events = [event async for event in proc]

        assert events == [
            ExecRemoteEvent.Stdout(data="final"),
            ExecRemoteEvent.Completed(exit_code=0),
        ]


# ============================================================================
# Single-use iterator
# ============================================================================


class TestSingleUseIterator:
    @pytest.mark.asyncio
    async def test_second_iteration_raises(self) -> None:
        sandbox = _make_sandbox_mock([_start_response(), _poll_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        _ = [event async for event in proc]

        with pytest.raises(RuntimeError, match="can only be iterated once"):
            async for _ in proc:
                pass


# ============================================================================
# Kill behavior
# ============================================================================


class TestKill:
    @pytest.mark.asyncio
    async def test_kill_calls_rpc(self) -> None:
        sandbox = _make_sandbox_mock([_start_response(), _kill_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        await proc.kill()

        assert sandbox.exec.call_count == 2

    @pytest.mark.asyncio
    async def test_kill_before_start_is_noop(self) -> None:
        sandbox = AsyncMock()
        proc = ExecRemoteProcess(sandbox, ["cmd"], ExecRemoteCommonOptions(), 5)

        await proc.kill()
        sandbox.exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_kill_after_completed_is_noop(self) -> None:
        sandbox = _make_sandbox_mock([_start_response(), _poll_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        _ = [event async for event in proc]
        call_count_before = sandbox.exec.call_count

        await proc.kill()
        assert sandbox.exec.call_count == call_count_before

    @pytest.mark.asyncio
    async def test_kill_after_kill_is_noop(self) -> None:
        sandbox = _make_sandbox_mock([_start_response(), _kill_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        await proc.kill()
        call_count_before = sandbox.exec.call_count

        await proc.kill()
        assert sandbox.exec.call_count == call_count_before

    @pytest.mark.asyncio
    async def test_kill_enqueues_remaining_output(self) -> None:
        sandbox = _make_sandbox_mock(
            [_start_response(), _kill_response(stdout="remaining", stderr="errs")]
        )

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        await proc.kill()

        assert proc._pending_events == [
            ExecRemoteEvent.Stdout(data="remaining"),
            ExecRemoteEvent.Stderr(data="errs"),
        ]

    @pytest.mark.asyncio
    async def test_killed_process_stops_iteration(self) -> None:
        """After external kill, iteration yields remaining output then stops."""
        sandbox = _make_sandbox_mock(
            [
                _start_response(),
                _poll_response(state="killed", exit_code=None, stdout="last"),
            ]
        )

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        events = [event async for event in proc]

        assert events == [ExecRemoteEvent.Stdout(data="last")]

    @pytest.mark.asyncio
    async def test_kill_suppresses_rpc_exception(self) -> None:
        """kill() should not propagate exceptions from the RPC call.

        Callers (e.g. bridge.py) rely on kill() being safe to call in finally
        blocks without disrupting subsequent cleanup like cancel_scope.cancel().
        """
        sandbox = AsyncMock()
        sandbox.default_polling_interval.return_value = 5

        call_count = 0

        async def failing_exec(*args: Any, **kwargs: Any) -> ExecResult[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Start succeeds
                return ExecResult(
                    success=True, returncode=0, stdout=_start_response(), stderr=""
                )
            # Kill RPC fails (e.g. sandbox transport error)
            raise ConnectionError("sandbox connection lost")

        sandbox.exec = AsyncMock(side_effect=failing_exec)

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)

        # Should not raise
        await proc.kill()

        # Should still be marked as killed
        assert proc._killed is True


# ============================================================================
# Cancellation
# ============================================================================


class TestCancellation:
    @pytest.mark.asyncio
    async def test_cancellation_kills_process(self) -> None:
        """When iteration is cancelled, the process should be killed."""
        kill_called = False
        sandbox = _make_never_completing_sandbox()

        proc = ExecRemoteProcess(sandbox, ["cmd"], ExecRemoteCommonOptions(), 5)
        proc._poll_interval = 0.01
        await proc._start()

        async def mock_kill() -> None:
            nonlocal kill_called
            kill_called = True
            proc._killed = True

        async def iterate() -> None:
            async for _ in proc:
                pass

        with patch.object(proc, "kill", side_effect=mock_kill):
            task = asyncio.create_task(iterate())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert kill_called


# ============================================================================
# Awaitable mode
# ============================================================================


class TestAwaitableMode:
    @pytest.mark.parametrize(
        "exit_code, stdout, stderr, expect_success",
        [
            (0, "hello", "", True),
            (1, "", "fail", False),
        ],
        ids=["success", "failure"],
    )
    @pytest.mark.asyncio
    async def test_returns_exec_result(
        self,
        exit_code: int,
        stdout: str,
        stderr: str,
        expect_success: bool,
    ) -> None:
        sandbox = _make_sandbox_mock(
            [
                _start_response(),
                _poll_response(exit_code=exit_code, stdout=stdout, stderr=stderr),
            ]
        )

        result = await exec_remote_awaitable(sandbox, ["cmd"], 5)

        assert isinstance(result, ExecResult)
        assert result.success is expect_success
        assert result.returncode == exit_code
        assert result.stdout == stdout
        assert result.stderr == stderr

    @pytest.mark.asyncio
    async def test_accumulates_output_across_polls(self) -> None:
        sandbox = _make_sandbox_mock(
            [
                _start_response(),
                _poll_response(state="running", exit_code=None, stdout="a", stderr="x"),
                _poll_response(state="running", exit_code=None, stdout="b", stderr="y"),
                _poll_response(stdout="c", stderr="z"),
            ]
        )

        result = await exec_remote_awaitable(
            sandbox, ["cmd"], 5, ExecRemoteCommonOptions(poll_interval=0)
        )

        assert result.success is True
        assert result.stdout == "abc"
        assert result.stderr == "xyz"

    @pytest.mark.asyncio
    async def test_killed_process_returns_failure(self) -> None:
        """If the process is killed externally, awaitable returns failure."""
        sandbox = _make_sandbox_mock(
            [_start_response(), _poll_response(state="killed", exit_code=None)]
        )

        result = await exec_remote_awaitable(sandbox, ["cmd"], 5)

        assert result.success is False
        assert result.returncode == -1


# ============================================================================
# Timeout
# ============================================================================


class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_raises_timeout_error(self) -> None:
        """Awaitable mode raises TimeoutError when timeout expires."""
        sandbox = _make_never_completing_sandbox()

        with pytest.raises(TimeoutError):
            await exec_remote_awaitable(
                sandbox,
                ["sleep", "999"],
                5,
                ExecRemoteAwaitableOptions(timeout=1, poll_interval=0.1),
            )

    @pytest.mark.asyncio
    async def test_timeout_none_does_not_timeout(self) -> None:
        """No timeout means the command runs to completion."""
        sandbox = _make_sandbox_mock([_start_response(), _poll_response(stdout="done")])

        result = await exec_remote_awaitable(
            sandbox, ["cmd"], 5, ExecRemoteAwaitableOptions(timeout=None)
        )

        assert result.success is True
        assert result.stdout == "done"

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self) -> None:
        """On timeout, the process should be killed."""
        sandbox = AsyncMock()
        sandbox.default_polling_interval.return_value = 5
        sandbox.no_events = _no_events_context

        call_count = 0
        methods_called: list[str] = []

        async def fake_exec(*args: Any, **kwargs: Any) -> ExecResult[str]:
            nonlocal call_count
            call_count += 1

            input_str = kwargs.get("input", "")
            if input_str:
                payload = json.loads(input_str)
                methods_called.append(payload.get("method", ""))

            if call_count == 1:
                return ExecResult(
                    success=True, returncode=0, stdout=_start_response(), stderr=""
                )
            elif methods_called and methods_called[-1] == "exec_remote_kill":
                return ExecResult(
                    success=True, returncode=0, stdout=_kill_response(), stderr=""
                )
            else:
                return ExecResult(
                    success=True,
                    returncode=0,
                    stdout=_poll_response(state="running", exit_code=None),
                    stderr="",
                )

        sandbox.exec = AsyncMock(side_effect=fake_exec)

        with pytest.raises(TimeoutError):
            await exec_remote_awaitable(
                sandbox,
                ["sleep", "999"],
                5,
                ExecRemoteAwaitableOptions(timeout=1, poll_interval=0.1),
            )

        assert "exec_remote_kill" in methods_called


# ============================================================================
# Input handling
# ============================================================================


class TestInputHandling:
    @pytest.mark.parametrize(
        "input_value, expected_rpc_input",
        [
            ("hello", "hello"),
            (b"bytes input", "bytes input"),
        ],
        ids=["string", "bytes_decoded"],
    )
    @pytest.mark.asyncio
    async def test_input_passed_to_start(
        self, input_value: str | bytes, expected_rpc_input: str
    ) -> None:
        sandbox = _make_sandbox_mock([_start_response()])

        await exec_remote_streaming(
            sandbox, ["cat"], 5, ExecRemoteCommonOptions(input=input_value)
        )

        start_call = sandbox.exec.call_args_list[0]
        rpc_payload = json.loads(
            start_call.kwargs.get("input", start_call[1].get("input", ""))
        )
        assert rpc_payload["params"]["input"] == expected_rpc_input


# ============================================================================
# PID access
# ============================================================================


class TestPidAccess:
    def test_pid_before_start_raises(self) -> None:
        proc = ExecRemoteProcess(AsyncMock(), ["cmd"], ExecRemoteCommonOptions(), 5)
        with pytest.raises(RuntimeError, match="not been submitted"):
            _ = proc.pid

    @pytest.mark.asyncio
    async def test_pid_after_start(self) -> None:
        sandbox = _make_sandbox_mock([_start_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        assert proc.pid == 42

    @pytest.mark.asyncio
    async def test_anext_before_start_raises(self) -> None:
        proc = ExecRemoteProcess(AsyncMock(), ["cmd"], ExecRemoteCommonOptions(), 5)
        proc._iteration_started = True
        with pytest.raises(RuntimeError, match="not been submitted"):
            await proc.__anext__()


# ============================================================================
# write_stdin / close_stdin
# ============================================================================


def _write_stdin_response(stdout: str = "", stderr: str = "") -> str:
    """Create a JSON-RPC write_stdin response."""
    return _rpc({"stdout": stdout, "stderr": stderr})


def _close_stdin_response(stdout: str = "", stderr: str = "") -> str:
    """Create a JSON-RPC close_stdin response."""
    return _rpc({"stdout": stdout, "stderr": stderr})


class TestWriteStdin:
    @pytest.mark.asyncio
    async def test_write_stdin_sends_rpc(self) -> None:
        """write_stdin sends data via exec_remote_write_stdin RPC."""
        sandbox = _make_sandbox_mock([_start_response(), _write_stdin_response()])
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cat"], 5, opts)
        await proc.write_stdin("hello")

        assert sandbox.exec.call_count == 2
        # Verify RPC payload
        rpc_call = sandbox.exec.call_args_list[1]
        payload = json.loads(rpc_call.kwargs.get("input", rpc_call[1].get("input", "")))
        assert payload["method"] == "exec_remote_write_stdin"
        assert payload["params"]["pid"] == 42
        assert payload["params"]["data"] == "hello"

    @pytest.mark.asyncio
    async def test_write_stdin_bytes_decoded(self) -> None:
        """Bytes input is decoded to UTF-8 before sending."""
        sandbox = _make_sandbox_mock([_start_response(), _write_stdin_response()])
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cat"], 5, opts)
        await proc.write_stdin(b"bytes data")

        rpc_call = sandbox.exec.call_args_list[1]
        payload = json.loads(rpc_call.kwargs.get("input", rpc_call[1].get("input", "")))
        assert payload["params"]["data"] == "bytes data"

    @pytest.mark.asyncio
    async def test_write_stdin_without_stdin_open_raises(self) -> None:
        """write_stdin raises RuntimeError when stdin_open is False."""
        sandbox = _make_sandbox_mock([_start_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        with pytest.raises(
            RuntimeError, match="stdin_open=True in ExecRemoteStreamingOptions"
        ):
            await proc.write_stdin("data")

    @pytest.mark.asyncio
    async def test_write_stdin_before_start_raises(self) -> None:
        """write_stdin raises RuntimeError when process not started."""
        proc = ExecRemoteProcess(
            AsyncMock(), ["cmd"], ExecRemoteStreamingOptions(stdin_open=True), 5
        )
        with pytest.raises(RuntimeError, match="not been submitted"):
            await proc.write_stdin("data")

    @pytest.mark.asyncio
    async def test_write_stdin_after_completed_raises(self) -> None:
        """write_stdin raises RuntimeError after process has completed."""
        sandbox = _make_sandbox_mock([_start_response(), _poll_response()])
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5, opts)
        _ = [event async for event in proc]

        with pytest.raises(RuntimeError, match="process has terminated"):
            await proc.write_stdin("data")

    @pytest.mark.asyncio
    async def test_write_stdin_after_killed_raises(self) -> None:
        """write_stdin raises RuntimeError after process has been killed."""
        sandbox = _make_sandbox_mock([_start_response(), _kill_response()])
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5, opts)
        await proc.kill()

        with pytest.raises(RuntimeError, match="process has terminated"):
            await proc.write_stdin("data")

    @pytest.mark.asyncio
    async def test_write_stdin_enqueues_output(self) -> None:
        """Output returned from write_stdin is enqueued as pending events."""
        sandbox = _make_sandbox_mock(
            [
                _start_response(),
                _write_stdin_response(stdout="chunk1", stderr="err1"),
                _poll_response(),
            ]
        )
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cat"], 5, opts)
        await proc.write_stdin("hello")

        events = [event async for event in proc]
        assert any(
            isinstance(e, ExecRemoteEvent.Stdout) and e.data == "chunk1" for e in events
        )
        assert any(
            isinstance(e, ExecRemoteEvent.Stderr) and e.data == "err1" for e in events
        )


class TestCloseStdin:
    @pytest.mark.asyncio
    async def test_close_stdin_sends_rpc(self) -> None:
        """close_stdin sends exec_remote_close_stdin RPC."""
        sandbox = _make_sandbox_mock([_start_response(), _close_stdin_response()])
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cat"], 5, opts)
        await proc.close_stdin()

        assert sandbox.exec.call_count == 2
        rpc_call = sandbox.exec.call_args_list[1]
        payload = json.loads(rpc_call.kwargs.get("input", rpc_call[1].get("input", "")))
        assert payload["method"] == "exec_remote_close_stdin"
        assert payload["params"]["pid"] == 42

    @pytest.mark.asyncio
    async def test_close_stdin_without_stdin_open_raises(self) -> None:
        """close_stdin raises RuntimeError when stdin_open is False."""
        sandbox = _make_sandbox_mock([_start_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        with pytest.raises(
            RuntimeError, match="stdin_open=True in ExecRemoteStreamingOptions"
        ):
            await proc.close_stdin()

    @pytest.mark.asyncio
    async def test_close_stdin_before_start_raises(self) -> None:
        """close_stdin raises RuntimeError when process not started."""
        proc = ExecRemoteProcess(
            AsyncMock(), ["cmd"], ExecRemoteStreamingOptions(stdin_open=True), 5
        )
        with pytest.raises(RuntimeError, match="not been submitted"):
            await proc.close_stdin()

    @pytest.mark.asyncio
    async def test_close_stdin_after_completed_is_noop(self) -> None:
        """close_stdin is a no-op after process has completed."""
        sandbox = _make_sandbox_mock([_start_response(), _poll_response()])
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5, opts)
        _ = [event async for event in proc]
        call_count_before = sandbox.exec.call_count

        await proc.close_stdin()
        assert sandbox.exec.call_count == call_count_before

    @pytest.mark.asyncio
    async def test_close_stdin_enqueues_output(self) -> None:
        """Output returned from close_stdin is enqueued as pending events."""
        sandbox = _make_sandbox_mock(
            [
                _start_response(),
                _close_stdin_response(stdout="final_out", stderr="final_err"),
                _poll_response(),
            ]
        )
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cat"], 5, opts)
        await proc.close_stdin()

        events = [event async for event in proc]
        assert any(
            isinstance(e, ExecRemoteEvent.Stdout) and e.data == "final_out"
            for e in events
        )
        assert any(
            isinstance(e, ExecRemoteEvent.Stderr) and e.data == "final_err"
            for e in events
        )

    @pytest.mark.asyncio
    async def test_close_stdin_after_killed_is_noop(self) -> None:
        """close_stdin is a no-op after process has been killed."""
        sandbox = _make_sandbox_mock([_start_response(), _kill_response()])
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5, opts)
        await proc.kill()
        call_count_before = sandbox.exec.call_count

        await proc.close_stdin()
        assert sandbox.exec.call_count == call_count_before


class TestStdinOpenStartParam:
    @pytest.mark.asyncio
    async def test_stdin_open_passed_to_start_rpc(self) -> None:
        """stdin_open=True is passed through to exec_remote_start RPC."""
        sandbox = _make_sandbox_mock([_start_response()])
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        await exec_remote_streaming(sandbox, ["cmd"], 5, opts)

        start_call = sandbox.exec.call_args_list[0]
        rpc_payload = json.loads(
            start_call.kwargs.get("input", start_call[1].get("input", ""))
        )
        assert rpc_payload["params"]["stdin_open"] is True

    @pytest.mark.asyncio
    async def test_stdin_open_false_not_sent(self) -> None:
        """stdin_open=False (default) is not included in start RPC params."""
        sandbox = _make_sandbox_mock([_start_response()])

        await exec_remote_streaming(sandbox, ["cmd"], 5)

        start_call = sandbox.exec.call_args_list[0]
        rpc_payload = json.loads(
            start_call.kwargs.get("input", start_call[1].get("input", ""))
        )
        assert "stdin_open" not in rpc_payload["params"]
