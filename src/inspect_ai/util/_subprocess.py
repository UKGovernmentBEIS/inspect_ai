import functools
import io
import os
import shlex
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

from ._concurrency import concurrency

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
    env: dict[str, str] = {},
    capture_output: bool = True,
    output_limit: int | None = None,
    timeout: int | None = None,
) -> ExecResult[str]: ...


@overload
async def subprocess(
    args: str | list[str],
    text: Literal[False] = False,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] = {},
    capture_output: bool = True,
    output_limit: int | None = None,
    timeout: int | None = None,
) -> ExecResult[bytes]: ...


async def subprocess(
    args: str | list[str],
    text: bool = True,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] = {},
    capture_output: bool = True,
    output_limit: int | None = None,
    timeout: int | None = None,
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
          (if False, then output is redirected to parent stderr/stdout)
       output_limit (int | None): Stop reading output if it exceeds
          the specified limit (in bytes).
       timeout (int | None): Timeout. If the timeout expires then
          a `TimeoutError` will be raised.

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
        process = await open_process(
            args,
            stdin=PIPE if input else DEVNULL,
            stdout=PIPE if capture_output else None,
            stderr=PIPE if capture_output else None,
            cwd=cwd,
            env={**os.environ, **env},
        )
        try:
            # write to stdin (convert input to bytes)
            if process.stdin and input:
                await process.stdin.send(input)
                await process.stdin.aclose()

            # read streams incrementally so we can check output limits
            async def read_stream(stream: ByteReceiveStream | None) -> bytes:
                # return early for no stream
                if stream is None:
                    return bytes()

                written = 0
                buffer = io.BytesIO()
                async for chunk in stream:
                    buffer.write(chunk)
                    written += len(chunk)
                    if output_limit is not None and written > output_limit:
                        process.kill()
                        break

                return buffer.getvalue()

            stdout, stderr = await tg_collect(
                [
                    functools.partial(read_stream, process.stdout),
                    functools.partial(read_stream, process.stderr),
                ]
            )

            returncode = await process.wait()
            success = returncode == 0
            if text:
                return ExecResult[str](
                    success=success,
                    returncode=returncode,
                    stdout=stdout.decode() if capture_output else "",
                    stderr=stderr.decode() if capture_output else "",
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
            try:
                await process.aclose()
            except ProcessLookupError:
                # the anyio ansycio backend calls process.kill() from within
                # its aclose() method without an enclosing exception handler
                # (which in turn can throw ProcessLookupError if the process
                # is already gone)
                pass

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
    async with concurrency("subprocesses", max_subprocesses_context_var.get()):
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
            # Wait for the process to exit. Will be called again by aclose().
            await process.wait()
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


max_subprocesses_context_var = ContextVar[int](
    "max_subprocesses", default=default_max_subprocesses()
)
