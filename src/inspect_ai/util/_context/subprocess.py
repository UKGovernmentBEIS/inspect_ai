import asyncio
import os
import shlex
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Literal, TypeVar, Union, overload

from .concurrency import concurrency, using_concurrency

T = TypeVar("T", str, bytes)


@dataclass
class ProcessResult(Generic[T]):
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
    timeout: int | None = None,
) -> ProcessResult[str]:
    ...


@overload
async def subprocess(
    args: str | list[str],
    text: Literal[False] = False,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] = {},
    timeout: int | None = None,
) -> ProcessResult[bytes]:
    ...


async def subprocess(
    args: str | list[str],
    text: bool = True,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] = {},
    timeout: int | None = None,
) -> Union[ProcessResult[str], ProcessResult[bytes]]:
    """Execute and wait for a subprocess.

    Convenience method for solvers, scorers, and tools to launch
    subprocesses. Automatically enforces a limit on concurrent
    subprocesses (defaulting to os.cpu_count() but controllable
    via the `max_subproccesses` eval config option).

    Args:
       args (str | list[str]): Command and arguments to execute.
       text (bool): Return stdout and stderr as text (defaults to True)
       input (str | bytes | memoryview | None): Optional stdin
          for subprocess.
       cwd (str | Path | None): Switch to directory for execution.
       env (dict[str, str]): Additional environment variables.
       timeout (int | None): Timeout

    Returns:
       Subprocess result (text or binary depending on `text` param)
    """
    # resolve input
    input = input.encode() if isinstance(input, str) else input

    # build command
    args = args if isinstance(args, list) else [args]
    command = " ".join([shlex.quote(arg) for arg in args])

    # function to run command (we may or may not run it w/ concurrency)
    async def run_command() -> Union[ProcessResult[str], ProcessResult[bytes]]:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env={**os.environ, **env},
        )

        # wait for it to execute and return result
        stdout, stderr = await proc.communicate(input=input)
        success = proc.returncode == 0
        returncode = proc.returncode if proc.returncode is not None else 1
        if text:
            return ProcessResult[str](
                success=success,
                returncode=returncode,
                stdout=stdout.decode(),
                stderr=stderr.decode(),
            )
        else:
            return ProcessResult[bytes](
                success=success,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
            )

    # wrapper for run command that implements timeout
    async def run_command_timeout() -> Union[ProcessResult[str], ProcessResult[bytes]]:
        if timeout:
            try:
                if sys.version_info >= (3, 11):
                    async with asyncio.timeout(timeout):
                        return await run_command()
                else:
                    return await asyncio.wait_for(run_command(), timeout=timeout)
            except asyncio.exceptions.TimeoutError:
                return ProcessResult(
                    False, 1, "", "Command timed out before completing"
                )
        else:
            return await run_command()

    # run command
    if using_concurrency():
        async with concurrency("subprocesses", max_subprocesses_context_var.get()):
            return await run_command_timeout()
    else:
        return await run_command_timeout()


def init_subprocess(max_subprocesses: int | None = None) -> None:
    # initialize dedicated subprocesses semaphore
    cpus = os.cpu_count()
    max_subprocesses = max_subprocesses if max_subprocesses else cpus if cpus else 1
    max_subprocesses_context_var.set(max_subprocesses)


max_subprocesses_context_var = ContextVar[int]("max_subprocesses")
