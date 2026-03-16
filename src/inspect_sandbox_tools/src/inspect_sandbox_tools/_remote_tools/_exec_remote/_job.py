import asyncio
import os
import signal
from asyncio.subprocess import Process as AsyncIOProcess
from typing import Literal

from inspect_sandbox_tools._util.common_types import ToolException

from .tool_types import PollResult


class Job:
    """Manages an async subprocess with separate stdout/stderr streams.

    The Job wraps asyncio.create_subprocess_shell with PIPE for stdout/stderr.
    Background read tasks accumulate output into buffers. poll() returns and
    clears incremental output. kill() terminates the subprocess gracefully
    then forcefully.
    """

    @classmethod
    async def create(
        cls,
        command: str,
        input: str | None = None,
        stdin_open: bool = False,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> "Job":
        """Create and start a new Job for the given command.

        Uses start_new_session=True so the subprocess becomes its own process
        group leader. This allows kill() to terminate the entire process tree
        (including any child processes spawned by the command).

        Args:
            command: The shell command to execute.
            input: Optional standard input to send to the command.
            stdin_open: If True, keep stdin open after writing initial input
                for later write_stdin()/close_stdin() calls.
            env: Additional environment variables (merged with current env).
            cwd: Working directory for command execution.
        """
        # Use stdin=PIPE if we have input to send or if stdin should stay open
        stdin = asyncio.subprocess.PIPE if (input is not None or stdin_open) else None

        # Merge additional env vars with current environment if provided
        subprocess_env = {**os.environ, **env} if env else None

        process = await asyncio.create_subprocess_shell(
            command,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=subprocess_env,
            cwd=cwd,
        )

        job = cls(process)

        # Write initial input if provided
        if input is not None and process.stdin is not None:
            process.stdin.write(input.encode("utf-8"))
            await process.stdin.drain()

        # Close stdin unless caller wants it kept open
        if not stdin_open and process.stdin is not None:
            process.stdin.close()
            await process.stdin.wait_closed()

        return job

    def __init__(self, process: AsyncIOProcess) -> None:
        self._process = process
        self._stdout_buffer: list[str] = []
        self._stderr_buffer: list[str] = []
        self._state: Literal["running", "completed", "killed"] = "running"
        self._exit_code: int | None = None

        # Start background read tasks
        self._stdout_task = asyncio.create_task(
            self._read_stream(process.stdout, self._stdout_buffer)
        )
        self._stderr_task = asyncio.create_task(
            self._read_stream(process.stderr, self._stderr_buffer)
        )

    @property
    def pid(self) -> int:
        """Return the process ID."""
        assert self._process.pid is not None
        return self._process.pid

    async def poll(self) -> PollResult:
        """Return current state and incremental output, clearing buffers."""
        # Check if process has finished
        if self._state == "running" and self._process.returncode is not None:
            self._state = "completed"
            self._exit_code = self._process.returncode
            # Wait for read tasks to finish draining
            await self._wait_for_readers()

        stdout, stderr = self._drain_buffers()

        return PollResult(
            state=self._state,
            exit_code=self._exit_code,
            stdout=stdout,
            stderr=stderr,
        )

    async def kill(self, timeout: int = 5) -> tuple[str, str]:
        """Terminate the process and return any remaining buffered output.

        Since the subprocess was started with start_new_session=True, it is the
        leader of its own process group. We use os.killpg() to send signals to
        the entire group, ensuring child processes are also terminated.

        Returns:
            A tuple of (stdout, stderr) containing any output buffered since
            the last poll.
        """
        if self._state != "running":
            return ("", "")

        self._state = "killed"
        pgid = self._process.pid
        assert pgid is not None, "Process was created without a pid"

        # Try graceful termination first (SIGTERM to process group)
        try:
            os.killpg(pgid, signal.SIGTERM)
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Force kill if graceful termination times out (SIGKILL to process group)
            os.killpg(pgid, signal.SIGKILL)
            await self._process.wait()
        except ProcessLookupError:
            # Process already exited
            pass

        await self._wait_for_readers()

        return self._drain_buffers()

    def _drain_buffers(self) -> tuple[str, str]:
        """Collect and clear the stdout/stderr buffers.

        Returns:
            A tuple of (stdout, stderr) strings accumulated since the last drain.
        """
        stdout = "".join(self._stdout_buffer)
        stderr = "".join(self._stderr_buffer)
        self._stdout_buffer.clear()
        self._stderr_buffer.clear()
        return (stdout, stderr)

    async def write_stdin(self, data: str) -> tuple[str, str]:
        """Write data to the process's stdin and return buffered output.

        Returns:
            A tuple of (stdout, stderr) accumulated since the last read.

        Raises:
            ToolException: If stdin is not available or already closed.
        """
        if self._process.stdin is None:
            raise ToolException(
                "stdin is not available (process started without stdin_open=True)"
            )
        if self._process.stdin.is_closing():
            raise ToolException("stdin is already closed")
        if self._state != "running":
            raise ToolException(f"Cannot write to stdin: process is {self._state}")

        self._process.stdin.write(data.encode("utf-8"))
        await self._process.stdin.drain()
        return self._drain_buffers()

    async def close_stdin(self) -> tuple[str, str]:
        """Close the process's stdin pipe to signal EOF and return buffered output.

        This is idempotent — calling it when stdin is already closed is a no-op.

        Returns:
            A tuple of (stdout, stderr) accumulated since the last read.

        Raises:
            ToolException: If stdin is not available.
        """
        if self._process.stdin is None:
            raise ToolException(
                "stdin is not available (process started without stdin_open=True)"
            )
        if self._process.stdin.is_closing():
            return self._drain_buffers()

        self._process.stdin.close()
        await self._process.stdin.wait_closed()
        return self._drain_buffers()

    async def cleanup(self) -> None:
        """Clean up resources. Called after job is removed from controller."""
        await self._wait_for_readers()

    async def _wait_for_readers(self) -> None:
        """Wait for background read tasks to complete."""
        for task in [self._stdout_task, self._stderr_task]:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _read_stream(
        self, stream: asyncio.StreamReader | None, buffer: list[str]
    ) -> None:
        """Read from a stream and append to buffer."""
        if stream is None:
            return

        try:
            while True:
                data = await stream.read(4096)
                if not data:
                    break
                buffer.append(data.decode("utf-8", errors="replace"))
        except asyncio.CancelledError:
            pass
