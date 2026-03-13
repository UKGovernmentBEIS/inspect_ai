from __future__ import annotations

from inspect_sandbox_tools._util.common_types import ToolException

from ._job import Job
from .tool_types import CloseStdinResult, KillResult, PollResult, WriteStdinResult

_CachedResponse = PollResult | KillResult | WriteStdinResult | CloseStdinResult


class Controller:
    """Simple job registry keyed by PID.

    Unlike bash_session's SessionController, exec_remote uses PIDs as natural
    unique identifiers - no session naming or multiplexing needed.
    """

    def __init__(self) -> None:
        self._jobs: dict[int, Job] = {}
        # Start dedup: request_id -> pid (prevents duplicate process spawning)
        self._start_request_ids: dict[str, int] = {}
        self._pid_to_start_request_id: dict[int, str] = {}
        # Response cache: pid -> (request_id, response)
        # Only the last response per job is cached. This is safe because the
        # host sends RPCs sequentially per process (never concurrent).
        self._last_response: dict[int, tuple[str, _CachedResponse]] = {}

    async def submit(
        self,
        command: str,
        input: str | None = None,
        stdin_open: bool = False,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        request_id: str | None = None,
    ) -> int:
        """Create a new job and return its PID.

        Args:
            command: The shell command to execute.
            input: Optional standard input to send to the command.
            stdin_open: If True, keep stdin open for later writes.
            env: Additional environment variables (merged with current env).
            cwd: Working directory for command execution.
            request_id: If provided and matches a previous submit, returns
                the existing PID without creating a new process.
        """
        if request_id and request_id in self._start_request_ids:
            return self._start_request_ids[request_id]

        job = await Job.create(
            command, input=input, stdin_open=stdin_open, env=env, cwd=cwd
        )
        self._jobs[job.pid] = job
        if request_id:
            self._start_request_ids[request_id] = job.pid
            self._pid_to_start_request_id[job.pid] = request_id
        return job.pid

    async def poll(self, pid: int, request_id: str | None = None) -> PollResult:
        """Get job state and incremental output. Auto-cleanup on terminal state."""
        cached = self._check_cache(pid, request_id)
        if cached is not None:
            return cached  # type: ignore[return-value]

        job = self._get_job(pid)
        result = await job.poll()
        self._store_cache(pid, request_id, result)

        if result.state in ("completed", "killed"):
            await self._cleanup_job(pid)

        return result

    async def kill(self, pid: int, request_id: str | None = None) -> KillResult:
        """Terminate a running job and return any remaining buffered output."""
        cached = self._check_cache(pid, request_id)
        if cached is not None:
            return cached  # type: ignore[return-value]

        job = self._get_job(pid)
        stdout, stderr = await job.kill()
        result = KillResult(stdout=stdout, stderr=stderr)
        self._store_cache(pid, request_id, result)

        await self._cleanup_job(pid)
        return result

    async def write_stdin(
        self, pid: int, data: str, request_id: str | None = None
    ) -> WriteStdinResult:
        """Write data to stdin of a running job and return buffered output."""
        cached = self._check_cache(pid, request_id)
        if cached is not None:
            return cached  # type: ignore[return-value]

        job = self._get_job(pid)
        stdout, stderr = await job.write_stdin(data)
        result = WriteStdinResult(stdout=stdout, stderr=stderr)
        self._store_cache(pid, request_id, result)
        return result

    async def close_stdin(
        self, pid: int, request_id: str | None = None
    ) -> CloseStdinResult:
        """Close stdin of a running job and return buffered output."""
        cached = self._check_cache(pid, request_id)
        if cached is not None:
            return cached  # type: ignore[return-value]

        job = self._get_job(pid)
        stdout, stderr = await job.close_stdin()
        result = CloseStdinResult(stdout=stdout, stderr=stderr)
        self._store_cache(pid, request_id, result)
        return result

    def _get_job(self, pid: int) -> Job:
        """Get job by PID or raise error."""
        job = self._jobs.get(pid)
        if job is None:
            raise ToolException(f"No job found with pid {pid}")
        return job

    def _check_cache(self, pid: int, request_id: str | None) -> _CachedResponse | None:
        """Return cached response if request_id matches, else None."""
        if request_id and pid in self._last_response:
            cached_rid, cached_response = self._last_response[pid]
            if cached_rid == request_id:
                return cached_response
        return None

    def _store_cache(
        self, pid: int, request_id: str | None, response: _CachedResponse
    ) -> None:
        """Cache response for idempotent retry."""
        if request_id:
            self._last_response[pid] = (request_id, response)

    async def _cleanup_job(self, pid: int) -> None:
        """Remove job from registry and clean up start dedup map.

        Uses pop() to avoid KeyError if a concurrent poll()/kill() already
        removed the job. _last_response[pid] is intentionally kept so retries
        of the terminal poll/kill can still get the cached response.
        """
        job = self._jobs.pop(pid, None)
        if job is not None:
            await job.cleanup()
        rid = self._pid_to_start_request_id.pop(pid, None)
        if rid:
            self._start_request_ids.pop(rid, None)
