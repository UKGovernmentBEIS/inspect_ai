"""Unit tests for the exec_remote Controller and Job.

Controller tests inject mock Jobs. Job tests spawn short-lived real
subprocesses to exercise kill and shutdown behaviour.
"""

import asyncio
import os
import shlex
import signal
import sys
import time
from asyncio import base_subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest
from inspect_sandbox_tools._remote_tools._exec_remote import _job as job_module
from inspect_sandbox_tools._remote_tools._exec_remote._controller import Controller
from inspect_sandbox_tools._remote_tools._exec_remote._job import Job
from inspect_sandbox_tools._remote_tools._exec_remote.tool_types import PollResult
from inspect_sandbox_tools._util.common_types import ToolException


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

        async def mock_poll(ack_seq: int, wait: float) -> PollResult:
            await asyncio.sleep(0)
            return completed_result

        async def mock_kill(ack_seq: int) -> tuple[int, str, str]:
            await asyncio.sleep(0)
            return (1, "", "")

        job.poll = mock_poll
        job.kill = mock_kill
        job.await_termination = AsyncMock()

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
async def test_poll_of_unknown_pid_names_the_missing_job() -> None:
    """The host's exec_remote client matches this message after a timed-out poll."""
    controller = Controller()

    with pytest.raises(ToolException, match=r"^No job found with pid 42"):
        await controller.poll(42, ack_seq=0)


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


async def _stop_job(job: Job) -> None:
    if job._process.returncode is None:
        job._process.kill()
        await job._process.wait()
    await job.cleanup()


