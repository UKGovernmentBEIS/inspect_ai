"""Unit tests for the exec_remote Controller.

These test the Controller in isolation by injecting mock Jobs, without
spawning real subprocesses.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from inspect_sandbox_tools._remote_tools._exec_remote import _job as job_module
from inspect_sandbox_tools._remote_tools._exec_remote._controller import Controller
from inspect_sandbox_tools._remote_tools._exec_remote._job import Job
from inspect_sandbox_tools._remote_tools._exec_remote.tool_types import PollResult


class TestControllerConcurrentPollAndKill:
    """Verify that concurrent poll() and kill() on the same PID don't raise."""

    @pytest.mark.asyncio
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
            state="completed", exit_code=0, seq=1, stdout="", stderr=""
        )

        # Create a mock job whose poll() and kill() yield control via
        # asyncio.sleep(0). This ensures both coroutines get past _get_job()
        # before either attempts deletion.
        job = MagicMock()
        job.pid = pid
        job.cleanup = AsyncMock()

        async def mock_poll(ack_seq: int) -> PollResult:
            await asyncio.sleep(0)
            return completed_result

        async def mock_kill(ack_seq: int) -> tuple[int, str, str]:
            await asyncio.sleep(0)
            return (1, "", "")

        job.poll = mock_poll
        job.kill = mock_kill

        # Inject the mock job directly into the controller's registry.
        controller._jobs[pid] = job

        # Both poll and kill will try to del self._jobs[pid].
        # Run them concurrently — only one should do the deletion.
        poll_result, kill_result = await asyncio.gather(
            controller.poll(pid, ack_seq=0),
            controller.kill(pid, ack_seq=0),
        )

        # Both should complete without error.
        assert poll_result.state == "completed"
        assert kill_result.stdout == ""

        # The job should have been removed from the registry.
        assert pid not in controller._jobs

        # cleanup should have been called exactly once, not twice.
        assert job.cleanup.call_count == 1


@pytest.mark.asyncio
async def test_shutdown_terminates_and_removes_all_jobs() -> None:
    controller = Controller()
    jobs = []
    for pid in (41, 42):
        job = MagicMock()
        job.shutdown = AsyncMock()
        job.cleanup = AsyncMock()
        controller._jobs[pid] = job
        jobs.append(job)

    await controller.shutdown()

    assert controller._jobs == {}
    for job in jobs:
        job.shutdown.assert_awaited_once_with()
        job.cleanup.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_shutdown_reports_failures_from_every_job() -> None:
    controller = Controller()
    for pid, message in ((41, "first shutdown failed"), (42, "second shutdown failed")):
        job = MagicMock()
        job.shutdown = AsyncMock(side_effect=RuntimeError(message))
        job.cleanup = AsyncMock()
        controller._jobs[pid] = job

    with pytest.raises(RuntimeError) as error:
        await controller.shutdown()

    assert "first shutdown failed" in str(error.value)
    assert "second shutdown failed" in str(error.value)


@pytest.mark.asyncio
async def test_retired_job_shutdown_uses_only_its_captured_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = await asyncio.create_subprocess_exec("true")
    await process.wait()
    job = Job(process)
    captured_child = MagicMock(pid=99)
    capture_group = MagicMock(return_value=[captured_child])
    terminate = AsyncMock()
    monkeypatch.setattr(job_module, "process_group_members", capture_group)
    monkeypatch.setattr(job_module, "terminate_process_tree", terminate)

    job.retire()
    await job.shutdown()

    assert process.pid is not None
    capture_group.assert_called_once_with(process.pid, exclude_pid=process.pid)
    terminate.assert_awaited_once_with(
        process,
        timeout=30,
        process_group=False,
        known_descendants=[captured_child],
    )
