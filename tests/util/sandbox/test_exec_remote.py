"""Tests for exec_remote.

Unit tests mock sandbox.exec() to test host-side logic (guards, kill behavior,
cancellation, accumulation). Integration tests (marked slow) run against a real
Docker container to verify the full host-to-container path.
"""

import contextlib
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import anyio
import pytest
import tenacity
from tenacity.wait import wait_none
from test_helpers.utils import skip_if_no_docker

import inspect_ai.util._sandbox.exec_remote as exec_remote_module
from inspect_ai.tool._sandbox_tools_utils.sandbox import (
    SandboxInjectionError,
    _inject_container_tools_code,
)
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.environment import SandboxDefaultUser
from inspect_ai.util._sandbox.events import (
    SandboxEnvironmentProxy,
    SandboxTimeoutError,
)
from inspect_ai.util._sandbox.exec_remote import (
    ExecCompleted,
    ExecRemoteAwaitableOptions,
    ExecRemoteCommonOptions,
    ExecRemoteProcess,
    ExecRemoteStreamingOptions,
    ExecStderr,
    ExecStdout,
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
    seq: int = 0,
) -> str:
    """Create a JSON-RPC poll response."""
    return _rpc(
        {
            "state": state,
            "exit_code": exit_code,
            "seq": seq,
            "stdout": stdout,
            "stderr": stderr,
        }
    )


def _kill_response(stdout: str = "", stderr: str = "", seq: int = 0) -> str:
    """Create a JSON-RPC kill response."""
    return _rpc({"seq": seq, "stdout": stdout, "stderr": stderr})


def _write_stdin_response(stdout: str = "", stderr: str = "", seq: int = 0) -> str:
    """Create a JSON-RPC write_stdin response."""
    return _rpc({"seq": seq, "stdout": stdout, "stderr": stderr})


def _close_stdin_response(stdout: str = "", stderr: str = "", seq: int = 0) -> str:
    """Create a JSON-RPC close_stdin response."""
    return _rpc({"seq": seq, "stdout": stdout, "stderr": stderr})


@contextlib.contextmanager
def _no_events_context() -> Iterator[None]:
    """A no-op context manager to stand in for SandboxEnvironmentProxy.no_events()."""
    yield


def _mock_sandbox() -> AsyncMock:
    sandbox = AsyncMock()
    sandbox._tools_default_user = None
    return sandbox


def _make_sandbox_mock(responses: list[str]) -> AsyncMock:
    """Create a mock SandboxEnvironment whose exec() returns canned responses.

    Each call to sandbox.exec() pops the next response from the list.
    """
    sandbox = _mock_sandbox()
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
    sandbox = _mock_sandbox()
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


