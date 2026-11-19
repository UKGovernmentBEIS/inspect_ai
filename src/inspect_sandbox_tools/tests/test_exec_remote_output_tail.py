"""Output a command leaves behind when it exits with the output buffer full.

A reader blocked on a full buffer cannot finish until a poll's reply frees
space, so the poll that sees the exit must not cancel it while a full reply is
buffered.
"""

import asyncio
import os
import shlex
import signal
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import anyio
import pytest
from inspect_sandbox_tools._remote_tools._exec_remote import _job as job_module
from inspect_sandbox_tools._remote_tools._exec_remote._controller import Controller
from inspect_sandbox_tools._remote_tools._exec_remote._job import Job
from inspect_sandbox_tools._remote_tools._exec_remote.tool_types import PollResult

_BUFFER = 64 * 1024
_REPLY = 16 * 1024

_WRITER = (
    "import sys\n"
    "size, stream = int(sys.argv[1]), getattr(sys, sys.argv[2])\n"
    "stream.write(''.join('%07d\\n' % i for i in range(size // 8 + 1))[:size])\n"
)


def _numbered(size: int) -> str:
    """`size` characters of numbered lines: lost, repeated or reordered output shows."""
    return "".join("%07d\n" % i for i in range(size // 8 + 1))[:size]


def _write_numbered(size: int, stream: str = "stdout") -> str:
    """A shell command that writes `_numbered(size)` to `stream`."""
    return shlex.join([sys.executable, "-c", _WRITER, str(size), stream])


@pytest.fixture
def small_buffers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_module, "_BACKPRESSURE_BUFFER_SIZE", _BUFFER)
    monkeypatch.setattr(job_module, "_MAX_POLL_OUTPUT_BYTES", _REPLY)


@pytest.fixture
async def controller() -> AsyncIterator[Controller]:
    controller = Controller()
    yield controller
    await controller.shutdown()


async def _poll_to_completion(
    controller: Controller, pid: int, wait: float = 0, ack_seq: int = 0
) -> tuple[PollResult, str, str]:
    """Poll until the job ends; return the last reply and all stdout and stderr."""
    stdout = stderr = ""
    with anyio.fail_after(30):
        while True:
            result = await controller.poll(pid, ack_seq, wait)
            ack_seq = result.seq
            stdout += result.stdout
            stderr += result.stderr
            if result.state != "running":
                return result, stdout, stderr


async def _wait_for_exit(job: Job) -> None:
    with anyio.fail_after(30):
        while job._process.returncode is None:
            await anyio.sleep(0.01)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize(
    "size",
    [_BUFFER + 12 * 1024 + 1, _BUFFER + 4 * _REPLY],
    ids=["a partial last reply", "a whole number of replies"],
)
@pytest.mark.usefixtures("small_buffers")
async def test_output_larger_than_the_buffer_is_kept_when_it_is_full_at_exit(
    controller: Controller, size: int, stream: str
) -> None:
    pid = await controller.submit(_write_numbered(size, stream))
    await _wait_for_exit(controller._jobs[pid])

    result, stdout, stderr = await _poll_to_completion(controller, pid)

    assert (result.state, result.exit_code) == ("completed", 0)
    assert {"stdout": stdout, "stderr": stderr} == {
        "stdout": "",
        "stderr": "",
        stream: _numbered(size),
    }


@pytest.mark.usefixtures("small_buffers")
async def test_output_larger_than_the_buffer_survives_a_slow_poll_after_exit(
    controller: Controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(job_module, "_READER_GRACE_SECONDS", 0.05)
    size = _BUFFER + 12 * _REPLY
    pid = await controller.submit(_write_numbered(size))
    await _wait_for_exit(controller._jobs[pid])

    first = await controller.poll(pid, 0)
    # the host takes longer over its next poll than the readers' grace
    await anyio.sleep(4 * job_module._READER_GRACE_SECONDS)
    result, rest, _ = await _poll_to_completion(controller, pid, ack_seq=first.seq)

    assert result.state == "completed"
    assert first.stdout + rest == _numbered(size)


@pytest.mark.usefixtures("small_buffers")
async def test_output_that_fills_the_buffer_while_a_poll_waits_for_the_readers_is_kept(
    controller: Controller, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    size = 4 * _BUFFER
    waiting = anyio.Event()
    wait_for_readers = Job._wait_for_readers

    async def signal_then_wait(job: Job, **kwargs: bool) -> None:
        waiting.set()
        await wait_for_readers(job, **kwargs)

    monkeypatch.setattr(Job, "_wait_for_readers", signal_then_wait)
    gate = tmp_path / "gate"
    # the leader exits at once; its child writes once `gate` exists
    pid = await controller.submit(
        f"(while [ ! -e {shlex.quote(str(gate))} ]; do sleep 0.01; done; "
        f"{_write_numbered(size)}) &"
    )
    output = ""

    async def poll_to_the_end() -> None:
        nonlocal output
        _, output, _ = await _poll_to_completion(controller, pid, wait=5.0)

    with anyio.fail_after(30):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(poll_to_the_end)
            await waiting.wait()
            gate.touch()

    assert output == _numbered(size)


@pytest.mark.usefixtures("small_buffers")
async def test_a_reader_that_fails_after_a_full_reply_still_raises_its_error(
    controller: Controller,
) -> None:
    """A poll that replied without waiting left the readers to a later poll."""
    size = _BUFFER + 4 * _REPLY
    pid = await controller.submit(_write_numbered(size, "stderr"))
    job = controller._jobs[pid]
    await _wait_for_exit(job)
    await job._stdout_task
    fail = anyio.Event()

    async def failing_reader() -> None:
        await fail.wait()
        raise OSError("read failed")

    job._stdout_task = asyncio.create_task(failing_reader())
    job._unawaited_readers = [job._stdout_task, job._stderr_task]

    first = await controller.poll(pid, 0)
    fail.set()
    await asyncio.wait([job._stdout_task])
    stderr, ack_seq = first.stderr, first.seq
    with pytest.raises(OSError, match="read failed"), anyio.fail_after(30):
        while True:
            reply = await controller.poll(pid, ack_seq)
            # the error comes from the poll that would have ended the job
            assert reply.state == "running"
            stderr, ack_seq = stderr + reply.stderr, reply.seq
    # raised once: the next poll ends the job, and no output is lost
    result, _, rest = await _poll_to_completion(controller, pid, ack_seq=ack_seq)

    assert (first.state, result.state) == ("running", "completed")
    assert stderr + rest == _numbered(size)


async def test_a_child_that_keeps_writing_does_not_hold_the_job_open(
    controller: Controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(job_module, "_BACKPRESSURE_BUFFER_SIZE", 4 * 1024 * 1024)
    monkeypatch.setattr(job_module, "_MAX_TAIL_BYTES", 2 * 1024 * 1024)
    monkeypatch.setattr(job_module, "_READER_GRACE_SECONDS", 0.1)
    pid = await controller.submit("yes & sleep 0.3; exit 3")
    job = controller._jobs[pid]
    try:
        # times out if the child's output keeps the job reported as running
        result, _, _ = await _poll_to_completion(controller, pid, wait=5.0)
    finally:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        # A cancelled reader leaves its pipe paused, so the transport never
        # sees the child's end: close it here, not when it is collected after
        # the event loop has closed.
        vars(job._process)["_transport"].close()

    assert (result.state, result.exit_code) == ("completed", 3)
