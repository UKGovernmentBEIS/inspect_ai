import asyncio
import os
import pwd
import signal
from asyncio.subprocess import Process as AsyncIOProcess
from collections.abc import Callable
from typing import Literal, NamedTuple

from inspect_sandbox_tools._util.common_types import ToolException

from ._acked_chunk_buffer import AckedChunkBuffer
from ._output_buffer import BoundedByteBuffer, DecodingBuffer
from .tool_types import PollResult


class OutputChunk(NamedTuple):
    """Sequence number and incremental stdout/stderr from a job operation."""

    seq: int
    stdout: str
    stderr: str


_BACKPRESSURE_BUFFER_SIZE = 100 * 1024 * 1024  # 100 MiB
_MAX_POLL_OUTPUT_BYTES = 1 * 1024 * 1024  # 1 MiB per poll response


def _set_oom_score_adj() -> None:
    """Set oom_score_adj in the child process before exec.

    Called via preexec_fn so it runs after fork() but before exec(),
    ensuring the shell and all its descendants inherit the adjusted score.
    This makes child processes the preferred OOM-kill target, protecting the
    sandbox tools server from the OOM killer.
    """
    try:
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write("1000")
    except OSError:
        pass


def _is_current_user(username: str) -> bool:
    """Check if the given username matches the current process user."""
    try:
        return pwd.getpwnam(username).pw_uid == os.getuid()
    except KeyError:
        return False