def _rpc_error(message: str, code: int = -32099, id: int = 1) -> str:
    """Create a JSON-RPC error response string (default: the server's ToolException code)."""
    return json.dumps(
        {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": id}
    )


def _make_scripted_sandbox(script: list[str | Exception]) -> AsyncMock:
    """Create a mock sandbox whose exec() answers from `script` in order.

    A str entry is returned as stdout; an Exception entry is raised. When the
    script runs out, the last entry repeats. Every JSON-RPC request's method and
    params are recorded in `sandbox.requests`.
    """
    sandbox = _mock_sandbox()
    sandbox.default_polling_interval.return_value = 5
    sandbox.no_events = _no_events_context
    requests: list[tuple[str, dict[str, Any]]] = []
    sandbox.requests = requests
    steps = list(script)

    async def fake_exec(*args: Any, **kwargs: Any) -> ExecResult[str]:
        request = json.loads(kwargs["input"])
        requests.append((request["method"], request.get("params", {})))
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        if isinstance(step, Exception):
            raise step
        return ExecResult(success=True, returncode=0, stdout=step, stderr="")

    sandbox.exec = AsyncMock(side_effect=fake_exec)
    return sandbox


# ============================================================================
# Single-use iterator
# ============================================================================


class TestSingleUseIterator:
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


class TestPollRetryExhaustion:
    async def test_poll_retry_exhaustion_reraises_underlying_error(self) -> None:
        sandbox = _mock_sandbox()
        sandbox.default_polling_interval.return_value = 5
        sandbox.no_events = _no_events_context
        sandbox.exec = AsyncMock(
            side_effect=RuntimeError("command terminated with exit code 137")
        )
        proc = ExecRemoteProcess(sandbox, ["cmd"], ExecRemoteCommonOptions(), 5)

        # The retry backoff would take ~30s to exhaust; zero out the wait the
        # same way conftest's fast_retry_waits does for model retries. Patching
        # asyncio.sleep would be a no-op under the trio variant (tenacity routes
        # through its portable sleep helper), and with real sleeps the attempt
        # count assertion becomes timing-sensitive.
        with patch(
            "inspect_ai.util._sandbox.exec_remote.wait_exponential_jitter",
            new=lambda *a, **k: wait_none(),
        ):
            with pytest.raises(RuntimeError, match="exit code 137"):
                await proc._poll()

        # stop_after_attempt(5) pins the attempt count; keep the assertion
        # exact so a stop-config regression is caught
        assert sandbox.exec.call_count == 5


# ============================================================================
# Poll timeout recovery (opt-in re-polling after a poll times out)
# ============================================================================


def _polls(sandbox: AsyncMock) -> list[dict[str, Any]]:
    """The params of every exec_remote_poll request a scripted sandbox received."""
    return [
        params for method, params in sandbox.requests if method == "exec_remote_poll"
    ]


class TestPollTimeoutRecovery:
    @pytest.mark.parametrize(
        "options",
        [ExecRemoteCommonOptions(), ExecRemoteCommonOptions(poll_timeout_retry=False)],
        ids=["default", "poll_timeout_retry_false"],
    )
    async def test_poll_timeout_is_raised_without_recovery(
        self, options: ExecRemoteCommonOptions
    ) -> None:
        """Unless recovery is requested, a timed-out poll raises and is not re-issued."""
        sandbox = _make_scripted_sandbox(
            [
                _start_response(42),
                SandboxTimeoutError("the pod is not answering."),
                _poll_response(state="completed", exit_code=0, seq=0),
            ]
        )
        proc = await exec_remote_streaming(sandbox, ["cmd"], 5, options)

        with pytest.raises(SandboxTimeoutError, match="the pod is not answering"):
            _ = [event async for event in proc]

        assert len(_polls(sandbox)) == 1

    def test_recovery_cannot_override_poll_timeout_retry_false(self) -> None:
        with pytest.raises(ValueError, match="poll_timeout_retry=False"):
            ExecRemoteCommonOptions(poll_timeout_retry=False, poll_timeout_recovery=60)

    async def test_recovery_rides_through_sandbox_timeouts_without_losing_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            exec_remote_module, "POLL_TIMEOUT_RECOVERY_WAIT_SECONDS", 0.0
        )
        stall = SandboxTimeoutError(
            "Command exceeded its 90s timeout and the pod did not report completion "
            "within a further 30s; the pod is not answering."
        )
        sandbox = _make_scripted_sandbox(
            [
                _start_response(42),
                _poll_response(state="running", exit_code=None, stdout="A", seq=1),
                stall,
                stall,
                _poll_response(state="running", exit_code=None, stdout="B", seq=2),
                _poll_response(state="completed", exit_code=0, seq=2),
            ]
        )
        proc = await exec_remote_streaming(
            sandbox, ["cmd"], 5, ExecRemoteCommonOptions(poll_timeout_recovery=60)
        )

        events = [event async for event in proc]

        assert events == [
            ExecStdout(data="A"),
            ExecStdout(data="B"),
            ExecCompleted(exit_code=0),
        ]
        # The two timed-out polls and the poll that finally answered all asked the
        # server to replay from seq 1: nothing after "A" was acknowledged until "B"
        # arrived.
        assert [params["ack_seq"] for params in _polls(sandbox)] == [0, 1, 1, 1, 2]

    async def test_recovery_time_exhausted_reraises_the_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            exec_remote_module, "POLL_TIMEOUT_RECOVERY_WAIT_SECONDS", 0.05
        )
        sandbox = _make_scripted_sandbox(
            [_start_response(42), SandboxTimeoutError("the pod is not answering.")]
        )
        proc = await exec_remote_streaming(
            sandbox, ["cmd"], 5, ExecRemoteCommonOptions(poll_timeout_recovery=0.3)
        )

        with pytest.raises(TimeoutError, match="the pod is not answering") as raised:
            await proc._poll()

        assert isinstance(raised.value, SandboxTimeoutError)
        assert 2 <= len(_polls(sandbox)) <= 10

    async def test_cancellation_during_recovery_ends_it_and_kills_the_process(
        self,
    ) -> None:
        """A caller's own deadline cancels recovery at once and still kills the process."""
        sandbox = _make_scripted_sandbox(
            [_start_response(42), SandboxTimeoutError("the pod is not answering.")]
        )

        with pytest.raises(TimeoutError) as raised:
            await exec_remote_awaitable(
                sandbox,
                ["cmd"],
                5,
                ExecRemoteAwaitableOptions(timeout=0.5, poll_timeout_recovery=60),
            )

        # The caller's own deadline, not the sandbox's timeout re-raised once the
        # recovery time ran out.
        assert not isinstance(raised.value, SandboxTimeoutError)
        assert [method for method, _ in sandbox.requests][-1] == "exec_remote_kill"

    async def test_recovery_does_not_reissue_a_timed_out_start(self) -> None:
        """Only polls are re-issued; a sandbox's own timeout retry is outside this mock."""
        sandbox = _make_scripted_sandbox(
            [SandboxTimeoutError("the pod is not answering.")]
        )

        with pytest.raises(TimeoutError):
            await exec_remote_streaming(
                sandbox, ["cmd"], 5, ExecRemoteCommonOptions(poll_timeout_recovery=60)
            )

        assert sandbox.exec.call_count == 1

    async def test_poll_after_recovery_names_a_lost_terminal_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            exec_remote_module, "POLL_TIMEOUT_RECOVERY_WAIT_SECONDS", 0.0
        )
        sandbox = _make_scripted_sandbox(
            [
                _start_response(42),
                SandboxTimeoutError("the pod is not answering."),
                _rpc_error("No job found with pid 42"),
            ]
        )
        proc = await exec_remote_streaming(
            sandbox, ["cmd"], 5, ExecRemoteCommonOptions(poll_timeout_recovery=60)
        )

        # The inner RuntimeError retry would otherwise back off for ~30s.
        with patch(
            "inspect_ai.util._sandbox.exec_remote.wait_exponential_jitter",
            new=lambda *a, **k: wait_none(),
        ):
            with pytest.raises(RuntimeError, match="ended during the stall") as raised:
                await proc._poll()

        assert raised.value.__cause__ is not None
        assert "No job found with pid 42" in str(raised.value.__cause__)

    async def test_no_job_found_without_a_timed_out_poll_stays_the_servers_error(
        self,
    ) -> None:
        """Without a timed-out poll no response was lost, so nothing is relabelled."""
        sandbox = _make_scripted_sandbox(
            [_start_response(42), _rpc_error("No job found with pid 42")]
        )
        proc = await exec_remote_streaming(
            sandbox, ["cmd"], 5, ExecRemoteCommonOptions(poll_timeout_recovery=60)
        )

        with patch(
            "inspect_ai.util._sandbox.exec_remote.wait_exponential_jitter",
            new=lambda *a, **k: wait_none(),
        ):
            with pytest.raises(RuntimeError, match=r"^No job found with pid 42$"):
                await proc._poll()

    @pytest.mark.parametrize(
        ("kill_during", "kill_reaches_sandbox", "raised", "match"),
        [
            ("pause", True, SandboxTimeoutError, "not answering"),
            ("pause", False, SandboxTimeoutError, "not answering"),
            # the server's own error: the caller killed the process
            ("repoll", True, RuntimeError, r"^No job found with pid 42$"),
            ("repoll", False, SandboxTimeoutError, "not answering"),
            # the re-poll's own error, not the answer to a poll sent after the kill
            ("backoff", True, RuntimeError, "exit code 137"),
            ("backoff", False, RuntimeError, "exit code 137"),
        ],
        ids=[
            "pause-kill_answered",
            "pause-kill_timed_out",
            "repoll-kill_answered",
            "repoll-kill_timed_out",
            "backoff-kill_answered",
            "backoff-kill_timed_out",
        ],
    )
    async def test_no_poll_is_issued_after_kill(
        self,
        monkeypatch: pytest.MonkeyPatch,
        kill_during: str,
        kill_reaches_sandbox: bool,
        raised: type[Exception],
        match: str,
    ) -> None:
        """kill() during recovery stops it, even when the kill request itself timed out.

        The kill comes during the pause before a re-poll, while a re-poll is in
        flight, or during the backoff after a re-poll failed with a `RuntimeError`.
        An in-flight re-poll then gets the server's `No job found` (the kill reached
        the sandbox) or times out (it did not), and is not retried.
        """
        monkeypatch.setattr(
            exec_remote_module, "POLL_TIMEOUT_RECOVERY_WAIT_SECONDS", 0.2
        )
        first_poll_timed_out = anyio.Event()
        repoll_started = anyio.Event()
        repoll_failed = anyio.Event()
        kill_requested = anyio.Event()
        kill_returned = anyio.Event()
        polls = 0
        requests: list[str] = []

        def answer(stdout: str) -> ExecResult[str]:
            return ExecResult(success=True, returncode=0, stdout=stdout, stderr="")

        async def fake_exec(*args: Any, **kwargs: Any) -> ExecResult[str]:
            nonlocal polls
            method = json.loads(kwargs["input"])["method"]
            requests.append(method)
            if method == "exec_remote_start":
                return answer(_start_response(42))
            if method == "exec_remote_kill":
                kill_requested.set()
                if not kill_reaches_sandbox:
                    raise SandboxTimeoutError("the pod is not answering.")
                return answer(_kill_response())
            polls += 1
            if polls == 1:
                first_poll_timed_out.set()
                raise SandboxTimeoutError("the pod is not answering.")
            if polls == 2 and kill_during == "repoll":
                repoll_started.set()
                await kill_requested.wait()
            if polls == 2 and kill_during == "backoff":
                repoll_failed.set()
                raise RuntimeError("command terminated with exit code 137")
            if kill_requested.is_set() and kill_reaches_sandbox:
                return answer(_rpc_error("No job found with pid 42"))
            raise SandboxTimeoutError("the pod is not answering.")

        sandbox = _mock_sandbox()
        sandbox.default_polling_interval.return_value = 5
        sandbox.no_events = _no_events_context
        sandbox.exec = AsyncMock(side_effect=fake_exec)
        proc = await exec_remote_streaming(
            sandbox, ["cmd"], 5, ExecRemoteCommonOptions(poll_timeout_recovery=60)
        )

        kill_after = {
            "pause": first_poll_timed_out,
            "repoll": repoll_started,
            "backoff": repoll_failed,
        }[kill_during]

        async def kill_at_the_chosen_moment() -> None:
            await kill_after.wait()
            await proc.kill()
            kill_returned.set()

        async def backoff_until_killed(seconds: float) -> None:
            await kill_returned.wait()

        def retry_backing_off_until_killed(**kwargs: Any) -> Any:
            return tenacity.retry(sleep=backoff_until_killed, **kwargs)

        # The backoff between RuntimeError retries of a poll lasts until kill() has
        # returned, so a kill always lands inside it and no retry waits ~30s.
        with patch(
            "inspect_ai.util._sandbox.exec_remote.retry",
            new=retry_backing_off_until_killed,
        ):
            with anyio.fail_after(10):
                async with anyio.create_task_group() as tg:
                    tg.start_soon(kill_at_the_chosen_moment)
                    with pytest.raises(raised, match=match):
                        _ = [event async for event in proc]

        assert requests[-1] == "exec_remote_kill"


