import asyncio

from inspect_sandbox_tools._util.common_types import ToolException
from inspect_sandbox_tools._util.user_switch import RunAs

from ._job import Job
from .tool_types import (
    CloseStdinResult,
    KillKeyResult,
    KillResult,
    PollResult,
    WriteStdinResult,
)


class Controller:
    """Simple job registry keyed by PID.

    Unlike bash_session's SessionController, exec_remote uses PIDs as natural
    unique identifiers - no session naming or multiplexing needed.

    A job may also carry a host-chosen key, so the host can kill it when the
    reply carrying its PID never arrives (see `kill_key`).
    """

    def __init__(self) -> None:
        self._jobs: dict[int, Job] = {}
        self._retired_jobs: list[Job] = []
        # Jobs started with a key, None while the start is in progress. Entries
        # outlive the job (as _retired_jobs does) so that a repeated start with
        # the same key never starts a second job.
        self._keyed_jobs: dict[str, Job | None] = {}
        # Keys killed before their job started; a start with one is refused.
        self._refused_keys: set[str] = set()

    async def submit(
        self,
        command: str,
        input: str | None = None,
        stdin_open: bool = False,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        user: str | RunAs | None = None,
        can_switch_user: bool = False,
        job_key: str | None = None,
    ) -> int:
        """Create a new job and return its PID.

        A start whose key was killed first is refused. A repeated start with
        the key of a running job (a retried request) returns that job's PID;
        one whose job is still starting or has ended is refused.

        Args:
            command: The shell command to execute.
            input: Optional standard input to send to the command.
            stdin_open: If True, keep stdin open for later writes.
            env: Additional environment variables (merged with current env).
            cwd: Working directory for command execution.
            user: User to run the command as (requires can_switch_user=True).
            can_switch_user: Whether the server can switch users (running as root).
            job_key: Host-chosen key that `kill_key` accepts.

        Raises:
            ToolException: If the job key was killed or has already been used.
        """
        if job_key is not None:
            if job_key in self._refused_keys:
                raise ToolException(
                    f"exec_remote job {job_key} was killed before it started"
                )
            if job_key in self._keyed_jobs:
                return self._repeated_start(job_key)
            self._keyed_jobs[job_key] = None
        try:
            job = await Job.create(
                command,
                input=input,
                stdin_open=stdin_open,
                env=env,
                cwd=cwd,
                user=user,
                can_switch_user=can_switch_user,
            )
        except BaseException:
            if job_key is not None:
                del self._keyed_jobs[job_key]
            raise
        self._jobs[job.pid] = job
        if job_key is not None:
            self._keyed_jobs[job_key] = job
            if job_key in self._refused_keys:
                await self.kill(job.pid, ack_seq=0)
                raise ToolException(
                    f"exec_remote job {job_key} was killed while it started"
                )
        return job.pid

    def _repeated_start(self, job_key: str) -> int:
        job = self._keyed_jobs[job_key]
        if job is None:
            raise ToolException(f"exec_remote job {job_key} is already starting")
        if self._jobs.get(job.pid) is not job:
            raise ToolException(f"exec_remote job {job_key} has already ended")
        return job.pid

    async def kill_key(self, job_key: str) -> KillKeyResult:
        """Kill the job started with `job_key`, or refuse its start if none has.

        The host calls this when it submitted a start but never received the
        PID, so the job may be running, starting, or not yet arrived. A job
        still starting is killed as soon as it starts.
        """
        job = self._keyed_jobs.get(job_key)
        if job is None:
            self._refused_keys.add(job_key)
            return KillKeyResult(killed=False)
        if self._jobs.get(job.pid) is not job:
            return KillKeyResult(killed=False)
        await self.kill(job.pid, ack_seq=0)
        return KillKeyResult(killed=True)

    async def poll(self, pid: int, ack_seq: int) -> PollResult:
        """Get job state and incremental output. Auto-cleanup on terminal state."""
        job = self._get_job(pid)
        result = await job.poll(ack_seq)

        # Auto-cleanup after terminal state. Use pop to avoid KeyError if a
        # concurrent kill() already removed the job between our await and here.
        if result.state in ("completed", "killed"):
            if self._jobs.pop(pid, None) is not None:
                job.retire()
                self._retired_jobs.append(job)
                await job.cleanup()

        return result

    async def kill(self, pid: int, ack_seq: int) -> KillResult:
        """Terminate a running job and return any remaining buffered output."""
        job = self._get_job(pid)
        seq, stdout, stderr = await job.kill(ack_seq)
        # Use pop to avoid KeyError if a concurrent poll() already removed the
        # job between our await and here.
        if self._jobs.pop(pid, None) is not None:
            job.retire()
            self._retired_jobs.append(job)
            await job.cleanup()
        return KillResult(seq=seq, stdout=stdout, stderr=stderr)

    async def write_stdin(self, pid: int, data: str, ack_seq: int) -> WriteStdinResult:
        """Write data to stdin of a running job and return buffered output."""
        job = self._get_job(pid)
        seq, stdout, stderr = await job.write_stdin(data, ack_seq)
        return WriteStdinResult(seq=seq, stdout=stdout, stderr=stderr)

    async def close_stdin(self, pid: int, ack_seq: int) -> CloseStdinResult:
        """Close stdin of a running job and return buffered output."""
        job = self._get_job(pid)
        seq, stdout, stderr = await job.close_stdin(ack_seq)
        return CloseStdinResult(seq=seq, stdout=stdout, stderr=stderr)

    async def shutdown(self) -> None:
        """Terminate every job owned by this server."""
        jobs = [*self._jobs.values(), *self._retired_jobs]
        self._jobs.clear()
        self._retired_jobs.clear()

        async def shutdown_job(job: Job) -> None:
            errors: list[Exception] = []
            try:
                await job.shutdown()
            except Exception as ex:
                errors.append(ex)
            try:
                await job.cleanup()
            except Exception as ex:
                errors.append(ex)
            if errors:
                raise RuntimeError("; ".join(str(error) for error in errors))

        results = await asyncio.gather(
            *(shutdown_job(job) for job in jobs), return_exceptions=True
        )
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise RuntimeError("; ".join(str(error) for error in errors))

    def _get_job(self, pid: int) -> Job:
        """Get job by PID or raise error."""
        job = self._jobs.get(pid)
        if job is None:
            raise ToolException(f"No job found with pid {pid}")
        return job
