"""Unit tests for the exec_remote Controller.

These test the Controller in isolation by injecting mock Jobs, without
spawning real subprocesses.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from inspect_sandbox_tools._remote_tools._exec_remote._controller import Controller
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
