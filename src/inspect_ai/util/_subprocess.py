import contextlib
import functools
import io
import os
import shlex
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from subprocess import DEVNULL, PIPE
from typing import Generic, Literal, TypeVar, Union, overload

import anyio
from anyio import ClosedResourceError, create_task_group, open_process
from anyio.abc import ByteReceiveStream, Process

from inspect_ai._util._async import tg_collect
from inspect_ai._util.trace import trace_action

from ._concurrency import concurrency as concurrency_manager

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
    subprocesses (defaulting to os.cpu_count() but controllable
    via the `max_subprocesses` eval config option).

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
    # resolve input
    input = (
        input.encode()
        if isinstance(input, str)
        else bytes(input)
        if input is not None
        else None
    )

    async def run_command() -> Union[ExecResult[str], ExecResult[bytes]]:
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
            # write to stdin (convert input to bytes)
            if process.stdin and input:
                await process.stdin.send(input)
                await process.stdin.aclose()

            if redirect_output_to_logger:
                consume = _log_stream
            else:
                consume = functools.partial(_read_stream, output_limit=output_limit)

            stdout, stderr = await tg_collect(
                [
                    functools.partial(consume, process.stdout),
                    functools.partial(consume, process.stderr),
                ]
            )

            returncode = await process.wait()
            success = returncode == 0
            if text:
                return ExecResult[str](
                    success=success,
                    returncode=returncode,
                    stdout=stdout.decode(errors="replace") if capture_output else "",
                    stderr=stderr.decode(errors="replace") if capture_output else "",
                )
            else:
                return ExecResult[bytes](
                    success=success,
                    returncode=returncode,
                    stdout=stdout if capture_output else bytes(),
                    stderr=stderr if capture_output else bytes(),
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
    async def run_command_timeout() -> Union[ExecResult[str], ExecResult[bytes]]:
        # wrap in timeout handler if requested
        if timeout is not None:
            with anyio.fail_after(timeout):
                # run_command() handles terminating the process if it is cancelled.
                return await run_command()
        else:
            return await run_command()

    # run command
    concurrency_ctx = (
        concurrency_manager("subprocesses", max_subprocesses_context_var.get())
        if concurrency
        else contextlib.nullcontext()
    )
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
    cpus = os.cpu_count()
    return cpus if cpus else 1


# Upper bound on `await process.wait()` after we have already SIGKILLed the
# process. After SIGKILL the OS process is gone; we are only waiting for
# asyncio's child-watcher callback to set `transport._returncode`. If that
# callback was lost to a child-watcher race it will never fire, so any finite
# bound is correct. 60s is far above plausible event-loop scheduling latency
# under heavy load while still bounding teardown.
LOST_SUBPROCESS_WAIT_TIMEOUT = 60


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
            await anyio.sleep(2)
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
