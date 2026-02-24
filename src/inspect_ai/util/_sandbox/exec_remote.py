"""ExecRemote - Asynchronous command execution with streaming output.

This module provides the host-side implementation for exec_remote, enabling
long-running commands in sandbox environments with streaming output.
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeVar, cast

import anyio
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

from inspect_ai._util._json_rpc import GenericJSONRPCErrorMapper, exec_model_request

from ._cli import SANDBOX_CLI
from ._json_rpc_transport import SandboxJSONRPCTransport

if TYPE_CHECKING:
    from .._subprocess import ExecResult
    from .environment import SandboxEnvironment


# ============================================================================
# Event Types
# ============================================================================


class ExecRemoteEvent:
    """Base class for all events yielded by ExecRemoteProcess."""

    Stdout: ClassVar[type[Stdout]]
    """A chunk of stdout data from the running process."""

    Stderr: ClassVar[type[Stderr]]
    """A chunk of stderr data from the running process."""

    Completed: ClassVar[type[Completed]]
    """Process completed (successfully or with error)."""

    type: ClassVar[str]
    """Event type discriminator ("stdout", "stderr", or "completed")."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        setattr(ExecRemoteEvent, cls.__name__, cls)


@dataclass
class Stdout(ExecRemoteEvent):
    """A chunk of stdout data from the running process."""

    type: ClassVar[str] = "stdout"
    """Event type discriminator."""

    data: str
    """The stdout data."""


@dataclass
class Stderr(ExecRemoteEvent):
    """A chunk of stderr data from the running process."""

    type: ClassVar[str] = "stderr"
    """Event type discriminator."""

    data: str
    """The stderr data."""


@dataclass
class Completed(ExecRemoteEvent):
    """Process completed (successfully or with error)."""

    type: ClassVar[str] = "completed"
    """Event type discriminator."""

    exit_code: int
    """The process exit code (0 = success)"""

    @property
    def success(self) -> bool:
        """True if the process exited successfully (exit code 0)."""
        return self.exit_code == 0


# ============================================================================
# Options
# ============================================================================


@dataclass
class ExecRemoteCommonOptions:
    """Common options for exec_remote() command execution.

    This base class contains options valid for both streaming and awaitable
    modes. Use ExecRemoteStreamingOptions or ExecRemoteAwaitableOptions for
    mode-specific options.
    """

    input: str | bytes | None = None
    """Standard input to send to the command"""

    cwd: str | None = None
    """Working directory for command execution"""

    env: dict[str, str] | None = None
    """Additional environment variables"""

    user: str | None = None
    """User to run the command as"""

    poll_interval: float | None = None
    """Interval between poll requests in seconds"""

    concurrency: bool = True
    """For sandboxes that run locally, request that the `concurrency()`
    function be used to throttle concurrent subprocesses."""


@dataclass
class ExecRemoteStreamingOptions(ExecRemoteCommonOptions):
    """Options for exec_remote() in streaming mode (stream=True)."""

    stdin_open: bool = False
    """If True, keep stdin open after writing initial input, enabling write_stdin()
    and close_stdin() on the returned ExecRemoteProcess. If False (default), stdin
    is closed immediately after writing initial input (or not opened at all)"""


@dataclass
class ExecRemoteAwaitableOptions(ExecRemoteCommonOptions):
    """Options for exec_remote() in awaitable mode (stream=False).

    Not yet implemented:
        timeout_retry: Retry logic on timeout (as in exec()) is not yet
            supported. When added, it will only apply to awaitable mode.
    """

    timeout: int | None = None
    """Maximum execution time in seconds. On timeout, the process is killed and
    TimeoutError is raised"""


# ============================================================================
# JSON-RPC Response Types (mirrors server-side types)
# ============================================================================


class _StartResult(BaseModel):
    """Result from exec_remote_start."""

    pid: int


class _PollResult(BaseModel):
    """Result from exec_remote_poll."""

    state: Literal["running", "completed", "killed"]
    exit_code: int | None = None
    stdout: str
    stderr: str


class _KillResult(BaseModel):
    """Result from exec_remote_kill."""

    stdout: str
    stderr: str


class _WriteStdinResult(BaseModel):
    """Result from exec_remote_write_stdin."""

    stdout: str
    stderr: str


class _CloseStdinResult(BaseModel):
    """Result from exec_remote_close_stdin."""

    stdout: str
    stderr: str


# ============================================================================
# Constants
# ============================================================================

MIN_POLL_INTERVAL = 5

