"""Tests for `emit_sample_event` and its thread-safe event channel.

`emit_sample_event` writes onto a `queue.SimpleQueue` so it can be invoked
from any thread (stdlib `logging` is thread-safe by contract; events may
originate from `anyio.to_thread.run_sync` worker threads, subprocess
capture threads, atexit handlers, etc.). The queue is unbounded, so
puts never block.
"""

import logging
import queue

import anyio

from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._logger import LoggerEvent, LoggingMessage
from inspect_ai.hooks._hooks import (
    SampleEvent,
    emit_sample_event,
)
from inspect_ai.log._samples import ActiveSample, _sample_active
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer


def test_emit_sample_event_unbounded_queue_never_blocks() -> None:
    """Many puts succeed without blocking on the unbounded queue."""
    sample_transcript = Transcript()
    active = ActiveSample(
        task="test_task",
        log_location="test",
        model="test_model",
        sample=Sample(input="test"),
        epoch=1,
        message_limit=None,
        token_limit=None,
        cost_limit=None,
        time_limit=None,
        working_limit=None,
        fails_on_error=True,
        transcript=sample_transcript,
        sandboxes={},
        checkpointer=_NoopCheckpointer(),
        eval_set_id=None,
        run_id="run-1",
        eval_id="eval-1",
    )
    sample_token = _sample_active.set(active)
    init_transcript(sample_transcript)

    active.event_queue = queue.SimpleQueue()

    try:
        event = LoggerEvent(
            message=LoggingMessage(level="info", message="filler", created=0.0)
        )

        for _ in range(2000):
            emit_sample_event(
                eval_set_id=None,
                run_id="run-1",
                eval_id="eval-1",
                sample_id="sample-1",
                event=event,
            )

        assert active.event_queue.qsize() == 2000
        # Pulling them back out should also work without exceptions.
        for _ in range(2000):
            item = active.event_queue.get_nowait()
            assert isinstance(item, SampleEvent)
    finally:
        _sample_active.reset(sample_token)
        init_transcript(Transcript())


def test_emit_sample_event_thread_safe_from_worker_thread() -> None:
    """Producing from a non-main thread must not raise.

    Regression test for https://github.com/UKGovernmentBEIS/inspect_ai/issues/4003
    — `emit_sample_event` used to call `anyio.MemoryObjectSendStream.send_nowait`,
    which under the trio backend invokes `trio._core.reschedule` and raises
    `RuntimeError: must be called from async context` from any thread that is
    not the event-loop thread.

    Spawns the producers via ``copy_context().run(...)`` because plain
    ``threading.Thread`` does NOT inherit ``ContextVar``s from the parent;
    that's the same context-copy mechanism ``anyio.to_thread.run_sync``
    uses internally, which is precisely the call path that triggered the
    original bug.
    """
    import contextvars
    import threading

    sample_transcript = Transcript()
    active = ActiveSample(
        task="test_task",
        log_location="test",
        model="test_model",
        sample=Sample(input="test"),
        epoch=1,
        message_limit=None,
        token_limit=None,
        cost_limit=None,
        time_limit=None,
        working_limit=None,
        fails_on_error=True,
        transcript=sample_transcript,
        sandboxes={},
        checkpointer=_NoopCheckpointer(),
        eval_set_id=None,
        run_id="run-1",
        eval_id="eval-1",
    )
    sample_token = _sample_active.set(active)
    init_transcript(sample_transcript)

    active.event_queue = queue.SimpleQueue()

    event = LoggerEvent(
        message=LoggingMessage(level="warning", message="from-thread", created=0.0)
    )

    errors: list[BaseException] = []

    def producer() -> None:
        try:
            for _ in range(50):
                emit_sample_event(
                    eval_set_id=None,
                    run_id="run-1",
                    eval_id="eval-1",
                    sample_id="sample-1",
                    event=event,
                )
        except BaseException as exc:
            errors.append(exc)

    try:
        ctx = contextvars.copy_context()
        threads = [threading.Thread(target=ctx.run, args=(producer,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"emit_sample_event raised from a worker thread: {errors}"
        assert active.event_queue.qsize() == 50 * 4
    finally:
        _sample_active.reset(sample_token)
        init_transcript(Transcript())


async def test_logging_from_worker_thread_does_not_crash_eval() -> None:
    """End-to-end regression for issue #4003.

    A solver that logs from inside ``anyio.to_thread.run_sync`` used to crash
    the eval under the trio backend with ``RuntimeError: must be called from
    async context``. The eval must complete with status ``success`` on both
    asyncio and trio.
    """
    from inspect_ai import Task, eval_async
    from inspect_ai.solver import solver

    # Use a logger under the inspect_ai namespace so it goes through the
    # inspect_ai LogHandler (which routes records into the active sample's
    # transcript stream — the path that used to crash from worker threads).
    worker_logger = logging.getLogger("inspect_ai.tests.test_sample_events.worker")

    def sync_work_that_logs() -> str:
        # WARNING (not INFO) so the record clears the root logger's default
        # level filter (DEFAULT_LOG_LEVEL is "warning").
        worker_logger.warning("hello from worker thread")
        return "done"

    @solver
    def thread_logger_solver():
        async def solve(state, generate):
            await anyio.to_thread.run_sync(sync_work_that_logs)
            return state

        return solve

    task = Task(
        dataset=[Sample(input="x", target="x")],
        solver=thread_logger_solver(),
    )
    log = (await eval_async(task, model="mockllm/model"))[0]
    assert log.status == "success", f"status={log.status} error={log.error}"