def _make_preexec(username: str | None) -> Callable[[], None]:
    """Build a preexec_fn that sets OOM score and optionally switches user.

    Args:
        username: If provided, switch to this user via setuid/setgid/initgroups.
            Requires the current process to be running as root.
            If the user matches the current process user, setuid is skipped.
    """

    def _preexec() -> None:
        _set_oom_score_adj()
        if username is not None:
            try:
                pw = pwd.getpwnam(username)
            except KeyError:
                os.write(
                    2,
                    f"exec_remote: user {username!r} not found in /etc/passwd\n".encode(),
                )
                os._exit(1)
            try:
                os.initgroups(username, pw.pw_gid)
                os.setgid(pw.pw_gid)
                os.setuid(pw.pw_uid)
            except PermissionError:
                os.write(
                    2,
                    f"exec_remote: permission denied switching to user {username!r} (server may lack CAP_SETUID/CAP_SETGID)\n".encode(),
                )
                os._exit(1)

    return _preexec


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
        user: str | None = None,
        can_switch_user: bool = False,
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
            user: User to run the command as (requires can_switch_user=True).
            can_switch_user: Whether the server can switch users (running as root).
        """
        # If the requested user matches the current process user, no setuid needed
        if user is not None and _is_current_user(user):
            user = None
        if user is not None and not can_switch_user:
            raise ToolException(
                f"Cannot switch to user {user!r}: server is not running as root"
            )

        # Use stdin=PIPE if we have input to send or if stdin should stay open
        stdin = asyncio.subprocess.PIPE if (input is not None or stdin_open) else None

        # Merge additional env vars with current environment if provided.
        # When switching user, set HOME from /etc/passwd to match docker exec --user.
        subprocess_env: dict[str, str] | None = {**os.environ, **env} if env else None
        if user is not None:
            if subprocess_env is None:
                subprocess_env = {**os.environ}
            try:
                subprocess_env["HOME"] = pwd.getpwnam(user).pw_dir
            except KeyError:
                subprocess_env["HOME"] = "/"

        process = await asyncio.create_subprocess_shell(
            command,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=subprocess_env,
            cwd=cwd,
            preexec_fn=_make_preexec(user),
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
        self._stdout_buffer = BoundedByteBuffer(_BACKPRESSURE_BUFFER_SIZE)
        self._stderr_buffer = BoundedByteBuffer(_BACKPRESSURE_BUFFER_SIZE)
        self._stdout_output = DecodingBuffer(self._stdout_buffer)
        self._stderr_output = DecodingBuffer(self._stderr_buffer)
        self._state: Literal["running", "completed", "killed"] = "running"
        self._exit_code: int | None = None
        self._acked_buffer: AckedChunkBuffer[tuple[str, str]] = AckedChunkBuffer()

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

    async def poll(self, ack_seq: int) -> PollResult:
        """Return current state and incremental output, clearing buffers."""
        # Check if process has finished
        if self._state == "running" and self._process.returncode is not None:
            self._state = "completed"
            self._exit_code = self._process.returncode
            # Wait for read tasks to finish draining
            await self._wait_for_readers()

        # Always limit per-poll output to keep JSON-RPC responses small.
        # Defer reporting terminal state until buffers are fully drained
        # so the client keeps polling for remaining output.
        stdout, stderr = self._drain_buffers(
            final=False, max_bytes=_MAX_POLL_OUTPUT_BYTES
        )

        buffers_empty = not stdout and not stderr
        if self._state != "running" and not buffers_empty:
            # Report as running so client keeps polling
            reported_state: Literal["running", "completed", "killed"] = "running"
            reported_exit_code = None
        elif self._state != "running" and buffers_empty:
            # Buffers drained — flush decoder and report terminal state
            stdout, stderr = self._drain_buffers(final=True)
            reported_state = self._state
            reported_exit_code = self._exit_code
        else:
            reported_state = self._state
            reported_exit_code = self._exit_code

        self._acked_buffer.push((stdout, stderr))
        seq, chunks = self._acked_buffer.collect(ack_seq)
        combined_out, combined_err = self._combine_chunks(chunks)

        return PollResult(
            state=reported_state,
            exit_code=reported_exit_code,
            seq=seq,
            stdout=combined_out,
            stderr=combined_err,
        )

    async def kill(self, ack_seq: int, timeout: int = 5) -> OutputChunk:
        """Terminate the process and return any remaining buffered output.

        Since the subprocess was started with start_new_session=True, it is the
        leader of its own process group. We use os.killpg() to send signals to
        the entire group, ensuring child processes are also terminated.
        """
        if self._state != "running":
            self._acked_buffer.push(("", ""))
            seq, chunks = self._acked_buffer.collect(ack_seq)
            return OutputChunk(seq, *self._combine_chunks(chunks))

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

        stdout, stderr = self._drain_buffers(final=True)
        self._acked_buffer.push((stdout, stderr))
        seq, chunks = self._acked_buffer.collect(ack_seq)
        return OutputChunk(seq, *self._combine_chunks(chunks))

    def _drain_buffers(
        self, final: bool = False, max_bytes: int | None = None
    ) -> tuple[str, str]:
        """Collect and clear the stdout/stderr buffers.

        Args:
            final: If True, flush any trailing partial UTF-8 sequences
                as replacement characters.
            max_bytes: Maximum raw bytes to drain per stream. If None,
                drains everything.

        Returns:
            A tuple of (stdout, stderr) strings accumulated since the last drain.
        """
        return (
            self._stdout_output.drain(final, max_bytes),
            self._stderr_output.drain(final, max_bytes),
        )

    async def write_stdin(self, data: str, ack_seq: int) -> OutputChunk:
        """Write data to the process's stdin and return buffered output.

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
        stdout, stderr = self._drain_buffers()
        self._acked_buffer.push((stdout, stderr))
        seq, chunks = self._acked_buffer.collect(ack_seq)
        return OutputChunk(seq, *self._combine_chunks(chunks))

    async def close_stdin(self, ack_seq: int) -> OutputChunk:
        """Close the process's stdin pipe to signal EOF and return buffered output.

        This is idempotent — calling it when stdin is already closed is a no-op.

        Raises:
            ToolException: If stdin is not available.
        """
        if self._process.stdin is None:
            raise ToolException(
                "stdin is not available (process started without stdin_open=True)"
            )
        if self._process.stdin.is_closing():
            stdout, stderr = self._drain_buffers()
        else:
            self._process.stdin.close()
            await self._process.stdin.wait_closed()
            stdout, stderr = self._drain_buffers()

        self._acked_buffer.push((stdout, stderr))
        seq, chunks = self._acked_buffer.collect(ack_seq)
        return OutputChunk(seq, *self._combine_chunks(chunks))

    @staticmethod
    def _combine_chunks(chunks: list[tuple[str, str]]) -> tuple[str, str]:
        """Concatenate a list of (stdout, stderr) chunks."""
        return (
            "".join(c[0] for c in chunks),
            "".join(c[1] for c in chunks),
        )

    async def cleanup(self) -> None:
        """Clean up resources. Called after job is removed from controller."""
        await self._wait_for_readers()

    async def _wait_for_readers(self) -> None:
        """Wait for background read tasks to complete."""
        self._stdout_buffer.close()
        self._stderr_buffer.close()
        for task in [self._stdout_task, self._stderr_task]:
            if not task.done():
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

    async def _read_stream(
        self, stream: asyncio.StreamReader | None, buffer: BoundedByteBuffer
    ) -> None:
        """Read from a stream and append to buffer with backpressure."""
        if stream is None:
            return

        try:
            while True:
                data = await stream.read(4096)
                if not data:
                    break
                await buffer.put(data)
        except asyncio.CancelledError:
            pass
