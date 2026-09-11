import contextlib
import functools
import io
import os
import shlex
from collections import deque
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from subprocess import DEVNULL, PIPE
from typing import Generic, Literal, TypeVar, Union, overload

import anyio
from anyio import (
    BrokenResourceError,
    ClosedResourceError,
    create_task_group,
    open_process,
)
from anyio.abc import ByteReceiveStream, ByteSendStream, Process

from inspect_ai._util._async import tg_collect
from inspect_ai._util.cpu import effective_cpu_count
from inspect_ai._util.trace import trace_action

from ._concurrency import concurrency as concurrency_manager
from ._concurrency import get_or_create_semaphore, register_subprocess_limiter

logger = getLogger(__name__)

T = TypeVar("T", str, bytes)


@dataclass
class ExecResult(Generic[T]):
    """Execution result from call to `subprocess()`."""

    success: bool
    """Did the process exit with success."""

    returncode: int
    """Return code from process exit."""

    stdout: T
    """Contents of stdout."""

    stderr: T
    """Contents of stderr."""


@dataclass(frozen=True)
class SubprocessRun(Generic[T]):
    """Result of `run_subprocess()`: the `ExecResult` plus stdin delivery status."""

    result: ExecResult[T]
    """The command's result, as `subprocess()` would return it."""

    stdin_written: bool
    """Whether `input` was fully written to the child's stdin.

    Trivially `True` when no input was given. `False` means the write failed
    because the child had already exited or closed its stdin; that can happen
    at any input size and which side wins is timing dependent. `result` still
    carries the child's exit status and output. `True` means the write
    completed, not that the child read the input: input that fits the OS pipe
    buffer sits there whether or not the child ever reads it.
    """


@overload
# type: ignore
async def subprocess(
    args: str | list[str],
    text: Literal[True] = True,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    output_limit: int | None = None,
    timeout: int | None = None,
    concurrency: bool = True,
) -> ExecResult[str]: ...


@overload
async def subprocess(
    args: str | list[str],
    text: Literal[False] = False,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    output_limit: int | None = None,
    timeout: int | None = None,
    concurrency: bool = True,
) -> ExecResult[bytes]: ...


async def subprocess(
    args: str | list[str],
    text: bool = True,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    output_limit: int | None = None,
    timeout: int | None = None,
    concurrency: bool = True,
) -> Union[ExecResult[str], ExecResult[bytes]]:
    """Execute and wait for a subprocess.

    Convenience method for solvers, scorers, and tools to launch
    subprocesses. Automatically enforces a limit on concurrent
    subprocesses (defaulting to the number of processors available
    to the eval, but controllable via the `max_subprocesses` eval
    config option).

    Args:
       args (str | list[str]): Command and arguments to execute.
       text (bool): Return stdout and stderr as text (defaults to True)
       input (str | bytes | memoryview | None): Optional stdin
          for subprocess.
       cwd (str | Path | None): Switch to directory for execution.
       env (dict[str, str]): Additional environment variables.
       capture_output (bool): Capture stderr and stdout into ExecResult
          (if False, then output is redirected to parent stderr/stdout
          or to logging if INSPECT_SUBPROCESS_REDIRECT_TO_LOGGER is set)
       output_limit (int | None): Maximum bytes to retain from stdout/stderr.
          If output exceeds this limit, only the most recent bytes are kept
          (older output is discarded). The process continues to completion.
       timeout (int | None): Timeout. If the timeout expires then
          a `TimeoutError` will be raised.
       concurrency: Request that the `concurrency()` function is used
          to throttle concurrent subprocesses.

    Returns:
       Subprocess result (text or binary depending on `text` param)

    Raises:
       TimeoutError: If the specified `timeout` expires.
    """
    run = await run_subprocess(
        args,
        text,
        input=input,
        cwd=cwd,
        env=env,
        capture_output=capture_output,
        output_limit=output_limit,
        timeout=timeout,
        concurrency=concurrency,
    )
    return run.result