@pytest.mark.parametrize(
    "error",
    [BrokenPipeError(32, "Broken pipe"), ConnectionResetError("Connection lost")],
)
async def test_initialize_stdin_reports_a_closed_stdin_as_connection_lost(
    monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    """Both low-level stdin errors report Connection lost and keep their cause."""
    job = await Job.spawn("exec sleep 30", stdin=True)
    try:
        assert job._process.stdin is not None
        monkeypatch.setattr(job._process.stdin, "drain", AsyncMock(side_effect=error))

        with pytest.raises(ConnectionResetError, match="Connection lost") as raised:
            await job.initialize_stdin("input", stdin_open=False)

        assert raised.value.__cause__ is error
    finally:
        await _stop_job(job)


@pytest.mark.asyncio
async def test_kill_signals_group_while_leader_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = await Job.create("sleep 30")
    signalled: list[tuple[int, int]] = []
    real_killpg = os.killpg

    def record_killpg(pgid: int, sig: int) -> None:
        signalled.append((pgid, sig))
        real_killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", record_killpg)
    try:
        await job.kill(ack_seq=0)
        assert job._process.returncode is not None
    finally:
        await _stop_job(job)

    assert signalled == [(job.pid, signal.SIGTERM)]


@pytest.mark.asyncio
async def test_kill_after_leader_exited_returns_output_without_signalling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = await Job.create("echo done")
    await job._process.wait()
    # Process exit does not guarantee the readers have buffered its output.
    await job._stdout_task
    await job._stderr_task
    killpg = MagicMock(side_effect=AssertionError("signalled a stale process group"))
    monkeypatch.setattr(os, "killpg", killpg)

    try:
        seq, stdout, stderr = await job.kill(ack_seq=0)
    finally:
        await _stop_job(job)

    killpg.assert_not_called()
    assert seq == 1
    assert stdout == "done\n"
    assert stderr == ""


@pytest.mark.asyncio
async def test_leader_exiting_before_the_kill_task_signals_keeps_its_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The leader runs when kill() is called but exits before the group is signalled."""
    real_terminate_group = Job._terminate_group

    async def terminate_after_exit(job: Job, *args: Any) -> None:
        await job._process.wait()
        await real_terminate_group(job, *args)

    monkeypatch.setattr(Job, "_terminate_group", terminate_after_exit)
    job = await Job.create("sleep 0.3; exit 3")
    killpg = MagicMock(side_effect=AssertionError("signalled an exited leader"))
    monkeypatch.setattr(os, "killpg", killpg)

    try:
        await job.kill(ack_seq=0)
        result = await job.poll(ack_seq=1)
    finally:
        await _stop_job(job)

    killpg.assert_not_called()
    assert result.state == "completed"
    assert result.exit_code == 3


async def _wait_for_exit(job: Job) -> None:
    """Wait for the leader's exit without waiting for its pipes to close."""
    with anyio.fail_after(5):
        while job._process.returncode is None:
            await anyio.sleep(0.01)


@pytest.mark.asyncio
async def test_poll_during_kill_of_exited_job_reports_its_exit_code() -> None:
    """A leader that exited on its own before kill() completed, whatever it is asked."""
    controller = Controller()
    # The background child holds the pipes open, so kill() and poll() both
    # wait for the readers and the poll reads the job's state during the kill.
    pid = await controller.submit("(sleep 30) & exit 3")
    job = controller._jobs[pid]
    await _wait_for_exit(job)

    try:
        _, result = await asyncio.gather(
            controller.kill(pid, ack_seq=0), controller.poll(pid, ack_seq=0)
        )
    finally:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await _stop_job(job)

    assert (result.state, result.exit_code) == ("completed", 3)


@pytest.mark.asyncio
async def test_shutdown_keeps_the_exit_code_of_an_exited_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(job_module, "terminate_process_tree", AsyncMock())
    job = await Job.create("exit 3")
    await _wait_for_exit(job)

    try:
        await job.shutdown()
        result = await job.poll(ack_seq=0)
    finally:
        await _stop_job(job)

    assert (result.state, result.exit_code) == ("completed", 3)


@pytest.mark.asyncio
async def test_kill_treats_reused_pid_as_exited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A leader handle whose identity no longer matches means the PID was reused."""
    job = await Job.create("sleep 30")
    job._leader = MagicMock(is_running=MagicMock(return_value=False))
    killpg = MagicMock()
    monkeypatch.setattr(os, "killpg", killpg)

    try:
        await job.kill(ack_seq=0)
    finally:
        await _stop_job(job)

    killpg.assert_not_called()


@pytest.mark.asyncio
async def test_kill_does_not_escalate_to_a_dead_leaders_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The leader dies on SIGTERM while a descendant in its own session holds the pipes.

    On Python 3.11+ ``Process.wait()`` then stays blocked past the grace period,
    and the SIGKILL escalation must not signal the dead leader's group id.
    """
    pidfile = tmp_path / "grandchild.pid"
    grandchild = (
        "import os,pathlib,time; os.setsid(); "
        f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(300)"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); time.sleep(300)"
    )
    job = await Job.create(f"{shlex.quote(sys.executable)} -c {shlex.quote(parent)}")
    for _ in range(200):
        if pidfile.exists():
            break
        await asyncio.sleep(0.05)
    assert pidfile.exists(), "grandchild did not start"

    signalled: list[int] = []
    real_killpg = os.killpg

    def record_killpg(pgid: int, sig: int) -> None:
        signalled.append(sig)
        real_killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", record_killpg)
    try:
        await asyncio.wait_for(job.kill(ack_seq=0, timeout=1), 10)
    finally:
        try:
            os.kill(int(pidfile.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass
        await _stop_job(job)

    assert signalled == [signal.SIGTERM]
    assert job._process.returncode is not None


class TestPollDeliversOutputAfterLeaderExits:
    """Output a child writes after the group leader exits must still reach poll."""

    @staticmethod
    async def _poll_to_completion(
        controller: Controller, pid: int, interval: float = 0.05
    ) -> tuple[PollResult, str, str]:
        """Poll a job every `interval` seconds until it reports a terminal state."""
        stdout, stderr = "", ""
        ack_seq = 0
        with anyio.fail_after(5):
            while True:
                result = await controller.poll(pid, ack_seq)
                ack_seq = result.seq
                stdout += result.stdout
                stderr += result.stderr
                if result.state != "running":
                    return result, stdout, stderr
                await anyio.sleep(interval)

    @pytest.mark.asyncio
    async def test_late_stdout_from_background_child_is_delivered(self) -> None:
        controller = Controller()
        pid = await controller.submit("(sleep 0.3; printf late) & printf early")
        result, stdout, stderr = await self._poll_to_completion(controller, pid)
        assert stdout == "earlylate"
        assert result.state == "completed"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_late_stderr_from_background_child_is_delivered(self) -> None:
        controller = Controller()
        pid = await controller.submit("(sleep 0.3; printf late 1>&2) & printf early")
        result, stdout, stderr = await self._poll_to_completion(controller, pid)
        assert stdout == "early"
        assert stderr == "late"
        assert result.state == "completed"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_first_poll_in_submit_turn_keeps_output(self) -> None:
        """The first poll can see the exit before the readers run; output survives.

        On main the buffers are closed before the readers drain the pipe, so this
        loses the output about half the time.
        """
        for _ in range(10):
            controller = Controller()
            pid = await controller.submit("printf hello")
            result, stdout, stderr = await self._poll_to_completion(controller, pid)
            assert stdout == "hello"
            assert result.state == "completed"
            assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_completes_within_one_second_when_a_child_writes_forever(
        self,
    ) -> None:
        """A single 1 s bound covers both streams, not 1 s per stream."""
        controller = Controller()
        pid = await controller.submit(
            "(while true; do printf x; sleep 0.01; done) & printf early"
        )
        try:
            start = time.monotonic()
            result, stdout, stderr = await self._poll_to_completion(controller, pid)
            elapsed = time.monotonic() - start
        finally:
            _kill_group(pid)
        assert result.state == "completed"
        assert "early" in stdout
        assert elapsed < 1.5

    @pytest.mark.asyncio
    async def test_cancelling_poll_waiting_for_readers_raises_in_caller(self) -> None:
        controller = Controller()
        pid = await controller.submit(
            "(while true; do printf x; sleep 0.01; done) & printf early"
        )
        try:
            job = controller._jobs[pid]
            with anyio.fail_after(5):
                while job._process.returncode is None:
                    await anyio.sleep(0.01)

            task = asyncio.create_task(controller.poll(pid, ack_seq=0))
            await anyio.sleep(0.1)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            _kill_group(pid)

    @pytest.mark.asyncio
    async def test_output_survives_a_poll_cancelled_while_waiting(
        self, tmp_path: Path
    ) -> None:
        """A poll cancelled while draining the readers must not lose output.

        The state is already terminal, so a later poll finishes the drain and
        still delivers the output the readers get afterwards.

        A gate file holds the child's late write until the test releases it, so
        the output cannot arrive before the poll is cancelled.
        """
        controller = Controller()
        gate = shlex.quote(str(tmp_path / "gate"))
        pid = await controller.submit(
            f"(while [ ! -e {gate} ]; do sleep 0.01; done; printf late) & printf early"
        )
        try:
            job = controller._jobs[pid]
            with anyio.fail_after(5):
                while job._process.returncode is None:
                    await anyio.sleep(0.01)

            task = asyncio.create_task(controller.poll(pid, ack_seq=0))
            await anyio.sleep(0.1)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            (tmp_path / "gate").touch()
            result, stdout, stderr = await self._poll_to_completion(controller, pid)
            assert stdout == "earlylate"
            assert result.state == "completed"
            assert result.exit_code == 0
        finally:
            _kill_group(pid)


def _kill_group(pid: int) -> None:
    """Kill a job's process group, including children that outlived the leader."""
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


_JOB_KEY = "0123456789abcdef0123456789abcdef"

_LARGE_INPUT = "x" * (512 * 1024)
"""More input than a pipe buffers, so writing it waits on the command."""


def _record_spawns(monkeypatch: pytest.MonkeyPatch) -> "asyncio.Queue[Job]":
    """Queue each Job as soon as its process is spawned."""
    spawned: asyncio.Queue[Job] = asyncio.Queue()
    real_spawn = Job.spawn

    async def recording_spawn(command: str, **kwargs: Any) -> Job:
        job = await real_spawn(command, **kwargs)
        spawned.put_nowait(job)
        return job

    monkeypatch.setattr(Job, "spawn", recording_spawn)
    return spawned


def _group_alive(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    return True


class TestKillByJobKey:
    """A host that never got a start's PID kills the job by its key."""

    @pytest.mark.asyncio
    async def test_kill_key_kills_a_started_job(self) -> None:
        controller = Controller()
        pid = await controller.submit("sleep 30", job_key=_JOB_KEY)
        try:
            result = await controller.kill_key(_JOB_KEY)

            assert result.killed is True
            assert not _group_alive(pid)
            with pytest.raises(ToolException, match="No job found"):
                await controller.poll(pid, ack_seq=0)
        finally:
            _kill_group(pid)

    @pytest.mark.asyncio
    async def test_kill_key_before_start_refuses_the_start(self) -> None:
        controller = Controller()

        result = await controller.kill_key(_JOB_KEY)
        with pytest.raises(ToolException, match="killed before it started"):
            await controller.submit("sleep 30", job_key=_JOB_KEY)

        assert result.killed is False
        assert controller._jobs == {}

    @pytest.mark.asyncio
    async def test_kill_key_during_spawn_waits_for_the_child_and_kills_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The child exists before Job.spawn() returns; kill_key must wait for it."""
        child_created = asyncio.Event()
        proceed = asyncio.Event()
        child_pids: list[int] = []
        real_connect_pipes = base_subprocess.BaseSubprocessTransport._connect_pipes

        async def paused_connect_pipes(
            transport: base_subprocess.BaseSubprocessTransport,
            waiter: "asyncio.Future[None]",
        ) -> None:
            pid = transport.get_pid()
            assert pid is not None
            child_pids.append(pid)
            child_created.set()
            await proceed.wait()
            await real_connect_pipes(transport, waiter)

        monkeypatch.setattr(
            base_subprocess.BaseSubprocessTransport,
            "_connect_pipes",
            paused_connect_pipes,
        )
        controller = Controller()
        submit = asyncio.create_task(
            controller.submit("exec sleep 30", input=_LARGE_INPUT, job_key=_JOB_KEY)
        )
        await child_created.wait()
        try:
            kill = asyncio.create_task(controller.kill_key(_JOB_KEY))
            for _ in range(10):
                await asyncio.sleep(0)
            assert not kill.done()
            assert _group_alive(child_pids[0])

            proceed.set()
            result = await asyncio.wait_for(kill, timeout=10)

            assert result.killed is True
            assert not _group_alive(child_pids[0])
            # killing the job ends the stdin write the start was waiting on
            with pytest.raises(ConnectionResetError, match="Connection lost"):
                await asyncio.wait_for(submit, timeout=10)
            assert controller._jobs == {}
        finally:
            proceed.set()
            submit.cancel()
            for pid in child_pids:
                _kill_group(pid)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("outcome", ["fails", "is cancelled"])
    async def test_start_retried_after_a_killed_spawn_ended_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, outcome: str
    ) -> None:
        """A retry of a start whose spawn ended while its kill waited must not run."""
        spawning = asyncio.Event()
        proceed = asyncio.Event()
        spawns = 0

        async def failing_spawn(command: str, **kwargs: Any) -> Job:
            nonlocal spawns
            spawns += 1
            if spawns == 1:
                spawning.set()
                await proceed.wait()
            raise OSError("spawn failed")

        monkeypatch.setattr(Job, "spawn", failing_spawn)
        controller = Controller()
        submit = asyncio.create_task(controller.submit("sleep 30", job_key=_JOB_KEY))
        await spawning.wait()
        kill = asyncio.create_task(controller.kill_key(_JOB_KEY))
        await asyncio.sleep(0)

        if outcome == "fails":
            proceed.set()
            with pytest.raises(OSError, match="spawn failed"):
                await submit
        else:
            submit.cancel()
            with pytest.raises(asyncio.CancelledError):
                await submit
        # the retry arrives before the kill has answered, and again after
        with pytest.raises(ToolException, match="killed before it started"):
            await controller.submit("sleep 30", job_key=_JOB_KEY)
        assert (await kill).killed is False
        with pytest.raises(ToolException, match="killed before it started"):
            await controller.submit("sleep 30", job_key=_JOB_KEY)

        assert spawns == 1
        assert controller._jobs == {}

    @pytest.mark.asyncio
    async def test_kill_key_while_input_is_backpressured_kills_the_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spawned = _record_spawns(monkeypatch)
        controller = Controller()
        submit = asyncio.create_task(
            controller.submit("exec sleep 60", input=_LARGE_INPUT, job_key=_JOB_KEY)
        )
        job = await spawned.get()
        try:
            await anyio.sleep(0.1)
            assert not submit.done()
            with pytest.raises(ToolException, match="is already starting"):
                await controller.submit("exec sleep 60", job_key=_JOB_KEY)

            result = await controller.kill_key(_JOB_KEY)

            assert result.killed is True
            assert not _group_alive(job.pid)
            with pytest.raises(ConnectionResetError, match="Connection lost"):
                await submit
            assert controller._jobs == {}
        finally:
            submit.cancel()
            _kill_group(job.pid)

    @pytest.mark.asyncio
    async def test_cancelled_start_kills_a_job_whose_input_is_backpressured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spawned = _record_spawns(monkeypatch)
        controller = Controller()
        submit = asyncio.create_task(
            controller.submit("exec sleep 60", input=_LARGE_INPUT, job_key=_JOB_KEY)
        )
        job = await spawned.get()
        try:
            await anyio.sleep(0.1)
            submit.cancel()
            with pytest.raises(asyncio.CancelledError):
                await submit

            assert not _group_alive(job.pid)
            assert controller._jobs == {}
        finally:
            _kill_group(job.pid)

    @pytest.mark.asyncio
    async def test_start_whose_command_closes_stdin_kills_the_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spawned = _record_spawns(monkeypatch)
        controller = Controller()
        try:
            with pytest.raises(ConnectionResetError, match="Connection lost"):
                await controller.submit(
                    "exec 0<&-; exec sleep 60", input=_LARGE_INPUT, job_key=_JOB_KEY
                )
            job = spawned.get_nowait()

            assert not _group_alive(job.pid)
            assert controller._jobs == {}
            assert (await controller.kill_key(_JOB_KEY)).killed is False
        finally:
            while not spawned.empty():
                _kill_group(spawned.get_nowait().pid)

    @pytest.mark.asyncio
    async def test_kill_key_during_a_failed_start_waits_for_the_job_to_die(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A kill by key joins the kill a failed start began, not return early."""
        spawned = _record_spawns(monkeypatch)
        terminating = asyncio.Event()
        real_killpg = os.killpg

        def killpg(pgid: int, sig: int) -> None:
            real_killpg(pgid, sig)
            if sig == signal.SIGTERM:
                terminating.set()

        monkeypatch.setattr(os, "killpg", killpg)
        controller = Controller()
        # ignores SIGTERM, so the start's kill waits to escalate to SIGKILL
        submit = asyncio.create_task(
            controller.submit(
                "trap '' TERM; exec 0<&-; exec sleep 60",
                input=_LARGE_INPUT,
                job_key=_JOB_KEY,
            )
        )
        job = await spawned.get()
        try:
            await terminating.wait()
            assert not submit.done()

            result = await controller.kill_key(_JOB_KEY)

            assert result.killed is True
            assert not _group_alive(job.pid)
            with pytest.raises(ConnectionResetError, match="Connection lost"):
                await submit
            assert controller._jobs == {}
        finally:
            submit.cancel()
            _kill_group(job.pid)

    @pytest.mark.asyncio
    async def test_repeated_start_returns_the_running_job(self) -> None:
        """A start the sandbox retried after a timeout must not start a second job."""
        controller = Controller()
        pid = await controller.submit("sleep 30", job_key=_JOB_KEY)
        try:
            assert await controller.submit("sleep 30", job_key=_JOB_KEY) == pid
            assert list(controller._jobs) == [pid]

            await controller.kill(pid, ack_seq=0)
            with pytest.raises(ToolException, match="has already ended"):
                await controller.submit("sleep 30", job_key=_JOB_KEY)
            assert controller._jobs == {}
        finally:
            _kill_group(pid)

    @pytest.mark.asyncio
    async def test_kill_key_of_an_unpolled_ended_job_reports_nothing_killed(
        self,
    ) -> None:
        controller = Controller()
        pid = await controller.submit("exit 3", job_key=_JOB_KEY)
        job = controller._jobs[pid]
        await job._process.wait()

        assert (await controller.kill_key(_JOB_KEY)).killed is False
        assert job._exit_code == 3

    @pytest.mark.asyncio
    async def test_kill_key_joins_termination_after_a_waiting_poll_retires_the_job(
        self,
    ) -> None:
        terminating = asyncio.Event()
        release_termination = asyncio.Event()
        job = MagicMock(pid=42, killed=True)

        async def poll(ack_seq: int, wait: float) -> PollResult:
            await terminating.wait()
            return PollResult(
                state="killed", exit_code=None, seq=1, stdout="", stderr=""
            )

        async def kill(ack_seq: int) -> tuple[int, str, str]:
            terminating.set()
            await release_termination.wait()
            return (1, "", "")

        job.poll = poll
        job.kill = kill
        job.cleanup = AsyncMock()
        job.await_termination = AsyncMock(side_effect=release_termination.wait)
        controller = Controller()
        controller._jobs[job.pid] = job
        controller._keyed_jobs[_JOB_KEY] = job
        with anyio.fail_after(1):
            waiting_poll = asyncio.create_task(
                controller.poll(job.pid, ack_seq=0, wait=10)
            )
            first_kill = asyncio.create_task(controller.kill_key(_JOB_KEY))
            await terminating.wait()
            await waiting_poll
            assert not first_kill.done()
            second_kill = asyncio.create_task(controller.kill_key(_JOB_KEY))
            await asyncio.sleep(0)
            assert not second_kill.done()
            release_termination.set()
            assert (await second_kill).killed is False
            assert (await first_kill).killed is True
        job.await_termination.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_kill_key_after_the_job_ended_reports_nothing_killed(self) -> None:
        controller = Controller()
        pid = await controller.submit("true", job_key=_JOB_KEY)
        await controller.kill(pid, ack_seq=0)

        assert (await controller.kill_key(_JOB_KEY)).killed is False


async def _poll_timed(
    controller: Controller, pid: int, wait: float
) -> tuple[PollResult, float]:
    start = time.monotonic()
    result = await controller.poll(pid, ack_seq=0, wait=wait)
    return result, time.monotonic() - start


async def _exited_with_output_read(job: Job) -> None:
    await _wait_for_exit(job)
    # Process exit does not guarantee the readers have buffered its output.
    await job._stdout_task
    await job._stderr_task


class TestWaitingPoll:
    """A poll with `wait` replies at the first of exit, output, expiry or kill."""

    @pytest.mark.asyncio
    async def test_returns_on_exit(self) -> None:
        controller = Controller()
        pid = await controller.submit("sleep 0.3; exit 3")

        result, elapsed = await _poll_timed(controller, pid, wait=10)

        assert (result.state, result.exit_code) == ("completed", 3)
        assert elapsed < 2

    @pytest.mark.asyncio
    async def test_returns_on_output_while_the_job_runs(self) -> None:
        controller = Controller()
        pid = await controller.submit("sleep 0.2; printf early; sleep 30")
        try:
            result, elapsed = await _poll_timed(controller, pid, wait=10)
        finally:
            _kill_group(pid)
            await _stop_job(controller._jobs[pid])

        assert (result.state, result.exit_code, result.stdout) == (
            "running",
            None,
            "early",
        )
        assert elapsed < 2

    @pytest.mark.asyncio
    async def test_output_waits_briefly_for_the_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exit that follows output inside the output wait shares its reply."""
        monkeypatch.setattr(job_module, "_OUTPUT_EXIT_WAIT_SECONDS", 5.0)
        controller = Controller()
        pid = await controller.submit("printf done; sleep 0.3; exit 3")

        result, _ = await _poll_timed(controller, pid, wait=10)

        assert (result.state, result.exit_code, result.stdout) == (
            "completed",
            3,
            "done",
        )

    @pytest.mark.asyncio
    async def test_returns_when_wait_expires(self) -> None:
        controller = Controller()
        pid = await controller.submit("sleep 30")
        try:
            result, elapsed = await _poll_timed(controller, pid, wait=0.3)
        finally:
            await controller.kill(pid, ack_seq=0)

        assert (result.state, result.stdout, result.stderr) == ("running", "", "")
        assert 0.3 <= elapsed < 2

    @pytest.mark.asyncio
    async def test_returns_on_kill(self) -> None:
        controller = Controller()
        pid = await controller.submit("sleep 30")
        job = controller._jobs[pid]
        poll = asyncio.create_task(_poll_timed(controller, pid, wait=10))
        await anyio.sleep(0.1)
        assert not poll.done()

        await controller.kill(pid, ack_seq=0)
        result, elapsed = await poll
        await _stop_job(job)

        assert result.state == "killed"
        assert elapsed < 5

    @pytest.mark.asyncio
    async def test_zero_wait_replies_without_waiting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        controller = Controller()
        pid = await controller.submit("sleep 30")
        sleep = AsyncMock(side_effect=AssertionError("waited with wait=0"))
        try:
            monkeypatch.setattr(asyncio, "sleep", sleep)
            result = await controller.poll(pid, ack_seq=0, wait=0)
        finally:
            monkeypatch.undo()
            await controller.kill(pid, ack_seq=0)

        assert (result.state, result.exit_code, result.stdout) == ("running", None, "")
        sleep.assert_not_called()


@pytest.mark.asyncio
async def test_poll_reports_exit_with_the_output_it_drains() -> None:
    controller = Controller()
    pid = await controller.submit("printf out; printf err 1>&2; exit 3")
    await _exited_with_output_read(controller._jobs[pid])

    result = await controller.poll(pid, ack_seq=0)

    assert (result.state, result.exit_code, result.stdout, result.stderr) == (
        "completed",
        3,
        "out",
        "err",
    )


@pytest.mark.asyncio
async def test_poll_reports_running_until_output_past_the_cap_is_drained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(job_module, "_MAX_POLL_OUTPUT_BYTES", 4)
    controller = Controller()
    pid = await controller.submit("printf 0123456789")
    await _exited_with_output_read(controller._jobs[pid])

    replies = []
    ack_seq = 0
    for _ in range(3):
        result = await controller.poll(pid, ack_seq)
        ack_seq = result.seq
        replies.append((result.state, result.exit_code, result.stdout))

    assert replies == [
        ("running", None, "0123"),
        ("running", None, "4567"),
        ("completed", 0, "89"),
    ]