RPC_TIMEOUT = 30
"""Timeout for individual JSON-RPC calls in seconds."""

T = TypeVar("T", bound=BaseModel)


class ExecRemoteProcess:
    r"""Handle to a running exec_remote process.

    This class is an async iterator that yields events as they arrive.
    It can only be iterated once (single-use iterator pattern).

    Usage patterns:

    1. Streaming: iterate over the process directly
       ```python
       proc = await sandbox.exec_remote(["cmd"])
       async for event in proc:
           match event:
               case ExecRemoteEvent.Stdout(data=data): print(data)
               case ExecRemoteEvent.Completed(exit_code=code): print(f"Done: {code}")
       ```

    2. Fire-and-forget with explicit kill:
       ```python
       proxy = await sandbox.exec_remote(["./proxy"])
       # ... do other work ...
       await proxy.kill()  # terminate when done
       ```

    3. Interactive stdin (requires stdin_open=True):
       ```python
       opts = ExecRemoteStreamingOptions(stdin_open=True)
       proc = await sandbox.exec_remote(["cat"], opts)
       await proc.write_stdin("hello\n")
       await proc.write_stdin("world\n")
       await proc.close_stdin()  # signal EOF
       async for event in proc:
           ...
       ```
    """

    def __init__(
        self,
        sandbox: SandboxEnvironment,
        cmd: list[str],
        options: ExecRemoteStreamingOptions | ExecRemoteCommonOptions,
        sandbox_default_poll_interval: float,
    ) -> None:
        """Initialize an ExecRemoteProcess.

        Args:
            sandbox: The sandbox environment where the process will run.
            cmd: Command and arguments to execute.
            options: Execution options.
            sandbox_default_poll_interval: Default poll interval in seconds,
                provided by the sandbox (e.g. from _default_poll_interval()).
        """
        self._sandbox = sandbox
        self._cmd = cmd
        self._options = options
        self._poll_interval = max(
            MIN_POLL_INTERVAL, options.poll_interval or sandbox_default_poll_interval
        )
        self._pid: int | None = None
        self._killed = False
        self._completed = False
        self._iteration_started = False
        self._pending_events: list[ExecRemoteEvent] = []
        self._transport = SandboxJSONRPCTransport(sandbox, SANDBOX_CLI)

    @property
    def pid(self) -> int:
        """Return the process ID."""
        if self._pid is None:
            raise RuntimeError("Process has not been submitted yet")
        return self._pid

    # -------------------------------------------------------------------------
    # RPC helpers
    # -------------------------------------------------------------------------

    async def _rpc(
        self, method: str, params: dict[str, object], result_type: type[T]
    ) -> T:
        """Make an RPC call to the sandbox."""
        return await exec_model_request(
            method=method,
            params=params,
            result_type=result_type,
            transport=self._transport,
            error_mapper=GenericJSONRPCErrorMapper,
            timeout=RPC_TIMEOUT,
            user=self._options.user,
            concurrency=self._options.concurrency,
        )

    async def _start(self) -> None:
        """Submit the job to the sandbox."""
        # Build params, converting bytes input to string if needed
        params: dict[str, object] = {"command": shlex.join(self._cmd)}
        if self._options.input is not None:
            if isinstance(self._options.input, bytes):
                params["input"] = self._options.input.decode("utf-8")
            else:
                params["input"] = self._options.input
        if (
            isinstance(self._options, ExecRemoteStreamingOptions)
            and self._options.stdin_open
        ):
            params["stdin_open"] = True
        if self._options.env:
            params["env"] = self._options.env
        if self._options.cwd:
            params["cwd"] = self._options.cwd

        result = await self._rpc("exec_remote_start", params, _StartResult)
        self._pid = result.pid

    # -------------------------------------------------------------------------
    # Async Iterator Protocol
    # -------------------------------------------------------------------------

    def __aiter__(self) -> "ExecRemoteProcess":
        """Return self as the async iterator.

        This class implements the async iterator protocol directly.
        It can only be iterated once - subsequent iterations will raise RuntimeError.
        """
        if self._iteration_started:
            raise RuntimeError("ExecRemoteProcess can only be iterated once")
        self._iteration_started = True
        return self

    async def __anext__(self) -> ExecRemoteEvent:
        """Return the next event from the process.

        Yields Stdout and Stderr events as output becomes available,
        then yields a final Completed event when the process terminates.

        Note: After the Completed event is yielded, the job is automatically
        cleaned up on the server side.

        If cancelled, the process will be killed before re-raising the exception.

        Raises:
            StopAsyncIteration: When the process has completed or been killed.
            RuntimeError: If the process has not been submitted yet.
        """
        if self._pid is None:
            raise RuntimeError("Process has not been submitted yet")

        # Return any pending events first
        if self._pending_events:
            return self._pending_events.pop(0)

        # If already in terminal state, stop iteration
        if self._completed or self._killed:
            raise StopAsyncIteration

        try:
            while True:
                # Perform the poll
                result = await self._poll()

                # Collect events from this poll
                events: list[ExecRemoteEvent] = []
                if result.stdout:
                    events.append(Stdout(data=result.stdout))
                if result.stderr:
                    events.append(Stderr(data=result.stderr))

                # Check for terminal state
                if result.state == "completed":
                    self._completed = True
                    if result.exit_code is None:
                        raise RuntimeError(
                            "Server returned completed state without exit_code"
                        )
                    events.append(Completed(exit_code=result.exit_code))
                elif result.state == "killed":
                    # Process was killed (possibly by another call to kill())
                    self._killed = True
                    # Don't yield Completed for killed processes - kill() discards output

                # If we have events, return the first and queue the rest
                if events:
                    self._pending_events = events[1:]
                    return events[0]

                # If killed with no events, stop iteration
                if self._killed:
                    raise StopAsyncIteration

                # Still running with no output, wait before polling again
                await anyio.sleep(self._poll_interval)

        except anyio.get_cancelled_exc_class():
            # Kill the process on cancellation to avoid leaving orphaned processes.
            with anyio.CancelScope(shield=True):
                await self.kill()
            raise

    async def _poll(self) -> _PollResult:
        @retry(
            wait=wait_exponential_jitter(initial=2),
            stop=(stop_after_attempt(5) | stop_after_delay(30)),
            retry=retry_if_exception(lambda e: isinstance(e, RuntimeError)),
        )
        async def poll() -> _PollResult:
            from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy

            sandbox_proxy = cast(SandboxEnvironmentProxy, self._transport.sandbox)
            with sandbox_proxy.no_events():
                return await self._rpc(
                    "exec_remote_poll", {"pid": self._pid}, _PollResult
                )

        return await poll()

    def _enqueue_output(self, stdout: str, stderr: str) -> None:
        """Enqueue any non-empty output as pending events for the iterator."""
        if stdout:
            self._pending_events.append(Stdout(data=stdout))
        if stderr:
            self._pending_events.append(Stderr(data=stderr))

    async def write_stdin(self, data: str | bytes) -> None:
        """Write data to the process's stdin.

        Requires that the process was started with stdin_open=True in
        ExecRemoteStreamingOptions.

        Args:
            data: Data to write. Bytes are decoded to UTF-8.

        Raises:
            RuntimeError: If stdin_open was not set, the process has not
                been started yet, or the process has already terminated.
        """
        if not (
            isinstance(self._options, ExecRemoteStreamingOptions)
            and self._options.stdin_open
        ):
            raise RuntimeError(
                "write_stdin() requires stdin_open=True in ExecRemoteStreamingOptions"
            )
        if self._pid is None:
            raise RuntimeError("Process has not been submitted yet")
        if self._completed or self._killed:
            raise RuntimeError("Cannot write to stdin: process has terminated")

        if isinstance(data, bytes):
            data = data.decode("utf-8")

        result = await self._rpc(
            "exec_remote_write_stdin",
            {"pid": self._pid, "data": data},
            _WriteStdinResult,
        )
        self._enqueue_output(result.stdout, result.stderr)

    async def close_stdin(self) -> None:
        """Close the process's stdin to signal EOF.

        Requires that the process was started with stdin_open=True in
        ExecRemoteStreamingOptions. Idempotent: calling after stdin is already
        closed is a no-op.

        Raises:
            RuntimeError: If stdin_open was not set, or the process has not
                been started yet.
        """
        if not (
            isinstance(self._options, ExecRemoteStreamingOptions)
            and self._options.stdin_open
        ):
            raise RuntimeError(
                "close_stdin() requires stdin_open=True in ExecRemoteStreamingOptions"
            )
        if self._pid is None:
            raise RuntimeError("Process has not been submitted yet")
        if self._completed or self._killed:
            return

        result = await self._rpc(
            "exec_remote_close_stdin",
            {"pid": self._pid},
            _CloseStdinResult,
        )
        self._enqueue_output(result.stdout, result.stderr)

    async def kill(self) -> None:
        """Terminate the process.

        Any output buffered since the last poll is enqueued as pending events
        so the async iterator can yield them before StopAsyncIteration.

        If the process has already completed or been killed, this is a no-op.
        """
        if self._pid is None or self._completed or self._killed:
            return

        self._killed = True
        try:
            result = await self._rpc(
                "exec_remote_kill", {"pid": self._pid}, _KillResult
            )
            self._enqueue_output(result.stdout, result.stderr)
        except Exception:
            logging.debug(
                f"exec_remote kill RPC failed for pid {self._pid}", exc_info=True
            )


