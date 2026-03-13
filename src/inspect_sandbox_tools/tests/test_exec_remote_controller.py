"""Unit tests for the exec_remote Controller.

These test the Controller in isolation by injecting mock Jobs, without
spawning real subprocesses.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from inspect_sandbox_tools._remote_tools._exec_remote._controller import Controller
from inspect_sandbox_tools._remote_tools._exec_remote._job import Job
from inspect_sandbox_tools._remote_tools._exec_remote.tool_types import (
    PollResult,
)
from inspect_sandbox_tools._util.common_types import ToolException


class TestControllerConcurrentPollAndKill:
    """Verify that concurrent poll() and kill() on the same PID don't raise."""

    async def test_concurrent_poll_and_kill_does_not_raise(self) -> None:
        """
        Concurrent poll (returning completed) and kill for the same PID should both succeed without raising KeyError.

        The race: both coroutines call _get_job(pid) successfully, then both
        await their respective job methods (yielding control), then both try
        to delete the job from _jobs. With bare `del`, the second one raises
        KeyError.
        """
        controller = Controller()
        pid = 42

        completed_result = PollResult(
            state="completed", exit_code=0, stdout="", stderr=""
        )

        # Create a mock job whose poll() and kill() yield control via
        # asyncio.sleep(0). This ensures both coroutines get past _get_job()
        # before either attempts deletion.
        job = MagicMock()
        job.pid = pid
        job.cleanup = AsyncMock()

        async def mock_poll() -> PollResult:
            await asyncio.sleep(0)
            return completed_result

        async def mock_kill() -> tuple[str, str]:
            await asyncio.sleep(0)
            return ("", "")

        job.poll = mock_poll
        job.kill = mock_kill

        # Inject the mock job directly into the controller's registry.
        controller._jobs[pid] = job

        # Both poll and kill will try to del self._jobs[pid].
        # Run them concurrently — only one should do the deletion.
        poll_result, kill_result = await asyncio.gather(
            controller.poll(pid),
            controller.kill(pid),
        )

        # Both should complete without error.
        assert poll_result.state == "completed"
        assert kill_result.stdout == ""

        # The job should have been removed from the registry.
        assert pid not in controller._jobs

        # cleanup should have been called exactly once, not twice.
        assert job.cleanup.call_count == 1


def _make_mock_job(pid: int = 42) -> MagicMock:
    """Build a mock Job with sensible async defaults."""
    job = MagicMock(spec=Job)
    job.pid = pid
    job.cleanup = AsyncMock()
    job.poll = AsyncMock(
        return_value=PollResult(state="running", exit_code=None, stdout="", stderr="")
    )
    job.kill = AsyncMock(return_value=("", ""))
    job.write_stdin = AsyncMock(return_value=("", ""))
    job.close_stdin = AsyncMock(return_value=("", ""))
    return job


class TestControllerStartDedup:
    """Verify that submit() deduplicates on request_id."""

    async def test_duplicate_start_returns_same_pid(self) -> None:
        """Submit twice with same request_id; Job.create called once, same pid returned."""
        controller = Controller()
        job = _make_mock_job(pid=42)
        mock_create = AsyncMock(return_value=job)

        with patch.object(Job, "create", mock_create):
            pid1 = await controller.submit("echo hi", request_id="req-abc")
            pid2 = await controller.submit("echo hi", request_id="req-abc")

        assert pid1 == pid2 == 42
        mock_create.assert_awaited_once()

    async def test_different_request_ids_create_different_jobs(self) -> None:
        """Different request_ids each create their own job."""
        controller = Controller()
        job1 = _make_mock_job(pid=42)
        job2 = _make_mock_job(pid=43)
        mock_create = AsyncMock(side_effect=[job1, job2])

        with patch.object(Job, "create", mock_create):
            pid1 = await controller.submit("echo a", request_id="req-1")
            pid2 = await controller.submit("echo b", request_id="req-2")

        assert pid1 == 42
        assert pid2 == 43
        assert mock_create.await_count == 2

    async def test_no_request_id_skips_dedup(self) -> None:
        """Without request_id, every submit creates a new job."""
        controller = Controller()
        job1 = _make_mock_job(pid=42)
        job2 = _make_mock_job(pid=43)
        mock_create = AsyncMock(side_effect=[job1, job2])

        with patch.object(Job, "create", mock_create):
            pid1 = await controller.submit("echo a")
            pid2 = await controller.submit("echo b")

        assert pid1 == 42
        assert pid2 == 43
        assert mock_create.await_count == 2


