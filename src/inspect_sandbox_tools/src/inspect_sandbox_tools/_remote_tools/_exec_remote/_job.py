import asyncio
import os
import signal
import time
from asyncio.subprocess import Process as AsyncIOProcess
from typing import Literal, NamedTuple

import psutil

from inspect_sandbox_tools._util.common_types import ToolException
from inspect_sandbox_tools._util.process_tree import (
    process_group_members,
    terminate_process_tree,
)
from inspect_sandbox_tools._util.user_switch import (
    RunAs,
    get_home_dir,
    make_preexec,
    switch_target,
)

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
_WAIT_CHECK_INTERVAL_SECONDS = 0.05
_OUTPUT_EXIT_WAIT_SECONDS = 0.1


def _leader_handle(process: AsyncIOProcess) -> psutil.Process | None:
    """Identity-checked handle for the job's group leader, taken at spawn.

    psutil records the creation time on construction, so the handle later
    distinguishes the process we started from another that reused its PID.
    None if the process was reaped before the handle could be taken.
    """
    if process.pid is None:
        return None
    try:
        return psutil.Process(process.pid)
    except psutil.NoSuchProcess:
        return None


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
        user: str | RunAs | None = None,
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
        job = await cls.spawn(
            command,
            stdin=input is not None or stdin_open,
            env=env,
            cwd=cwd,
            user=user,
            can_switch_user=can_switch_user,
        )
        await job.initialize_stdin(input, stdin_open)
        return job

    @classmethod
    async def spawn(
        cls,
        command: str,
        stdin: bool = False,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        user: str | RunAs | None = None,
        can_switch_user: bool = False,
    ) -> "Job":
        """Start the process for a new Job, without writing to its stdin.

        Args:
            command: The shell command to execute.
            stdin: If True, connect stdin to a pipe for `initialize_stdin`.
            env: Additional environment variables (merged with current env).
            cwd: Working directory for command execution.
            user: User to run the command as (requires can_switch_user=True).
            can_switch_user: Whether the server can switch users (running as root).
        """
        user = switch_target(user, can_switch_user)

        # Merge additional env vars with current environment if provided. When
        # switching user, HOME follows the user unless the caller set it explicitly.
        subprocess_env: dict[str, str] | None = {**os.environ, **env} if env else None
        if user is not None:
            subprocess_env = {**os.environ, "HOME": get_home_dir(user), **(env or {})}

        process = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE if stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=subprocess_env,
            cwd=cwd,
            preexec_fn=make_preexec(user),
        )

        return cls(process)

    async def initialize_stdin(self, input: str | None, stdin_open: bool) -> None:
        """Write the initial input, then close stdin unless it is kept open.

        This can wait as long as the command does not read its input, and it
        raises ConnectionResetError("Connection lost") if the command closes
        stdin first. asyncio raises BrokenPipeError or ConnectionResetError
        depending on timing, so both map to the one error.

        Args:
            input: Standard input to send to the command, if any.
            stdin_open: If True, keep stdin open for later writes.
        """
        stdin = self._process.stdin
        if stdin is None:
            return
        try:
            if input is not None:
                stdin.write(input.encode("utf-8"))
                await stdin.drain()
            if not stdin_open:
                stdin.close()
                await stdin.wait_closed()
        except (BrokenPipeError, ConnectionResetError) as ex:
            raise ConnectionResetError("Connection lost") from ex

    def __init__(self, process: AsyncIOProcess) -> None:
        self._process = process
        self._leader = _leader_handle(process)
        self._stdout_buffer = BoundedByteBuffer(_BACKPRESSURE_BUFFER_SIZE)
        self._stderr_buffer = BoundedByteBuffer(_BACKPRESSURE_BUFFER_SIZE)
        self._stdout_output = DecodingBuffer(self._stdout_buffer)
        self._stderr_output = DecodingBuffer(self._stderr_buffer)
        self._killed = False
        self._acked_buffer: AckedChunkBuffer[tuple[str, str]] = AckedChunkBuffer()
        self._known_descendants: list[psutil.Process] = []
        self._retired = False
        # Termination started by the first kill(); later kills wait for it.
        self._termination: asyncio.Task[None] | None = None

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

    @property
    def killed(self) -> bool:
        """Whether kill() or shutdown() signalled the leader while it ran."""
        return self._killed

    @property
    def _state(self) -> Literal["running", "completed", "killed"]:
        """Read from the process, so an exit no caller has seen yet still counts.

        A job is killed only if kill() or shutdown() signalled its leader while
        it ran; a leader that exited on its own keeps its exit code.
        """
        if self._killed:
            return "killed"
        if self._process.returncode is not None:
            return "completed"
        return "running"

    @property
    def _exit_code(self) -> int | None:
        return self._process.returncode if self._state == "completed" else None

    @property
    def _has_output(self) -> bool:
        return len(self._stdout_buffer) > 0 or len(self._stderr_buffer) > 0

    async def poll(self, ack_seq: int, wait: float = 0) -> PollResult:
        """Return current state and incremental output, clearing buffers.

        Args:
            ack_seq: Sequence number of the last output the client received.
            wait: Seconds to wait for the job to exit or buffer output before
                replying (see `_wait_while_idle`).
        """
        await self._wait_while_idle(wait)

        # Drain the readers whenever the job is no longer running. A poll
        # cancelled here leaves the state terminal with the readers unfinished;
        # a later poll finishes the drain so its output is not lost. Once the
        # readers are done this does nothing.
        if self._state != "running":
            await self._wait_for_readers()

        # Always limit per-poll output to keep JSON-RPC responses small. While
        # output remains past the limit, report running so the client polls
        # again; once the buffers are empty, flush the decoder and report the
        # terminal state with this output.
        stdout, stderr = self._drain_buffers(
            final=False, max_bytes=_MAX_POLL_OUTPUT_BYTES
        )
        reported_state = self._state
        if reported_state != "running" and self._has_output:
            reported_state = "running"
        elif reported_state != "running":
            tail_stdout, tail_stderr = self._drain_buffers(final=True)
            stdout += tail_stdout
            stderr += tail_stderr
        reported_exit_code = None if reported_state == "running" else self._exit_code

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

    async def _wait_while_idle(self, wait: float) -> None:
        """Wait up to `wait` seconds while the job runs and has no output.

        Returns at the first of: the job exits or is killed, output is buffered,
        or `wait` expires. After output is buffered, it waits up to 0.1 s more
        (still within `wait`) for the exit, so a short command's output and exit
        status share one reply. The state is checked every 0.05 s instead of
        awaiting `Process.wait()`, which on Python 3.11+ blocks while a
        descendant holds the pipes. With `wait=0` it returns at once.
        """
        deadline = time.monotonic() + wait
        while self._state == "running" and (now := time.monotonic()) < deadline:
            if self._has_output:
                deadline = min(deadline, now + _OUTPUT_EXIT_WAIT_SECONDS)
            await asyncio.sleep(min(_WAIT_CHECK_INTERVAL_SECONDS, deadline - now))

    async def kill(self, ack_seq: int, timeout: int = 5) -> OutputChunk:
        """Terminate the process and return any remaining buffered output.

        Since the subprocess was started with start_new_session=True, it is the
        leader of its own process group. We use os.killpg() to send signals to
        the entire group, ensuring child processes are also terminated.

        The group is signalled only after checking that the leader is still the
        process we started. Once it has exited and been reaped, its PID, and so
        the group id, may belong to an unrelated process, which a server running
        as root would then signal. A job whose leader exited on its own is
        treated as finished: it keeps its exit code, its buffered output is
        returned and any children that outlived it may be left running.

        Termination runs once, shielded from cancellation of the caller: a kill
        that arrives while another is terminating the job waits for it, so no
        caller returns before the group has been terminated.
        """
        if self._killed and self._termination is None:
            # shutdown() already terminated it
            self._acked_buffer.push(("", ""))
            seq, chunks = self._acked_buffer.collect(ack_seq)
            return OutputChunk(seq, *self._combine_chunks(chunks))

        if self._termination is None:
            self._termination = asyncio.create_task(self._terminate_group(timeout))
        await asyncio.shield(self._termination)
        await self._wait_for_readers()

        stdout, stderr = self._drain_buffers(final=True)
        self._acked_buffer.push((stdout, stderr))
        seq, chunks = self._acked_buffer.collect(ack_seq)
        return OutputChunk(seq, *self._combine_chunks(chunks))

    async def await_termination(self) -> None:
        """Wait for an in-progress kill to finish, if one exists."""
        if self._termination is not None:
            await asyncio.shield(self._termination)

    async def _terminate_group(self, timeout: int) -> None:
        # The leader is checked here, with no await before the signal, so an exit
        # after kill() was called keeps its exit code. Check and signal are still
        # not atomic. Likelihood that leader could exit, be reaped and have its PID
        # reused between is unlikely, as the PID space must wrap inside that gap.
        if not self._leader_running():
            return
        self._killed = True
        pgid = self.pid
        try:
            os.killpg(pgid, signal.SIGTERM)
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            await self._force_kill_group(pgid, timeout)
        except ProcessLookupError:
            pass

    async def shutdown(self, timeout: int = 30) -> None:
        """Forcefully terminate this server-owned job during server shutdown."""
        if self._leader_running():
            self._killed = True
        known_descendants = [*self._known_descendants]
        try:
            await terminate_process_tree(
                self._process,
                timeout=timeout,
                process_group=not self._retired,
                known_descendants=known_descendants,
            )
        finally:
            self._known_descendants.clear()
            await self._wait_for_readers()

    async def _force_kill_group(self, pgid: int, timeout: int) -> None:
        """SIGKILL the group once SIGTERM's grace period has passed.

        On Python 3.11+ ``Process.wait()`` returns only after every pipe has
        closed, so the grace period can expire with the leader already dead
        and its group gone while a descendant still holds stdout or stderr.
        The leader is therefore rechecked before signalling by id, and the
        wait after SIGKILL is bounded because it may never return while such
        a descendant lives.
        """
        if not self._leader_running():
            return
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    def _leader_running(self) -> bool:
        """Whether the group leader is still the process this job started.

        ``returncode`` alone is not enough: asyncio's child watcher reaps the
        child before the event loop records the exit, and the PID is reusable
        from the reap onward. The handle taken at spawn compares creation time,
        so a reused PID reads as not running.
        """
        return (
            self._process.returncode is None
            and self._leader is not None
            and self._leader.is_running()
        )

    def retire(self) -> None:
        """Snapshot remaining group members before retaining a completed job."""
        if self._retired:
            return
        self._retired = True
        self._remember_descendants()

    def _remember_descendants(self) -> None:
        pid = self._process.pid
        if pid is not None:
            self._known_descendants.extend(process_group_members(pid, exclude_pid=pid))

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
        """Wait up to 1 s for the read tasks to reach EOF, then cancel any left.

        Only the tasks still running when called are awaited, so a repeated
        call does not re-raise an error an earlier call already handled. The
        buffers stay open while the tasks run, so output read after the leader
        exits is kept, and cancelling a task frees a put() that waits on a full
        buffer. A reader error is raised to the caller.
        """
        readers = [t for t in (self._stdout_task, self._stderr_task) if not t.done()]
        if not readers:
            return
        _, pending = await asyncio.wait(readers, timeout=1.0)
        for task in pending:
            task.cancel()
        await asyncio.gather(*readers)

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