class TestKill:
    async def test_kill_calls_rpc(self) -> None:
        sandbox = _make_sandbox_mock([_start_response(), _kill_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        await proc.kill()

        assert sandbox.exec.call_count == 2

    async def test_kill_before_start_is_noop(self) -> None:
        sandbox = _mock_sandbox()
        proc = ExecRemoteProcess(sandbox, ["cmd"], ExecRemoteCommonOptions(), 5)

        await proc.kill()
        sandbox.exec.assert_not_called()

    async def test_kill_after_completed_is_noop(self) -> None:
        sandbox = _make_sandbox_mock([_start_response(), _poll_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        _ = [event async for event in proc]
        call_count_before = sandbox.exec.call_count

        await proc.kill()
        assert sandbox.exec.call_count == call_count_before

    async def test_kill_after_kill_is_noop(self) -> None:
        sandbox = _make_sandbox_mock([_start_response(), _kill_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        await proc.kill()
        call_count_before = sandbox.exec.call_count

        await proc.kill()
        assert sandbox.exec.call_count == call_count_before

    async def test_kill_enqueues_remaining_output(self) -> None:
        sandbox = _make_sandbox_mock(
            [_start_response(), _kill_response(stdout="remaining", stderr="errs")]
        )

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        await proc.kill()

        assert proc._pending_events == [
            ExecStdout(data="remaining"),
            ExecStderr(data="errs"),
        ]

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

        assert events == [ExecStdout(data="last")]

    async def test_kill_suppresses_rpc_exception(self) -> None:
        """kill() should not propagate exceptions from the RPC call.

        Callers (e.g. bridge.py) rely on kill() being safe to call in finally
        blocks without disrupting subsequent cleanup like cancel_scope.cancel().
        """
        sandbox = _mock_sandbox()
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
            async with anyio.create_task_group() as tg:
                tg.start_soon(iterate)
                await anyio.sleep(0.05)
                tg.cancel_scope.cancel()

        assert kill_called


# ============================================================================
# Awaitable mode (host-side accumulation logic)
# ============================================================================


class TestAwaitableMode:
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

    async def test_timeout_kills_process(self) -> None:
        """On timeout, the process should be killed."""
        sandbox = _mock_sandbox()
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
# PID access
# ============================================================================


class TestPidAccess:
    def test_pid_before_start_raises(self) -> None:
        proc = ExecRemoteProcess(AsyncMock(), ["cmd"], ExecRemoteCommonOptions(), 5)
        with pytest.raises(RuntimeError, match="not been submitted"):
            _ = proc.pid

    async def test_pid_after_start(self) -> None:
        sandbox = _make_sandbox_mock([_start_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        assert proc.pid == 42

    async def test_anext_before_start_raises(self) -> None:
        proc = ExecRemoteProcess(AsyncMock(), ["cmd"], ExecRemoteCommonOptions(), 5)
        proc._iteration_started = True
        with pytest.raises(RuntimeError, match="not been submitted"):
            await proc.__anext__()


class TestUserParam:
    _DEFAULT_USER = SandboxDefaultUser(uid=1111, gid=1111, groups=[1111], home="/h")

    async def _start_params(
        self, options: ExecRemoteStreamingOptions
    ) -> dict[str, Any]:
        sandbox = _make_sandbox_mock([_start_response()])
        sandbox._tools_default_user = self._DEFAULT_USER
        await exec_remote_streaming(sandbox, ["cmd"], 5, options)
        params: dict[str, Any] = json.loads(sandbox.exec.call_args.kwargs["input"])[
            "params"
        ]
        return params

    async def test_default_user_identity_sent_without_explicit_user(self) -> None:
        params = await self._start_params(ExecRemoteStreamingOptions())
        assert params["user"] == self._DEFAULT_USER._asdict()

    async def test_explicit_user_wins(self) -> None:
        params = await self._start_params(ExecRemoteStreamingOptions(user="nobody"))
        assert params["user"] == "nobody"


# ============================================================================
# write_stdin / close_stdin error guards
# ============================================================================


class TestWriteStdin:
    async def test_write_stdin_without_stdin_open_raises(self) -> None:
        """write_stdin raises RuntimeError when stdin_open is False."""
        sandbox = _make_sandbox_mock([_start_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        with pytest.raises(
            RuntimeError, match="stdin_open=True in ExecRemoteStreamingOptions"
        ):
            await proc.write_stdin("data")

    async def test_write_stdin_before_start_raises(self) -> None:
        """write_stdin raises RuntimeError when process not started."""
        proc = ExecRemoteProcess(
            AsyncMock(), ["cmd"], ExecRemoteStreamingOptions(stdin_open=True), 5
        )
        with pytest.raises(RuntimeError, match="not been submitted"):
            await proc.write_stdin("data")

    async def test_write_stdin_after_completed_raises(self) -> None:
        """write_stdin raises RuntimeError after process has completed."""
        sandbox = _make_sandbox_mock([_start_response(), _poll_response()])
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5, opts)
        _ = [event async for event in proc]

        with pytest.raises(RuntimeError, match="process has terminated"):
            await proc.write_stdin("data")

    async def test_write_stdin_after_killed_raises(self) -> None:
        """write_stdin raises RuntimeError after process has been killed."""
        sandbox = _make_sandbox_mock([_start_response(), _kill_response()])
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5, opts)
        await proc.kill()

        with pytest.raises(RuntimeError, match="process has terminated"):
            await proc.write_stdin("data")

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
        assert any(isinstance(e, ExecStdout) and e.data == "chunk1" for e in events)
        assert any(isinstance(e, ExecStderr) and e.data == "err1" for e in events)


# ============================================================================
# Poll timeout and retry option plumbing
# ============================================================================


class TestPollTimeoutOptions:
    """Verify that poll_timeout and poll_timeout_retry propagate correctly."""

    async def test_default_poll_timeout_uses_rpc_timeout(self) -> None:
        """Default poll_timeout=None falls back to RPC_TIMEOUT (30)."""
        sandbox = _make_sandbox_mock([_start_response()])

        await exec_remote_streaming(sandbox, ["cmd"], 5, ExecRemoteCommonOptions())

        kwargs = sandbox.exec.call_args_list[0].kwargs
        assert kwargs["timeout"] == 120

    async def test_explicit_poll_timeout_propagates(self) -> None:
        """Explicit poll_timeout value is passed through to sandbox.exec."""
        sandbox = _make_sandbox_mock([_start_response()])

        await exec_remote_streaming(
            sandbox, ["cmd"], 5, ExecRemoteCommonOptions(poll_timeout=60)
        )

        kwargs = sandbox.exec.call_args_list[0].kwargs
        assert kwargs["timeout"] == 60

    async def test_default_poll_timeout_retry_preserves_transport_default(self) -> None:
        """Default poll_timeout_retry=None should not pass timeout_retry.

        Transport uses its own default (True).
        """
        sandbox = _make_sandbox_mock([_start_response()])

        await exec_remote_streaming(sandbox, ["cmd"], 5, ExecRemoteCommonOptions())

        kwargs = sandbox.exec.call_args_list[0].kwargs
        # timeout_retry should either not be present (transport defaults to True)
        # or be True
        assert kwargs.get("timeout_retry", True) is True

    async def test_explicit_poll_timeout_retry_false_propagates(self) -> None:
        """Explicit poll_timeout_retry=False disables retries."""
        sandbox = _make_sandbox_mock([_start_response()])

        await exec_remote_streaming(
            sandbox, ["cmd"], 5, ExecRemoteCommonOptions(poll_timeout_retry=False)
        )

        kwargs = sandbox.exec.call_args_list[0].kwargs
        assert kwargs["timeout_retry"] is False

    async def test_explicit_poll_timeout_retry_true_propagates(self) -> None:
        """Explicit poll_timeout_retry=True is passed through."""
        sandbox = _make_sandbox_mock([_start_response()])

        await exec_remote_streaming(
            sandbox, ["cmd"], 5, ExecRemoteCommonOptions(poll_timeout_retry=True)
        )

        kwargs = sandbox.exec.call_args_list[0].kwargs
        assert kwargs["timeout_retry"] is True


# ============================================================================
# Options positional order
# ============================================================================

_BASE_POSITIONAL: tuple[object, ...] = (
    "in",
    "/work",
    {"K": "V"},
    "someone",
    7.0,
    30.0,
    False,
    False,
)


def _base_fields(options: ExecRemoteCommonOptions) -> tuple[object, ...]:
    return (
        options.input,
        options.cwd,
        options.env,
        options.user,
        options.poll_interval,
        options.poll_timeout,
        options.poll_timeout_retry,
        options.concurrency,
    )


class TestOptionsPositionalOrder:
    """New options are keyword-only, so positional callers keep their meaning."""

    def test_common_options(self) -> None:
        options = ExecRemoteCommonOptions(
            "in", "/work", {"K": "V"}, "someone", 7.0, 30.0, False, False
        )

        assert _base_fields(options) == _BASE_POSITIONAL
        assert options.poll_timeout_recovery is None

    def test_streaming_options(self) -> None:
        options = ExecRemoteStreamingOptions(
            "in", "/work", {"K": "V"}, "someone", 7.0, 30.0, False, False, True
        )

        assert _base_fields(options) == _BASE_POSITIONAL
        assert options.stdin_open is True
        assert options.poll_timeout_recovery is None

    def test_awaitable_options(self) -> None:
        options = ExecRemoteAwaitableOptions(
            "in", "/work", {"K": "V"}, "someone", 7.0, 30.0, False, False, 12.0
        )

        assert _base_fields(options) == _BASE_POSITIONAL
        assert options.timeout == 12.0
        assert options.poll_timeout_recovery is None


# ============================================================================
# close_stdin error guards
# ============================================================================


class TestCloseStdin:
    async def test_close_stdin_without_stdin_open_raises(self) -> None:
        """close_stdin raises RuntimeError when stdin_open is False."""
        sandbox = _make_sandbox_mock([_start_response()])

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)
        with pytest.raises(
            RuntimeError, match="stdin_open=True in ExecRemoteStreamingOptions"
        ):
            await proc.close_stdin()

    async def test_close_stdin_before_start_raises(self) -> None:
        """close_stdin raises RuntimeError when process not started."""
        proc = ExecRemoteProcess(
            AsyncMock(), ["cmd"], ExecRemoteStreamingOptions(stdin_open=True), 5
        )
        with pytest.raises(RuntimeError, match="not been submitted"):
            await proc.close_stdin()

    async def test_close_stdin_after_completed_is_noop(self) -> None:
        """close_stdin is a no-op after process has completed."""
        sandbox = _make_sandbox_mock([_start_response(), _poll_response()])
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5, opts)
        _ = [event async for event in proc]
        call_count_before = sandbox.exec.call_count

        await proc.close_stdin()
        assert sandbox.exec.call_count == call_count_before

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
        assert any(isinstance(e, ExecStdout) and e.data == "final_out" for e in events)
        assert any(isinstance(e, ExecStderr) and e.data == "final_err" for e in events)

    async def test_close_stdin_after_killed_is_noop(self) -> None:
        """close_stdin is a no-op after process has been killed."""
        sandbox = _make_sandbox_mock([_start_response(), _kill_response()])
        opts = ExecRemoteStreamingOptions(stdin_open=True)

        proc = await exec_remote_streaming(sandbox, ["cmd"], 5, opts)
        await proc.kill()
        call_count_before = sandbox.exec.call_count

        await proc.close_stdin()
        assert sandbox.exec.call_count == call_count_before


# ============================================================================
# Integration tests (real Docker container)
# ============================================================================


@pytest.fixture
async def docker_sandbox(request):
    """Yield a proxy-wrapped Docker sandbox with tools injected."""
    task_name = f"{__name__}_{request.node.name}"

    await DockerSandboxEnvironment.task_init(task_name=task_name, config=None)
    envs = await DockerSandboxEnvironment.sample_init(
        task_name=task_name, config=None, metadata={}
    )

    async def cleanup() -> None:
        await DockerSandboxEnvironment.sample_cleanup(
            task_name=task_name, config=None, environments=envs, interrupted=False
        )
        await DockerSandboxEnvironment.task_cleanup(
            task_name=task_name, config=None, cleanup=True
        )

    raw = envs["default"]
    try:
        await _inject_container_tools_code(raw)
    except (FileNotFoundError, SandboxInjectionError):
        await cleanup()
        pytest.skip("Sandbox tools binary not available")

    proxy = SandboxEnvironmentProxy(raw)
    proxy._tools_injected = True

    # Smoke test: verify the injected binary accepts the current RPC schema.
    # Fails when the binary predates host-side schema changes (e.g. ack_seq).
    # Only skip on ValueError (response-validation/schema mismatch). RuntimeError
    # — including poll-retry exhaustion, which is now reraised — must propagate
    # so a genuinely broken docker exec fails loudly instead of silently skipping
    # this whole integration suite.
    try:
        await exec_remote_awaitable(proxy, ["true"], proxy.default_polling_interval())
    except ValueError:
        await cleanup()
        pytest.skip("Injected binary incompatible with current host-side RPC schema")

    try:
        yield proxy
    finally:
        await cleanup()


@skip_if_no_docker
@pytest.mark.slow
async def test_streaming_echo(docker_sandbox) -> None:
    """Streaming exec_remote yields stdout then completed."""
    proc = await exec_remote_streaming(
        docker_sandbox, ["echo", "hello"], docker_sandbox.default_polling_interval()
    )
    assert isinstance(proc, ExecRemoteProcess)

    events = [event async for event in proc]

    stdout_events = [e for e in events if isinstance(e, ExecStdout)]
    completed = [e for e in events if isinstance(e, ExecCompleted)]
    assert len(completed) == 1
    assert completed[0].exit_code == 0
    assert "hello" in "".join(e.data for e in stdout_events)


@skip_if_no_docker
@pytest.mark.slow
async def test_streaming_stderr(docker_sandbox) -> None:
    """Streaming exec_remote captures stderr."""
    proc = await exec_remote_streaming(
        docker_sandbox,
        ["sh", "-c", "echo err >&2"],
        docker_sandbox.default_polling_interval(),
    )

    events = [event async for event in proc]

    stderr_events = [e for e in events if isinstance(e, ExecStderr)]
    assert "err" in "".join(e.data for e in stderr_events)


@skip_if_no_docker
@pytest.mark.slow
async def test_streaming_nonzero_exit(docker_sandbox) -> None:
    """Non-zero exit code is reported in ExecCompleted."""
    proc = await exec_remote_streaming(
        docker_sandbox,
        ["sh", "-c", "exit 42"],
        docker_sandbox.default_polling_interval(),
    )

    events = [event async for event in proc]

    completed = [e for e in events if isinstance(e, ExecCompleted)]
    assert len(completed) == 1
    assert completed[0].exit_code == 42


@skip_if_no_docker
@pytest.mark.slow
async def test_awaitable_echo(docker_sandbox) -> None:
    """Awaitable exec_remote returns ExecResult."""
    result = await exec_remote_awaitable(
        docker_sandbox, ["echo", "hello"], docker_sandbox.default_polling_interval()
    )

    assert result.success
    assert "hello" in result.stdout


@skip_if_no_docker
@pytest.mark.slow
async def test_awaitable_failure(docker_sandbox) -> None:
    """Awaitable exec_remote reports failure."""
    result = await exec_remote_awaitable(
        docker_sandbox,
        ["sh", "-c", "echo oops >&2; exit 1"],
        docker_sandbox.default_polling_interval(),
    )

    assert not result.success
    assert result.returncode == 1
    assert "oops" in result.stderr


@skip_if_no_docker
@pytest.mark.slow
async def test_streaming_multiline(docker_sandbox) -> None:
    """Streaming collects multi-line output correctly."""
    proc = await exec_remote_streaming(
        docker_sandbox,
        ["sh", "-c", "echo line1; echo line2; echo line3"],
        docker_sandbox.default_polling_interval(),
    )

    events = [event async for event in proc]

    stdout = "".join(e.data for e in events if isinstance(e, ExecStdout))
    assert "line1" in stdout
    assert "line2" in stdout
    assert "line3" in stdout


@skip_if_no_docker
@pytest.mark.slow
async def test_streaming_kill(docker_sandbox) -> None:
    """Kill terminates a long-running process."""
    proc = await exec_remote_streaming(
        docker_sandbox, ["sleep", "300"], docker_sandbox.default_polling_interval()
    )
    await proc.kill()
    assert proc._killed


@skip_if_no_docker
@pytest.mark.slow
async def test_awaitable_timeout(docker_sandbox) -> None:
    """Awaitable mode raises TimeoutError when timeout expires."""
    with pytest.raises(TimeoutError):
        await exec_remote_awaitable(
            docker_sandbox,
            ["sleep", "300"],
            docker_sandbox.default_polling_interval(),
            ExecRemoteAwaitableOptions(timeout=2, poll_interval=0.5),
        )


@skip_if_no_docker
@pytest.mark.slow
async def test_streaming_stdin(docker_sandbox) -> None:
    """write_stdin sends data to the process and close_stdin triggers EOF."""
    opts = ExecRemoteStreamingOptions(stdin_open=True)
    proc = await exec_remote_streaming(
        docker_sandbox, ["cat"], docker_sandbox.default_polling_interval(), opts
    )

    await proc.write_stdin("hello from stdin\n")
    await proc.close_stdin()

    events = [event async for event in proc]

    stdout = "".join(e.data for e in events if isinstance(e, ExecStdout))
    assert "hello from stdin" in stdout

    completed = [e for e in events if isinstance(e, ExecCompleted)]
    assert len(completed) == 1
    assert completed[0].exit_code == 0


@skip_if_no_docker
@pytest.mark.slow
async def test_env_vars(docker_sandbox) -> None:
    """Environment variables are passed to the process."""
    opts = ExecRemoteCommonOptions(env={"MY_TEST_VAR": "hello123"})
    result = await exec_remote_awaitable(
        docker_sandbox,
        ["sh", "-c", "echo $MY_TEST_VAR"],
        docker_sandbox.default_polling_interval(),
        opts,
    )

    assert result.success
    assert "hello123" in result.stdout


@skip_if_no_docker
@pytest.mark.slow
async def test_cwd(docker_sandbox) -> None:
    """Working directory is respected."""
    opts = ExecRemoteCommonOptions(cwd="/tmp")
    result = await exec_remote_awaitable(
        docker_sandbox, ["pwd"], docker_sandbox.default_polling_interval(), opts
    )

    assert result.success
    assert "/tmp" in result.stdout


@skip_if_no_docker
@pytest.mark.slow
async def test_input_string(docker_sandbox) -> None:
    """String input is passed to the process's stdin."""
    opts = ExecRemoteCommonOptions(input="hello from input\n")
    result = await exec_remote_awaitable(
        docker_sandbox, ["cat"], docker_sandbox.default_polling_interval(), opts
    )

    assert result.success
    assert "hello from input" in result.stdout


@skip_if_no_docker
@pytest.mark.slow
async def test_input_bytes(docker_sandbox) -> None:
    """Bytes input is decoded to UTF-8 and passed to stdin."""
    opts = ExecRemoteCommonOptions(input=b"bytes input\n")
    result = await exec_remote_awaitable(
        docker_sandbox, ["cat"], docker_sandbox.default_polling_interval(), opts
    )

    assert result.success
    assert "bytes input" in result.stdout


@skip_if_no_docker
@pytest.mark.slow
async def test_ack_seq_retransmit(docker_sandbox) -> None:
    """Resetting _last_seq simulates a lost response; server retransmits."""
    import anyio

    opts = ExecRemoteStreamingOptions(stdin_open=True)
    proc = await exec_remote_streaming(
        docker_sandbox, ["cat"], docker_sandbox.default_polling_interval(), opts
    )

    # Write and poll until cat echoes back, so the server has output to track
    await proc.write_stdin("hello\n")
    collected: list[ExecStdout | ExecStderr | ExecCompleted] = list(
        proc._pending_events
    )
    proc._pending_events.clear()
    for _ in range(20):
        result = await proc._poll()
        if result.stdout:
            collected.append(ExecStdout(data=result.stdout))
            break
        await anyio.sleep(0.1)

    assert any(isinstance(e, ExecStdout) and "hello" in e.data for e in collected), (
        f"Expected 'hello' in output, got {collected}"
    )
    seq_after_first = proc._last_seq
    assert seq_after_first > 0

    # Simulate lost response: reset ack_seq so server thinks we missed everything
    proc._last_seq = 0

    # Next write — server retransmits "hello" (unacked) plus new "world"
    await proc.write_stdin("world\n")
    retransmit_events = list(proc._pending_events)
    proc._pending_events.clear()
    for _ in range(20):
        result = await proc._poll()
        if result.stdout:
            retransmit_events.append(ExecStdout(data=result.stdout))
            break
        await anyio.sleep(0.1)

    retransmit_stdout = "".join(
        e.data for e in retransmit_events if isinstance(e, ExecStdout)
    )
    assert "hello" in retransmit_stdout, (
        f"Expected retransmit of unacked 'hello', got: {retransmit_stdout!r}"
    )
    assert "world" in retransmit_stdout

    await proc.close_stdin()
    _ = [event async for event in proc]