class TestControllerResponseCache:
    """Verify that request_id caches the last response per PID."""

    async def test_poll_cache_returns_same_response(self) -> None:
        """Same request_id on poll: job.poll called once, same result returned."""
        controller = Controller()
        job = _make_mock_job(pid=42)
        controller._jobs[42] = job

        result1 = await controller.poll(42, request_id="req-x")
        result2 = await controller.poll(42, request_id="req-x")

        assert result1 == result2
        job.poll.assert_awaited_once()

    async def test_poll_cache_miss_on_different_request_id(self) -> None:
        """Different request_ids each call job.poll."""
        controller = Controller()
        job = _make_mock_job(pid=42)
        controller._jobs[42] = job

        await controller.poll(42, request_id="req-1")
        await controller.poll(42, request_id="req-2")

        assert job.poll.await_count == 2

    async def test_terminal_poll_cached_after_cleanup(self) -> None:
        """After terminal poll + cleanup, retry with same request_id returns cached response."""
        controller = Controller()
        job = _make_mock_job(pid=42)
        completed = PollResult(state="completed", exit_code=0, stdout="done", stderr="")
        job.poll = AsyncMock(return_value=completed)
        controller._jobs[42] = job

        result1 = await controller.poll(42, request_id="req-final")
        # Job is now cleaned up (not in _jobs)
        assert 42 not in controller._jobs

        # Retry with same request_id — should hit cache even though job is gone
        result2 = await controller.poll(42, request_id="req-final")

        assert result1 == result2 == completed
        job.poll.assert_awaited_once()

    async def test_poll_after_cleanup_with_different_request_id_raises(self) -> None:
        """After terminal poll + cleanup, poll with a different request_id raises ToolException."""
        controller = Controller()
        job = _make_mock_job(pid=42)
        completed = PollResult(state="completed", exit_code=0, stdout="done", stderr="")
        job.poll = AsyncMock(return_value=completed)
        controller._jobs[42] = job

        await controller.poll(42, request_id="req-final")
        assert 42 not in controller._jobs

        with pytest.raises(ToolException, match="No job found with pid 42"):
            await controller.poll(42, request_id="req-different")

    async def test_no_request_id_skips_cache(self) -> None:
        """Without request_id, every call hits job.poll."""
        controller = Controller()
        job = _make_mock_job(pid=42)
        controller._jobs[42] = job

        await controller.poll(42)
        await controller.poll(42)

        assert job.poll.await_count == 2

    @pytest.mark.parametrize(
        "method_name, call_args, mock_attr",
        [
            ("kill", (42,), "kill"),
            ("write_stdin", (42, "hello"), "write_stdin"),
            ("close_stdin", (42,), "close_stdin"),
        ],
        ids=["kill", "write_stdin", "close_stdin"],
    )
    async def test_cache_returns_same_response(
        self, method_name: str, call_args: tuple[Any, ...], mock_attr: str
    ) -> None:
        """Same request_id on kill/write_stdin/close_stdin: underlying method called once."""
        controller = Controller()
        job = _make_mock_job(pid=42)
        controller._jobs[42] = job

        method = getattr(controller, method_name)
        result1 = await method(*call_args, request_id="req-x")
        result2 = await method(*call_args, request_id="req-x")

        assert result1 == result2
        getattr(job, mock_attr).assert_awaited_once()

    async def test_pid_reuse_overwrites_stale_cache(self) -> None:
        """After job1 completes on pid=42, job2 reuses pid=42; fresh request_id gets fresh result."""
        controller = Controller()

        job1 = _make_mock_job(pid=42)
        job1.poll = AsyncMock(
            return_value=PollResult(
                state="completed", exit_code=0, stdout="job1", stderr=""
            )
        )
        controller._jobs[42] = job1

        # Complete job1
        result1 = await controller.poll(42, request_id="req-job1-final")
        assert result1.stdout == "job1"
        assert 42 not in controller._jobs  # cleaned up

        # New job2 reuses pid=42
        job2 = _make_mock_job(pid=42)
        job2.poll = AsyncMock(
            return_value=PollResult(
                state="running", exit_code=None, stdout="job2", stderr=""
            )
        )
        controller._jobs[42] = job2

        # Different request_id -> cache miss -> job2.poll called
        result2 = await controller.poll(42, request_id="req-job2-first")
        assert result2.stdout == "job2"
        job2.poll.assert_awaited_once()