@overload
async def run_subprocess(
    args: str | list[str],
    text: Literal[True] = True,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    output_limit: int | None = None,
    timeout: int | None = None,
    concurrency: bool = True,
) -> SubprocessRun[str]: ...


@overload
async def run_subprocess(
    args: str | list[str],
    text: Literal[False],
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    output_limit: int | None = None,
    timeout: int | None = None,
    concurrency: bool = True,
) -> SubprocessRun[bytes]: ...


@overload
async def run_subprocess(
    args: str | list[str],
    text: bool,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    output_limit: int | None = None,
    timeout: int | None = None,
    concurrency: bool = True,
) -> SubprocessRun[str] | SubprocessRun[bytes]: ...


async def run_subprocess(
    args: str | list[str],
    text: bool = True,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    output_limit: int | None = None,
    timeout: int | None = None,
    concurrency: bool = True,
) -> SubprocessRun[str] | SubprocessRun[bytes]:
    """`subprocess()` that also reports whether `input` was fully written to the child's stdin.

    A child that exits before reading its stdin is not an error for
    `subprocess()` (its `ExecResult` says what happened), but some callers
    need to know that it happened: the Docker compose CLI does this when
    dockerd fails the exec attach under load, and such a command should be
    retried rather than have its result believed. Same arguments, raises and
    semantics as `subprocess()`; see there.
    """
    # resolve input
    input = (
        input.encode()
        if isinstance(input, str)
        else bytes(input)
        if input is not None
        else None
    )

    async def run_command() -> SubprocessRun[str] | SubprocessRun[bytes]:
        redirect_output_to_logger = (
            not capture_output
            and os.environ.get("INSPECT_SUBPROCESS_REDIRECT_TO_LOGGER") is not None
        )
        process = await open_process(
            args,
            stdin=PIPE if input else DEVNULL,
            stdout=PIPE if (capture_output or redirect_output_to_logger) else None,
            stderr=PIPE if (capture_output or redirect_output_to_logger) else None,
            cwd=cwd,
            env={**os.environ, **(env or {})},
        )
        try:
            if redirect_output_to_logger:
                consume = _log_stream
            else:
                consume = functools.partial(_read_stream, output_limit=output_limit)

            stdin_written = True

            async def write_stdin() -> bytes:
                nonlocal stdin_written
                stdin_written = await _write_stdin(process.stdin, input)
                return bytes()

            # Feed stdin alongside the readers rather than before them: a child
            # that fills its stdout pipe before reading stdin would otherwise
            # block us on the write while we block it on the read.
            io_tasks: list[Callable[[], Awaitable[bytes]]] = [
                functools.partial(consume, process.stdout),
                functools.partial(consume, process.stderr),
                write_stdin,
            ]
            stdout, stderr, _ = await tg_collect(io_tasks)

            returncode = await process.wait()
            success = returncode == 0
            if text:
                return SubprocessRun(
                    result=ExecResult[str](
                        success=success,
                        returncode=returncode,
                        stdout=stdout.decode(errors="replace")
                        if capture_output
                        else "",
                        stderr=stderr.decode(errors="replace")
                        if capture_output
                        else "",
                    ),
                    stdin_written=stdin_written,
                )
            else:
                return SubprocessRun(
                    result=ExecResult[bytes](
                        success=success,
                        returncode=returncode,
                        stdout=stdout if capture_output else bytes(),
                        stderr=stderr if capture_output else bytes(),
                    ),
                    stdin_written=stdin_written,
                )
        # Handle cancellation before aclose() is called to avoid deadlock.
        except anyio.get_cancelled_exc_class():
            await gracefully_terminate_cancelled_subprocess(process)
            raise
        finally:
            # Inlined process.aclose() with a bounded final wait. anyio's
            # Process.aclose() re-shields and does an unbounded
            # `await self.wait()` on its exception path; if asyncio's child
            # watcher misses this process's exit (a known race under heavy
            # subprocess churn — symptom: `unix_events.py: exit status already
            # read`), that wait never resolves and the shield makes it
            # uncancellable, deadlocking the caller's task group on teardown.
            with anyio.CancelScope(shield=True):
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        with contextlib.suppress(Exception):
                            await stream.aclose()
                # Reach here on normal return (process already exited),
                # cancellation (gracefully_terminate already SIGKILLed), or
                # any other exception in the body — the last case can leave a
                # live, never-signalled process. anyio's aclose() handled that
                # by re-shield + kill(); preserve that here so the wait is
                # actually post-SIGKILL on every path.
                if process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                with anyio.move_on_after(LOST_SUBPROCESS_WAIT_TIMEOUT) as scope:
                    await process.wait()
                if scope.cancelled_caught:
                    _warn_lost_subprocess(process, "aclose")

    # wrapper for run command that implements timeout
    async def run_command_timeout() -> SubprocessRun[str] | SubprocessRun[bytes]:
        # wrap in timeout handler if requested
        if timeout is not None:
            with anyio.fail_after(timeout):
                # run_command() handles terminating the process if it is cancelled.
                return await run_command()
        else:
            return await run_command()

    # run command. `resizable=True` backs the limit with a ResizableLimiter so
    # the control channel's modify-limits directive can retune max_subprocesses
    # mid-eval (see design/ctl/control-channel.md phase 3); registered before
    # acquiring so a retune lands even while every slot is held.
    concurrency_ctx: contextlib.AbstractAsyncContextManager[object]
    if concurrency:
        register_subprocess_limiter(
            await get_or_create_semaphore(
                "subprocesses",
                max_subprocesses_context_var.get(),
                key=None,
                visible=True,
                resizable=True,
            )
        )
        concurrency_ctx = concurrency_manager(
            "subprocesses", max_subprocesses_context_var.get(), resizable=True
        )
    else:
        concurrency_ctx = contextlib.nullcontext()
    async with concurrency_ctx:
        message = args if isinstance(args, str) else shlex.join(args)
        with trace_action(logger, "Subprocess", message):
            return await run_command_timeout()


