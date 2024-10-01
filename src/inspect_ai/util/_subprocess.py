import asyncio
import os
import sys
from asyncio.subprocess import Process
from contextvars import ContextVar
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import AsyncGenerator, Generic, Literal, TypeVar, Union, cast, overload

from ._concurrency import concurrency

logger = getLogger(__name__)

T = TypeVar("T", str, bytes)


@dataclass
class ExecResult(Generic[T]):
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
    timeout: int | None = None,
) -> ExecResult[bytes]: ...


async def subprocess(
    args: str | list[str],
    text: bool = True,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] = {},
    capture_output: bool = True,
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
       timeout (int | None): Timeout. If the timeout expires then
         a `TimeoutError` will be raised.

    Returns:
       Subprocess result (text or binary depending on `text` param)

    Raises:
       TimeoutError: If the specified `timeout` expires.
    """
    # resolve input
    input = input.encode() if isinstance(input, str) else input

    # function to run command (we may or may not run it w/ concurrency)
    async def run_command() -> (
        AsyncGenerator[Union[Process, ExecResult[str], ExecResult[bytes]], None]
    ):
        if isinstance(args, str):
            proc = await asyncio.create_subprocess_shell(
                args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE if capture_output else None,
                stderr=asyncio.subprocess.PIPE if capture_output else None,
                cwd=cwd,
                env={**os.environ, **env},
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                args[0],
                *args[1:],
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE if capture_output else None,
                stderr=asyncio.subprocess.PIPE if capture_output else None,
                cwd=cwd,
                env={**os.environ, **env},
            )

        # yield the proc
        yield proc

        # wait for it to execute and yield result
        stdout, stderr = await proc.communicate(input=input)
        success = proc.returncode == 0
        returncode = proc.returncode if proc.returncode is not None else 1
        if text:
            yield ExecResult[str](
                success=success,
                returncode=returncode,
                stdout=stdout.decode() if capture_output else "",
                stderr=stderr.decode() if capture_output else "",
            )
        else:
            yield ExecResult[bytes](
                success=success,
                returncode=returncode,
                stdout=stdout if capture_output else bytes(),
                stderr=stderr if capture_output else bytes(),
            )

    # wrapper for run command that implements timeout
    async def run_command_timeout() -> Union[ExecResult[str], ExecResult[bytes]]:
        # run the command and capture the process handle
        rc = run_command()
        proc = cast(Process, await anext(rc))

        # await result wrapped in timeout handler if requested
        if timeout:
            try:
                if sys.version_info >= (3, 11):
                    async with asyncio.timeout(timeout):
                        result = await anext(rc)
                        return cast(Union[ExecResult[str], ExecResult[bytes]], result)
                else:
                    result = await asyncio.wait_for(anext(rc), timeout=timeout)
                    return cast(Union[ExecResult[str], ExecResult[bytes]], result)
            except asyncio.exceptions.TimeoutError:
                # terminate timed out process -- try for graceful termination
                # then be more forceful if requied
                try:
                    proc.terminate()
                    await asyncio.sleep(2)
                    if proc.returncode is None:
                        proc.kill()
                except Exception as ex:
                    logger.warning(
                        f"Unexpected error terminating timed out process '{args}': {ex}"
                    )

                # raise standard Python TimeoutError
                raise TimeoutError

        # await result without timeout
        else:
            result = await anext(rc)
            return cast(Union[ExecResult[str], ExecResult[bytes]], result)

    # run command
    async with concurrency("subprocesses", max_subprocesses_context_var.get()):
        return await run_command_timeout()


def init_max_subprocesses(max_subprocesses: int | None = None) -> None:
    max_subprocesses = (
        max_subprocesses if max_subprocesses else default_max_subprocesses()
    )
    max_subprocesses_context_var.set(max_subprocesses)


def default_max_subprocesses() -> int:
    cpus = os.cpu_count()
    return cpus if cpus else 1


max_subprocesses_context_var = ContextVar[int](
    "max_subprocesses", default=default_max_subprocesses()
)
