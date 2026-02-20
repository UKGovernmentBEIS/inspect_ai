from inspect_sandbox_tools._util.common_types import ToolException

from ._job import Job
from .tool_types import CloseStdinResult, KillResult, PollResult, WriteStdinResult


class Controller:
    """Simple job registry keyed by PID.

    Unlike bash_session's SessionController, exec_remote uses PIDs as natural
    unique identifiers - no session naming or multiplexing needed.
    """

    def __init__(self) -> None:
        self._jobs: dict[int, Job] = {}

    async def submit(
        self,
        command: str,
        input: str | None = None,
        stdin_open: bool = False,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> int:
        """Create a new job and return its PID.

        Args:
            command: The shell command to execute.
            input: Optional standard input to send to the command.
            stdin_open: If True, keep stdin open for later writes.
            env: Additional environment variables (merged with current env).
            cwd: Working directory for command execution.
        """
        job = await Job.create(
            command, input=input, stdin_open=stdin_open, env=env, cwd=cwd
        )
        self._jobs[job.pid] = job
        return job.pid

    async def poll(self, pid: int) -> PollResult:
        """Get job state and incremental output. Auto-cleanup on terminal state."""
        job = self._get_job(pid)
        result = await job.poll()

        # Auto-cleanup after terminal state. Use pop to avoid KeyError if a
        # concurrent kill() already removed the job between our await and here.
        if result.state in ("completed", "killed"):
            if self._jobs.pop(pid, None) is not None:
                await job.cleanup()

        return result

    async def kill(self, pid: int) -> KillResult:
        """Terminate a running job and return any remaining buffered output."""
        job = self._get_job(pid)
        stdout, stderr = await job.kill()
        # Use pop to avoid KeyError if a concurrent poll() already removed the
        # job between our await and here.
        if self._jobs.pop(pid, None) is not None:
            await job.cleanup()
        return KillResult(stdout=stdout, stderr=stderr)

    async def write_stdin(self, pid: int, data: str) -> WriteStdinResult:
        """Write data to stdin of a running job and return buffered output."""
        job = self._get_job(pid)
        stdout, stderr = await job.write_stdin(data)
        return WriteStdinResult(stdout=stdout, stderr=stderr)

    async def close_stdin(self, pid: int) -> CloseStdinResult:
        """Close stdin of a running job and return buffered output."""
        job = self._get_job(pid)
        stdout, stderr = await job.close_stdin()
        return CloseStdinResult(stdout=stdout, stderr=stderr)

    def _get_job(self, pid: int) -> Job:
        """Get job by PID or raise error."""
        job = self._jobs.get(pid)
        if job is None:
            raise ToolException(f"No job found with pid {pid}")
        return job