def init_max_subprocesses(max_subprocesses: int | None = None) -> None:
    max_subprocesses = (
        max_subprocesses if max_subprocesses else default_max_subprocesses()
    )
    max_subprocesses_context_var.set(max_subprocesses)


def default_max_subprocesses() -> int:
    # the processors this process may use rather than the machine's: under a
    # container CPU limit `os.cpu_count()` reports the host's, and sizing the
    # subprocess limiter off that oversubscribes the eval's own quota
    return effective_cpu_count()


# Upper bound on `await process.wait()` after we have already SIGKILLed the
# process. After SIGKILL the OS process is gone; we are only waiting for
# asyncio's child-watcher callback to set `transport._returncode`. If that
# callback was lost to a child-watcher race it will never fire, so any finite
# bound is correct. 60s is far above plausible event-loop scheduling latency
# under heavy load while still bounding teardown.
LOST_SUBPROCESS_WAIT_TIMEOUT = 60

# Grace period after SIGTERM before escalating to SIGKILL for a timed-out
# process. Named (rather than inline) so tests exercising the timeout/kill
# path can shrink it without waiting the full production grace.
SUBPROCESS_SIGTERM_GRACE_SECONDS = 2


def _warn_lost_subprocess(process: Process, where: str) -> None:
    logger.warning(
        "subprocess wait() did not return within %ds after SIGKILL (pid=%s, %s); "
        "asyncio child watcher likely missed this process's exit. "
        "Leaking transport to avoid deadlock.",
        LOST_SUBPROCESS_WAIT_TIMEOUT,
        process.pid,
        where,
    )


