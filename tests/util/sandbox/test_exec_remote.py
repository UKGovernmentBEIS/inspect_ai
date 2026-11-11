"""Tests for exec_remote.

Unit tests mock sandbox.exec() to test host-side logic (guards, kill behavior,
cancellation, accumulation). Integration tests (marked slow) run against a real
Docker container to verify the full host-to-container path.
"""

import asyncio
import contextlib
import json
import warnings
from collections.abc import Iterator
from typing import Any, Literal
from unittest.mock import AsyncMock, patch

import anyio
import pytest
import tenacity
from tenacity.wait import wait_none
from test_helpers.utils import skip_if_no_docker, skip_if_trio

import inspect_ai.util._sandbox.exec_remote as exec_remote_module
from inspect_ai.tool._sandbox_tools_utils.sandbox import (
    SandboxInjectionError,
    _inject_container_tools_code,
)
from inspect_ai.util._sandbox.context import (
    sandbox_default_context_var,
    sandbox_environments_context_var,
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
from inspect_ai.util._sandbox.identity import sandbox_identity
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


class TestPollRetryWait:
    async def test_poll_retry_wait_builds_without_warning(self) -> None:
        """Each poll builds its retry wait without tenacity's `initial` warning."""
        sandbox = _make_sandbox_mock([_start_response(), _poll_response()])

        with warnings.catch_warnings():
            warnings.filterwarnings("error", message="The 'initial' parameter")
            result = await exec_remote_awaitable(
                sandbox, ["cmd"], 5, ExecRemoteCommonOptions(poll_interval=0)
            )

        assert result.success is True


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

        assert [method for method, _ in sandbox.requests] == [
            "exec_remote_start",
            "exec_remote_kill_key",
        ]

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
# Start without a reply
# ============================================================================


class _GuestWithoutStartReply:
    """A fake tool server that starts the job but whose start reply never arrives.

    The start registers a running job under its key, then either waits until
    cancelled (`lose="hang"`) or raises the sandbox's timeout
    (`lose="timeout"`). exec_remote_kill_key marks the keyed job killed, after
    `kill_answer` is set when one is given (as the real server answers only
    once the job has terminated).
    """

    def __init__(
        self,
        lose: Literal["hang", "timeout"],
        kill_hangs: bool = False,
        kill_answer: anyio.Event | None = None,
    ) -> None:
        self.lose = lose
        self.kill_hangs = kill_hangs
        self.kill_answer = kill_answer
        self.kill_received = anyio.Event()
        self.jobs: dict[str, str] = {}
        self.kill_key_kwargs: list[dict[str, Any]] = []
        self.started = anyio.Event()
        self.sandbox = _mock_sandbox()
        self.sandbox.default_polling_interval.return_value = 5
        self.sandbox.no_events = _no_events_context
        self.sandbox.exec = AsyncMock(side_effect=self._exec)

    async def _exec(self, *args: Any, **kwargs: Any) -> ExecResult[str]:
        request = json.loads(kwargs["input"])
        job_key = request["params"]["job_key"]
        if request["method"] == "exec_remote_start":
            self.jobs[job_key] = "running"
            self.started.set()
            if self.lose == "timeout":
                raise SandboxTimeoutError("the start reply was lost.")
            await anyio.sleep_forever()
        assert request["method"] == "exec_remote_kill_key"
        self.kill_key_kwargs.append(kwargs)
        self.kill_received.set()
        if self.kill_hangs:
            await anyio.sleep_forever()
        if self.kill_answer is not None:
            await self.kill_answer.wait()
        killed = self.jobs.get(job_key) == "running"
        self.jobs[job_key] = "killed"
        return ExecResult(
            success=True, returncode=0, stdout=_rpc({"killed": killed}), stderr=""
        )


class TestStartWithoutReply:
    """A job whose start reply never arrives is killed by its key."""

    async def test_cancelled_start_kills_the_job(self) -> None:
        guest = _GuestWithoutStartReply(lose="hang")

        async with anyio.create_task_group() as tg:
            tg.start_soon(exec_remote_streaming, guest.sandbox, ["sleep", "999"], 5)
            await guest.started.wait()
            tg.cancel_scope.cancel()

        assert list(guest.jobs.values()) == ["killed"]
        # cleanup must not queue behind the commands it is cleaning up after
        assert guest.kill_key_kwargs[0]["concurrency"] is False
        assert guest.kill_key_kwargs[0]["timeout_retry"] is False

    async def test_caller_timeout_during_start_kills_the_job(self) -> None:
        guest = _GuestWithoutStartReply(lose="hang")

        with pytest.raises(TimeoutError):
            with anyio.fail_after(0.5):
                await exec_remote_streaming(guest.sandbox, ["sleep", "999"], 5)

        assert list(guest.jobs.values()) == ["killed"]

    async def test_timed_out_start_kills_the_job(self) -> None:
        guest = _GuestWithoutStartReply(lose="timeout")

        with pytest.raises(TimeoutError):
            await exec_remote_streaming(guest.sandbox, ["sleep", "999"], 5)

        assert list(guest.jobs.values()) == ["killed"]

    @pytest.mark.parametrize("lose", ["hang", "timeout"])
    async def test_start_cleanup_waits_for_the_kill_by_key_answer(
        self, lose: Literal["hang", "timeout"]
    ) -> None:
        """The error reaches the caller only after the server answers the kill."""
        kill_answer = anyio.Event()
        guest = _GuestWithoutStartReply(lose=lose, kill_answer=kill_answer)
        scope = anyio.CancelScope()
        finished = anyio.Event()

        async def start() -> None:
            with scope, contextlib.suppress(TimeoutError):
                await exec_remote_streaming(guest.sandbox, ["sleep", "999"], 5)
            finished.set()

        async with anyio.create_task_group() as tg:
            tg.start_soon(start)
            await guest.started.wait()
            scope.cancel()  # no effect once a timed-out start is cleaning up
            await guest.kill_received.wait()
            await anyio.wait_all_tasks_blocked()
            assert not finished.is_set()

            kill_answer.set()
            await finished.wait()

        assert list(guest.jobs.values()) == ["killed"]

    @skip_if_trio
    @pytest.mark.parametrize("cancel", ["task", "timeout"])
    async def test_native_asyncio_cancellation_waits_for_the_kill_by_key_answer(
        self, cancel: Literal["task", "timeout"]
    ) -> None:
        """Task.cancel() or asyncio.timeout() during cleanup does not interrupt it."""
        kill_answer = anyio.Event()
        guest = _GuestWithoutStartReply(lose="timeout", kill_answer=kill_answer)
        timeouts: list[asyncio.Timeout] = []

        async def start() -> None:
            async with asyncio.timeout(None) as timeout:
                timeouts.append(timeout)
                await exec_remote_streaming(guest.sandbox, ["sleep", "999"], 5)

        task = asyncio.ensure_future(start())
        await guest.kill_received.wait()
        if cancel == "task":
            task.cancel()
        else:
            timeouts[0].reschedule(asyncio.get_running_loop().time())
        await anyio.wait_all_tasks_blocked()
        assert not task.done()

        kill_answer.set()
        with pytest.raises(
            asyncio.CancelledError if cancel == "task" else TimeoutError
        ):
            await task
        assert list(guest.jobs.values()) == ["killed"]

    async def test_cancelled_starts_send_every_kill_without_waiting_for_replies(
        self,
    ) -> None:
        """Slow kill replies for some starts do not hold back the kills of others."""
        kill_answer = anyio.Event()
        guest = _GuestWithoutStartReply(lose="hang", kill_answer=kill_answer)
        starts = anyio.CancelScope()
        finished = anyio.Event()

        async def start_twelve() -> None:
            with starts:
                async with anyio.create_task_group() as tg:
                    for _ in range(12):
                        tg.start_soon(
                            exec_remote_streaming, guest.sandbox, ["sleep", "999"], 5
                        )
            finished.set()

        async with anyio.create_task_group() as tg:
            tg.start_soon(start_twelve)
            await anyio.wait_all_tasks_blocked()
            assert list(guest.jobs.values()) == ["running"] * 12

            starts.cancel()
            await anyio.wait_all_tasks_blocked()
            assert len(guest.kill_key_kwargs) == 12

            kill_answer.set()
            await finished.wait()

        assert list(guest.jobs.values()) == ["killed"] * 12

    async def test_kill_by_key_is_bounded(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(exec_remote_module, "KILL_KEY_TIMEOUT", 0.2)
        guest = _GuestWithoutStartReply(lose="timeout", kill_hangs=True)

        with anyio.fail_after(5):
            with pytest.raises(TimeoutError, match="start reply was lost"):
                await exec_remote_streaming(guest.sandbox, ["sleep", "999"], 5)

        assert len(guest.kill_key_kwargs) == 1
        assert "may still be running" in caplog.text


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
        self,
        options: ExecRemoteStreamingOptions,
        identity: tuple[str, str | None] | None = None,
        identity_sandbox: str = "default",
    ) -> dict[str, Any]:
        sandbox = _make_sandbox_mock([_start_response()])
        sandbox._tools_default_user = self._DEFAULT_USER
        envs_token = sandbox_environments_context_var.set(
            {"default": sandbox, "other": _mock_sandbox()}
        )
        default_token = sandbox_default_context_var.set("default")
        try:
            with (
                sandbox_identity(identity[0], cwd=identity[1], sandbox=identity_sandbox)
                if identity is not None
                else contextlib.nullcontext()
            ):
                await exec_remote_streaming(sandbox, ["cmd"], 5, options)
        finally:
            sandbox_default_context_var.reset(default_token)
            sandbox_environments_context_var.reset(envs_token)
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

    async def test_identity_scope_user_and_cwd_sent_when_omitted(self) -> None:
        params = await self._start_params(
            ExecRemoteStreamingOptions(), identity=("w-1", "/home/w-1")
        )
        assert params["user"] == "w-1"
        assert params["cwd"] == "/home/w-1"

    async def test_identity_scope_keeps_explicit_user_and_cwd(self) -> None:
        params = await self._start_params(
            ExecRemoteStreamingOptions(user="root", cwd="/srv"),
            identity=("w-1", "/home/w-1"),
        )
        assert params["user"] == "root"
        assert params["cwd"] == "/srv"

    async def test_identity_scope_for_another_sandbox_is_ignored(self) -> None:
        params = await self._start_params(
            ExecRemoteStreamingOptions(),
            identity=("w-1", "/home/w-1"),
            identity_sandbox="other",
        )
        assert params["user"] == self._DEFAULT_USER._asdict()
        assert "cwd" not in params

    @pytest.mark.parametrize("scoped", ["default", "other"])
    async def test_identity_scope_reaches_the_provider_behind_the_sample_proxy(
        self, scoped: str
    ) -> None:
        from test_helpers.sandbox import CannedSandbox

        from inspect_ai.util import sandbox

        provider = CannedSandbox.returning(ExecResult(True, 0, _start_response(), ""))
        provider._tools_injected = True
        provider._tools_default_user = self._DEFAULT_USER
        proxy = SandboxEnvironmentProxy(provider)
        envs_token = sandbox_environments_context_var.set(
            {
                "default": proxy,
                "other": SandboxEnvironmentProxy(
                    CannedSandbox.returning(ExecResult(True, 0, "", ""))
                ),
            }
        )
        default_token = sandbox_default_context_var.set("default")
        try:
            with sandbox_identity("w-1", cwd="/home/w-1", sandbox=scoped):
                # in a scope on `other`, sandbox() is `other`
                view = (sandbox() if scoped == "default" else proxy).as_type(
                    CannedSandbox
                )
                assert view is provider
                await view.exec_remote(["id"], ExecRemoteStreamingOptions())
        finally:
            sandbox_default_context_var.reset(default_token)
            sandbox_environments_context_var.reset(envs_token)
        [request] = provider.inputs
        assert isinstance(request, str)
        params = json.loads(request)["params"]
        if scoped == "default":
            assert (params["user"], params["cwd"]) == ("w-1", "/home/w-1")
        else:
            assert params["user"] == self._DEFAULT_USER._asdict()
            assert "cwd" not in params

    @pytest.mark.parametrize("tools_user", ["root", None], ids=["root", "rootless"])
    async def test_transport_runs_as_the_tools_user_in_a_scope(
        self, tools_user: str | None
    ) -> None:
        from test_helpers.sandbox import CannedSandbox

        provider = CannedSandbox.returning(ExecResult(True, 0, _start_response(), ""))
        proxy = SandboxEnvironmentProxy(provider)
        proxy._tools_injected = True
        proxy._tools_user = tools_user
        proxy._tools_default_user = self._DEFAULT_USER
        envs_token = sandbox_environments_context_var.set({"default": proxy})
        default_token = sandbox_default_context_var.set("default")
        try:
            with sandbox_identity("w-1"):
                await proxy.exec_remote(["id"], ExecRemoteStreamingOptions())
        finally:
            sandbox_default_context_var.reset(default_token)
            sandbox_environments_context_var.reset(envs_token)
        # the member's identity travels as the request's user, not the exec's
        [(_, exec_user)] = provider.exec_calls
        assert exec_user == tools_user
        [request] = provider.inputs
        assert isinstance(request, str)
        assert json.loads(request)["params"]["user"] == "w-1"


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
# Server wait window
# ============================================================================


def _poll_wait_start_response(pid: int = 42) -> str:
    """A start response from sandbox tools that support the poll `wait` param."""
    return _rpc({"pid": pid, "poll_wait": True})


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record the duration of each `anyio.sleep` call and return at once."""
    recorded: list[float] = []
    real_sleep = anyio.sleep

    async def record_sleep(delay: float) -> None:
        recorded.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(anyio, "sleep", record_sleep)
    return recorded


_RUNNING = _poll_response(state="running", exit_code=None)


class TestServerWait:
    async def test_old_server_gets_no_wait_and_idle_sleeps(
        self, sleeps: list[float]
    ) -> None:
        sandbox = _make_scripted_sandbox(
            [_start_response(42), _RUNNING, _RUNNING, _poll_response()]
        )
        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)

        events = [event async for event in proc]

        assert events == [ExecCompleted(exit_code=0)]
        assert all("wait" not in params for params in _polls(sandbox))
        assert sleeps == [5, 5]

    async def test_polls_wait_for_the_remaining_window_without_sleeps(
        self, sleeps: list[float]
    ) -> None:
        sandbox = _make_scripted_sandbox(
            [_poll_wait_start_response(42), _RUNNING, _RUNNING, _poll_response()]
        )
        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)

        events = [event async for event in proc]

        assert events == [ExecCompleted(exit_code=0)]
        waits = [params["wait"] for params in _polls(sandbox)]
        assert len(waits) == 3
        assert waits[0] > 5
        assert all(0 < wait <= 10 for wait in waits)
        assert waits == sorted(waits, reverse=True)
        assert sleeps == []

    async def test_wait_is_capped_at_half_the_poll_timeout(self) -> None:
        sandbox = _make_scripted_sandbox(
            [_poll_wait_start_response(42), _RUNNING, _poll_response()]
        )
        proc = await exec_remote_streaming(
            sandbox, ["cmd"], 5, ExecRemoteCommonOptions(poll_timeout=4)
        )

        _ = [event async for event in proc]

        assert [params["wait"] for params in _polls(sandbox)] == [2, 2]

    async def test_polls_sleep_without_wait_after_the_window(
        self, sleeps: list[float]
    ) -> None:
        sandbox = _make_scripted_sandbox(
            [_poll_wait_start_response(42), _RUNNING, _RUNNING, _poll_response()]
        )
        scripted_exec = sandbox.exec.side_effect
        proc: ExecRemoteProcess | None = None

        async def end_window_after_first_poll(
            *args: Any, **kwargs: Any
        ) -> ExecResult[str]:
            result = await scripted_exec(*args, **kwargs)
            if len(_polls(sandbox)) == 1:
                assert proc is not None
                proc._server_wait_end = 0
            return result

        sandbox.exec.side_effect = end_window_after_first_poll
        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)

        _ = [event async for event in proc]

        assert ["wait" in params for params in _polls(sandbox)] == [
            True,
            False,
            False,
        ]
        assert sleeps == [5, 5]

    async def test_stdin_open_process_gets_no_wait(self, sleeps: list[float]) -> None:
        sandbox = _make_scripted_sandbox(
            [_poll_wait_start_response(42), _RUNNING, _poll_response()]
        )
        proc = await exec_remote_streaming(
            sandbox, ["cmd"], 5, ExecRemoteStreamingOptions(stdin_open=True)
        )

        _ = [event async for event in proc]

        assert all("wait" not in params for params in _polls(sandbox))
        assert sleeps == [5]

    @staticmethod
    def _sandbox_with_blocking_poll() -> tuple[AsyncMock, list[str], anyio.Event]:
        """A sandbox that supports poll waits and never answers a poll."""
        methods: list[str] = []
        poll_started = anyio.Event()
        answers = {
            "exec_remote_start": _poll_wait_start_response(42),
            "exec_remote_kill": _kill_response(),
        }

        async def fake_exec(*args: Any, **kwargs: Any) -> ExecResult[str]:
            request = json.loads(kwargs["input"])
            methods.append(request["method"])
            if request["method"] == "exec_remote_poll":
                assert "wait" in request["params"]
                poll_started.set()
                await anyio.sleep_forever()
            return ExecResult(
                success=True, returncode=0, stdout=answers[request["method"]], stderr=""
            )

        sandbox = _mock_sandbox()
        sandbox.no_events = _no_events_context
        sandbox.exec = AsyncMock(side_effect=fake_exec)
        return sandbox, methods, poll_started

    async def test_cancellation_during_a_waiting_poll_kills_the_process(
        self,
    ) -> None:
        sandbox, methods, poll_started = self._sandbox_with_blocking_poll()
        proc = await exec_remote_streaming(sandbox, ["cmd"], 5)

        async def iterate() -> None:
            async for _ in proc:
                pass

        async with anyio.create_task_group() as tg:
            tg.start_soon(iterate)
            await poll_started.wait()
            tg.cancel_scope.cancel()

        assert methods == ["exec_remote_start", "exec_remote_poll", "exec_remote_kill"]

    async def test_timeout_during_a_waiting_poll_kills_the_process(self) -> None:
        sandbox, methods, _ = self._sandbox_with_blocking_poll()

        with pytest.raises(TimeoutError):
            await exec_remote_awaitable(
                sandbox, ["cmd"], 5, ExecRemoteAwaitableOptions(timeout=0.5)
            )

        assert methods == ["exec_remote_start", "exec_remote_poll", "exec_remote_kill"]


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


_ORPHAN_SLEEP = "86413"
"""Sleep duration that marks the job of the start-without-reply tests."""


async def _orphan_running(sandbox: Any) -> bool:
    return await _orphan_running_via(sandbox.exec)


async def _orphan_running_via(exec: Any) -> bool:
    # the bracket keeps this probe's own command line from matching
    pattern = f"{_ORPHAN_SLEEP[:-1]}[{_ORPHAN_SLEEP[-1]}]"
    result = await exec(
        ["sh", "-c", f"grep -l -a '{pattern}' /proc/[0-9]*/cmdline 2>/dev/null"]
    )
    return bool(result.stdout.strip())


@contextlib.contextmanager
def _start_reply_lost(sandbox: Any, lose: Literal["hang", "timeout"]) -> Iterator[Any]:
    """Run each exec_remote_start for real in the sandbox, then lose its reply."""
    real_exec = sandbox.exec
    started = anyio.Event()

    async def exec_losing_start_reply(*args: Any, **kwargs: Any) -> Any:
        result = await real_exec(*args, **kwargs)
        if "exec_remote_start" in (kwargs.get("input") or ""):
            started.set()
            if lose == "timeout":
                raise TimeoutError("the start reply was lost.")
            await anyio.sleep_forever()
        return result

    with patch.object(sandbox, "exec", exec_losing_start_reply):
        yield started


@skip_if_no_docker
@pytest.mark.slow
async def test_cancelled_start_kills_the_job(docker_sandbox) -> None:
    with _start_reply_lost(docker_sandbox, "hang") as started:
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                exec_remote_streaming, docker_sandbox, ["sleep", _ORPHAN_SLEEP], 5
            )
            await started.wait()
            assert await _orphan_running(docker_sandbox)
            tg.cancel_scope.cancel()

    assert not await _orphan_running(docker_sandbox)


@skip_if_no_docker
@pytest.mark.slow
async def test_timed_out_start_kills_the_job(docker_sandbox) -> None:
    with _start_reply_lost(docker_sandbox, "timeout"):
        with pytest.raises(TimeoutError):
            await exec_remote_streaming(docker_sandbox, ["sleep", _ORPHAN_SLEEP], 5)

    assert not await _orphan_running(docker_sandbox)


_BACKPRESSURED_INPUT = "x" * (512 * 1024)
"""More input than a pipe buffers, so the start waits on a command that never reads it."""


async def _wait_for_orphan(sandbox: Any) -> None:
    with anyio.fail_after(30):
        while not await _orphan_running(sandbox):
            await anyio.sleep(0.1)


@contextlib.contextmanager
def _start_times_out_once_running(sandbox: Any) -> Iterator[None]:
    """Time out each exec_remote_start once its job runs, with the start unfinished."""
    real_exec = sandbox.exec

    async def exec_timing_out_start(*args: Any, **kwargs: Any) -> Any:
        if "exec_remote_start" not in (kwargs.get("input") or ""):
            return await real_exec(*args, **kwargs)
        async with anyio.create_task_group() as tg:
            tg.start_soon(lambda: real_exec(*args, **kwargs))
            with anyio.fail_after(30):
                while not await _orphan_running_via(real_exec):
                    await anyio.sleep(0.1)
            tg.cancel_scope.cancel()
        raise TimeoutError("the start timed out.")

    with patch.object(sandbox, "exec", exec_timing_out_start):
        yield


@skip_if_no_docker
@pytest.mark.slow
async def test_cancelled_start_with_backpressured_input_kills_the_job(
    docker_sandbox,
) -> None:
    async with anyio.create_task_group() as tg:
        tg.start_soon(
            exec_remote_streaming,
            docker_sandbox,
            ["sleep", _ORPHAN_SLEEP],
            5,
            ExecRemoteStreamingOptions(input=_BACKPRESSURED_INPUT),
        )
        await _wait_for_orphan(docker_sandbox)
        tg.cancel_scope.cancel()

    assert not await _orphan_running(docker_sandbox)


@skip_if_no_docker
@pytest.mark.slow
async def test_timed_out_start_with_backpressured_input_kills_the_job(
    docker_sandbox,
) -> None:
    with _start_times_out_once_running(docker_sandbox):
        with pytest.raises(TimeoutError):
            await exec_remote_awaitable(
                docker_sandbox,
                ["sleep", _ORPHAN_SLEEP],
                5,
                ExecRemoteAwaitableOptions(input=_BACKPRESSURED_INPUT),
            )

    assert not await _orphan_running(docker_sandbox)


@skip_if_no_docker
@pytest.mark.slow
async def test_timed_out_start_waits_for_a_job_the_server_is_killing(
    docker_sandbox,
) -> None:
    """The kill by key must not return while the failed start's own kill waits.

    The command ignores SIGTERM and closes stdin, so the server's start fails
    and its kill waits seconds before SIGKILL; the start times out meanwhile.
    """
    # $((...)) keeps the marker out of the shell's own command line, so the
    # probe sees the job only once stdin is closed and the server is killing it
    sleep = f"$(({int(_ORPHAN_SLEEP) - 1}+1))"
    with _start_times_out_once_running(docker_sandbox):
        with pytest.raises(TimeoutError):
            await exec_remote_streaming(
                docker_sandbox,
                ["exec", "sh", "-c", f"trap '' TERM; exec 0<&-; exec sleep {sleep}"],
                5,
                ExecRemoteStreamingOptions(input=_BACKPRESSURED_INPUT),
            )

    assert not await _orphan_running(docker_sandbox)


@contextlib.contextmanager
def _kill_key_replies(sandbox: Any) -> Iterator[list[str]]:
    """Record the raw sandbox reply (or error) of each exec_remote_kill_key."""
    real_exec = sandbox.exec
    replies: list[str] = []

    async def exec_recording_kill_key(*args: Any, **kwargs: Any) -> Any:
        if "exec_remote_kill_key" not in (kwargs.get("input") or ""):
            return await real_exec(*args, **kwargs)
        try:
            result = await real_exec(*args, **kwargs)
        except BaseException as ex:
            replies.append(repr(ex))
            raise
        replies.append(repr(result))
        return result

    with patch.object(sandbox, "exec", exec_recording_kill_key):
        yield replies


# pid, process group, state and command line of every process but this shell;
# the fields after the ")" that ends the command name are state, ppid and pgrp
_PROCESS_LIST = r"""
for d in /proc/[0-9]*; do
  [ "${d#/proc/}" = "$$" ] && continue
  s=$(sed 's/.*) //' "$d/stat" 2>/dev/null) || continue
  set -- $s
  printf '%s pgid=%s state=%s %s\n' "${d#/proc/}" "$3" "$1" \
    "$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null)"
done
"""

_SERVER_STDERR_TAIL = (
    "for f in $(find / -xdev -name server-stderr.log 2>/dev/null); do "
    'echo "== $f"; tail -c 4000 "$f"; done'
)


async def _orphan_report(
    sandbox: Any, start_error: BaseException, kill_key_replies: list[str]
) -> str:
    """Describe the sandbox state when a failed start left its job running."""
    processes = await sandbox.exec(["sh", "-c", _PROCESS_LIST])
    server_stderr = await sandbox.exec(["sh", "-c", _SERVER_STDERR_TAIL])
    return "\n".join(
        [
            f"sleep {_ORPHAN_SLEEP} still runs after the failed start.",
            f"start error: {start_error!r}",
            f"kill_key replies: {kill_key_replies}",
            "processes:",
            processes.stdout + processes.stderr,
            "server stderr:",
            (server_stderr.stdout + server_stderr.stderr) or "(none found)",
        ]
    )


@skip_if_no_docker
@pytest.mark.slow
async def test_start_whose_command_closes_stdin_kills_the_job(docker_sandbox) -> None:
    with _kill_key_replies(docker_sandbox) as kill_key_replies:
        with pytest.raises(RuntimeError, match="Connection lost") as start_error:
            await exec_remote_streaming(
                docker_sandbox,
                # exec so that no outer shell keeps stdin open
                ["exec", "sh", "-c", f"exec 0<&-; exec sleep {_ORPHAN_SLEEP}"],
                5,
                ExecRemoteStreamingOptions(input=_BACKPRESSURED_INPUT),
            )

    # The job has survived in CI but never locally; the report records what
    # the kill path saw (meridianlabs-ai/inspect_ai#622).
    if await _orphan_running(docker_sandbox):
        pytest.fail(
            await _orphan_report(docker_sandbox, start_error.value, kill_key_replies)
        )


@skip_if_no_docker
@pytest.mark.slow
async def test_kill_by_key_before_start_refuses_the_start(docker_sandbox) -> None:
    proc = ExecRemoteProcess(
        docker_sandbox, ["sleep", _ORPHAN_SLEEP], ExecRemoteCommonOptions(), 5
    )

    await proc._kill_key()
    with pytest.raises(RuntimeError, match="killed before it started"):
        await proc._start()

    assert not await _orphan_running(docker_sandbox)