# ============================================================================
# Factory Functions
# ============================================================================


async def exec_remote_streaming(
    sandbox: SandboxEnvironment,
    cmd: list[str],
    sandbox_default_poll_interval: float,
    options: ExecRemoteStreamingOptions | ExecRemoteCommonOptions | None = None,
) -> ExecRemoteProcess:
    """Create and start an exec_remote process for streaming.

    Submits the start command to the sandbox and returns only after the process
    has been successfully launched (i.e. after the exec_remote_start RPC completes
    and a PID has been assigned).

    Args:
        sandbox: The sandbox environment to run the command in.
        cmd: Command and arguments to execute.
        sandbox_default_poll_interval: Default poll interval in seconds,
            provided by the sandbox (e.g. from _default_poll_interval()).
        options: Execution options.

    Returns:
        ExecRemoteProcess handle that can be iterated for events, or killed.
        The process is guaranteed to have been started when this returns.
    """
    proc = ExecRemoteProcess(
        sandbox,
        cmd,
        options or ExecRemoteCommonOptions(),
        sandbox_default_poll_interval,
    )
    await proc._start()
    return proc


async def exec_remote_awaitable(
    sandbox: SandboxEnvironment,
    cmd: list[str],
    sandbox_default_poll_interval: float,
    options: ExecRemoteAwaitableOptions | ExecRemoteCommonOptions | None = None,
) -> ExecResult[str]:
    """Run a command and return the result without streaming.

    Submits the command, polls until completion, and returns ExecResult.
    If cancelled or timed out, the process will be killed.

    Each output stream (stdout and stderr) is limited to 10 MiB. If output
    exceeds this limit, only the most recent 10 MiB is kept.

    Args:
        sandbox: The sandbox environment to run the command in.
        cmd: Command and arguments to execute.
        sandbox_default_poll_interval: Default poll interval in seconds,
            provided by the sandbox (e.g. from _default_poll_interval()).
        options: Execution options.

    Returns:
        ExecResult[str] with success, returncode, stdout, and stderr.

    Raises:
        TimeoutError: If options.timeout is set and the command exceeds it.
    """
    from .._subprocess import CircularByteBuffer
    from .._subprocess import ExecResult as ExecResultClass
    from .limits import SandboxEnvironmentLimits

    opts = options or ExecRemoteCommonOptions()
    proc = await exec_remote_streaming(
        sandbox, cmd, sandbox_default_poll_interval, opts
    )

    # Accumulate output chunks with memory limiting
    output_limit = SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE
    stdout_buffer = CircularByteBuffer(output_limit)
    stderr_buffer = CircularByteBuffer(output_limit)

    timeout = opts.timeout if isinstance(opts, ExecRemoteAwaitableOptions) else None

    try:
        with anyio.fail_after(timeout):
            async for event in proc:
                if isinstance(event, Stdout):
                    stdout_buffer.write(event.data.encode("utf-8"))
                elif isinstance(event, Stderr):
                    stderr_buffer.write(event.data.encode("utf-8"))
                elif isinstance(event, Completed):
                    return ExecResultClass[str](
                        success=event.success,
                        returncode=event.exit_code,
                        stdout=stdout_buffer.getvalue().decode(
                            "utf-8", errors="replace"
                        ),
                        stderr=stderr_buffer.getvalue().decode(
                            "utf-8", errors="replace"
                        ),
                    )
    except TimeoutError:
        # Kill the process (the cancellation handler in __anext__ already
        # does this, but we call it explicitly in case the timeout fires
        # between iterations rather than inside __anext__)
        with anyio.CancelScope(shield=True):
            await proc.kill()
        raise

    # If we get here, the process was killed (no Completed event)
    return ExecResultClass[str](
        success=False,
        returncode=-1,
        stdout=stdout_buffer.getvalue().decode("utf-8", errors="replace"),
        stderr=stderr_buffer.getvalue().decode("utf-8", errors="replace"),
    )