async def gracefully_terminate_cancelled_subprocess(process: Process) -> None:
    with anyio.CancelScope(shield=True):
        try:
            # Terminate timed out process -- try for graceful termination then kill if
            # required.
            process.terminate()
            await anyio.sleep(SUBPROCESS_SIGTERM_GRACE_SECONDS)
            if process.returncode is None:
                process.kill()
            # With anyio's asyncio backend, process.aclose() calls process.wait() which
            # can deadlock if the process generates so much output that it blocks
            # waiting for the OS pipe buffer to accept more data. See
            # https://docs.python.org/3/library/asyncio-subprocess.html#asyncio.subprocess.Process.wait
            # Therefore, we need to ensure that the process's stdout and stderr streams
            # are drained before we call process.wait() in aclose().
            async with create_task_group() as tg:
                tg.start_soon(drain_stream, process.stdout)
                tg.start_soon(drain_stream, process.stderr)
            # Bounded: see LOST_SUBPROCESS_WAIT_TIMEOUT.
            with anyio.move_on_after(LOST_SUBPROCESS_WAIT_TIMEOUT) as scope:
                await process.wait()
            if scope.cancelled_caught:
                _warn_lost_subprocess(process, "gracefully_terminate")
        # The process may have already exited, in which case we can ignore the error.
        except ProcessLookupError:
            pass


async def _write_stdin(stream: ByteSendStream | None, input: bytes | None) -> bool:
    """Write `input` to the child's stdin and close it.

    A child that exits or closes its stdin before consuming the input makes the
    write fail (EPIPE/ECONNRESET, surfaced by anyio as `BrokenResourceError`).
    That is the child's business, not a launch failure: its exit status and
    stderr describe what happened, so the caller should still get an
    `ExecResult` rather than an exception. Whether the write or the exit wins
    is timing-dependent, so tolerating it here is what makes such commands
    behave deterministically.

    Returns whether the input was fully written (`True` when there was none).
    """
    if stream is not None and input:
        try:
            await stream.send(input)
            await stream.aclose()
        except (BrokenResourceError, ClosedResourceError):
            return False
    return True


async def drain_stream(stream: ByteReceiveStream | None) -> None:
    if stream is None:
        return
    try:
        async for _ in stream:
            pass
    except ClosedResourceError:
        pass


async def _read_stream(
    stream: ByteReceiveStream | None, *, output_limit: int | None = None
) -> bytes:
    if stream is None:
        return bytes()
    if output_limit is None:
        bytesio = io.BytesIO()
        async for chunk in stream:
            bytesio.write(chunk)
        return bytesio.getvalue()
    else:
        circular = CircularByteBuffer(output_limit)
        async for chunk in stream:
            circular.write(chunk)
        return circular.getvalue()


async def _log_stream(stream: ByteReceiveStream | None) -> bytes:
    if stream is None:
        return bytes()
    buffer = bytes()
    async for chunk in stream:
        parts = (buffer + chunk).split(b"\n")
        buffer = parts[-1]
        for line in parts[:-1]:
            logger.info(line.decode(errors="replace").rstrip())
    if buffer:
        logger.info(buffer.decode(errors="replace").rstrip())
    return bytes()


max_subprocesses_context_var = ContextVar[int](
    "max_subprocesses", default=default_max_subprocesses()
)


class CircularByteBuffer:
    """Memory-efficient circular buffer that keeps only the most recent bytes."""

    def __init__(self, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = max_bytes
        self._chunks: deque[bytes] = deque()
        self._total_bytes = 0

    def write(self, data: bytes) -> None:
        if not data:
            return
        self._chunks.append(data)
        self._total_bytes += len(data)

        # Discard oldest chunks until under limit
        while self._total_bytes > self._max_bytes and len(self._chunks) > 1:
            removed = self._chunks.popleft()
            self._total_bytes -= len(removed)

        # If single chunk still over limit, truncate from front
        if self._total_bytes > self._max_bytes and self._chunks:
            excess = self._total_bytes - self._max_bytes
            self._chunks[0] = self._chunks[0][excess:]
            self._total_bytes = self._max_bytes

    def getvalue(self) -> bytes:
        return b"".join(self._chunks)
