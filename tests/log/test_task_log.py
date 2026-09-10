import tempfile
import types
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, BinaryIO, cast
from unittest.mock import patch
from zipfile import ZipExtFile

import anyio
import pytest
from test_helpers.task_logger import TaskLoggerShim

from inspect_ai import Task, eval
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.run import eval_run
from inspect_ai._eval.task import log as task_log_module
from inspect_ai._eval.task.log import (
    TaskLogger,
    resolve_package_revision,
    resolve_task_distribution,
)
from inspect_ai._util.background import background_task_group, set_background_task_group
from inspect_ai._util.error import EvalError
from inspect_ai._util.git import GitContext
from inspect_ai._util.package import DirectUrl, VcsInfo
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._timeline import timeline_build
from inspect_ai.log import EvalRevision
from inspect_ai.log._file import (
    read_eval_log_async,
    read_eval_log_sample_async,
    read_eval_log_sample_summaries_async,
)
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalRetryError,
    EvalSample,
    EvalSampleSummary,
    EvalSpec,
    EvalStats,
)
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.eval import EvalRecorder
from inspect_ai.log._recorders.json import JSONRecorder
from inspect_ai.log._recorders.recorder import Recorder, SampleRecordKey
from inspect_ai.model import GenerateConfig, ModelOutput, get_model
from inspect_ai.model._chat_message import ChatMessageUser


def _fake_dist(name: str, version: str = "1.0.0") -> types.SimpleNamespace:
    return types.SimpleNamespace(name=name, version=version)


class TestResolveTaskDistribution:
    def test_returns_none_when_task_registry_name_is_none(self):
        assert resolve_task_distribution(None) is None

    def test_returns_none_when_task_not_in_registry(self):
        with patch("inspect_ai._eval.task.log.registry_lookup", return_value=None):
            assert resolve_task_distribution("pkg/some_task") is None

    def test_returns_none_when_no_distribution_for_object(self):
        with (
            patch("inspect_ai._eval.task.log.registry_lookup", return_value=object()),
            patch(
                "inspect_ai._eval.task.log.get_distribution_for_object",
                return_value=None,
            ),
        ):
            assert resolve_task_distribution("pkg/some_task") is None

    def test_returns_none_for_inspect_ai_itself(self):
        with (
            patch("inspect_ai._eval.task.log.registry_lookup", return_value=object()),
            patch(
                "inspect_ai._eval.task.log.get_distribution_for_object",
                return_value=_fake_dist("inspect-ai"),
            ),
        ):
            assert resolve_task_distribution("inspect_ai/some_task") is None

    def test_returns_distribution_for_external_task(self):
        dist = _fake_dist("harder-tasks-judge-run", "0.1.0")
        with (
            patch("inspect_ai._eval.task.log.registry_lookup", return_value=object()),
            patch(
                "inspect_ai._eval.task.log.get_distribution_for_object",
                return_value=dist,
            ),
        ):
            assert resolve_task_distribution("harder_tasks/judge_run") is dist


@pytest.mark.anyio
async def test_eval_run_cleans_initialized_loggers_when_setup_fails(
    monkeypatch,
) -> None:
    cleaned_loggers: list[object] = []
    init_count = 0

    class FakeTaskLogger:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def init(self) -> None:
            nonlocal init_count
            init_count += 1
            if init_count == 2:
                raise RuntimeError("setup failed")

        async def cleanup(self) -> None:
            cleaned_loggers.append(self)

    monkeypatch.setattr("inspect_ai._eval.run.TaskLogger", FakeTaskLogger)

    tasks = [
        Task(dataset=[Sample(input="input", target="target")]),
        Task(dataset=[Sample(input="input", target="target")]),
    ]
    model = get_model("mockllm/model")
    resolved_tasks = resolve_tasks(tasks, {}, model, None, None, None)

    with pytest.raises(RuntimeError, match="setup failed"):
        await eval_run(
            eval_set_id=None,
            run_id="run-id",
            tasks=resolved_tasks,
            parallel=1,
            eval_config=EvalConfig(log_realtime=True),
            eval_checkpoint=None,
            recorder=cast(Recorder, object()),
            header_only=False,
            run_samples=False,
        )

    assert len(cleaned_loggers) == 1


def _sample() -> EvalSample:
    return EvalSample(id="sample", epoch=1, input="question", target="answer")


def _eval_spec() -> EvalSpec:
    return EvalSpec(
        created="2026-05-18T00:00:00+00:00",
        task="task",
        model="mockllm/model",
        dataset=EvalDataset(),
        config=EvalConfig(),
    )


class _FlushRecorder:
    def __init__(self, location: str = "test.eval") -> None:
        self.location = location
        self.init_count = 0
        self.discard_count = 0
        self.flush_count = 0
        self.flush_started = anyio.Event()
        self.allow_flush = anyio.Event()
        self.allow_flush.set()
        self.fail_times = 0

    async def log_init(
        self, eval_spec: EvalSpec, location: str | None = None, clean: bool = True
    ) -> str:
        self.init_count += 1
        return location or self.location

    async def log_discard(
        self, eval_spec: EvalSpec, *, keep_destination: bool = False
    ) -> None:
        self.discard_count += 1

    async def flush(self, eval_spec: EvalSpec) -> None:
        self.flush_count += 1
        self.flush_started.set()
        await self.allow_flush.wait()
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("flush failed")

    async def log_start(self, eval_spec: EvalSpec, plan: EvalPlan) -> None:
        pass

    async def log_sample(
        self, eval_spec: EvalSpec, sample: EvalSample, *, write_through: bool = False
    ) -> None:
        pass

    async def buffered_sample(
        self,
        eval_spec: EvalSpec,
        id: str | int,
        epoch: int,
        *,
        exclude_fields: set[str] | None = None,
    ) -> EvalSample | None:
        return None


class _FlushBufferDB:
    def __init__(self) -> None:
        self.removed: list[tuple[str | int, int]] = []
        self.removed_samples = anyio.Event()
        self.completed_metadata: list[dict[str, Any] | None] = []

    def complete_sample(
        self,
        summary: EvalSampleSummary,
        sample_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.completed_metadata.append(sample_metadata)

    def remove_samples(self, samples: list[tuple[str | int, int]]) -> None:
        self.removed.extend(samples)
        self.removed_samples.set()

    def cleanup(self) -> None:
        pass


class _FinishRecorder(_FlushRecorder):
    """A flush recorder whose ``log_finish`` can be paused mid-call."""

    def __init__(self, location: str = "test.eval") -> None:
        super().__init__(location)
        self.log_finish_entered = anyio.Event()
        self.allow_log_finish = anyio.Event()
        self.allow_log_finish.set()

    async def log_finish(self, *args: Any, **kwargs: Any) -> Any:
        self.log_finish_entered.set()
        await self.allow_log_finish.wait()
        return None


def _flush_logger(
    *,
    flush_buffer: int = 2,
    buffer_db: Any | None = None,
    recorder: _FlushRecorder | None = None,
) -> TaskLoggerShim:
    logger = TaskLoggerShim(buffer_db or _FlushBufferDB())
    logger.recorder = cast(Recorder, recorder or _FlushRecorder())
    logger.eval = _eval_spec()
    logger.flush_buffer = flush_buffer
    logger.flush_pending = []
    logger._samples_completed = 0
    return logger


@asynccontextmanager
async def _running_stale_flush_timer(
    logger: TaskLogger, *, start: bool = True
) -> AsyncIterator[None]:
    original_tg = background_task_group()
    async with anyio.create_task_group() as background_tg:
        set_background_task_group(background_tg)
        try:
            if start:
                await logger._start_stale_flush_timer_if_needed()
            yield
        finally:
            await logger._stop_stale_flush_timer()
            set_background_task_group(original_tg)


@pytest.mark.anyio
async def test_task_logger_flushes_pending_samples_at_threshold() -> None:
    recorder = _FlushRecorder()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=2, buffer_db=buffer_db, recorder=recorder)

    async with _running_stale_flush_timer(logger, start=False):
        await logger.complete_sample(_sample(), flush=True)
        assert recorder.flush_count == 0
        assert logger.flush_pending == [("sample", 1)]

        second = _sample().model_copy(update={"id": "sample-2"})
        await logger.complete_sample(second, flush=True)

    assert recorder.flush_count == 1
    assert logger.flush_pending == []
    assert buffer_db.removed == [("sample", 1), ("sample-2", 1)]


@pytest.mark.anyio
async def test_task_logger_forwards_full_metadata_to_buffer() -> None:
    recorder = _FlushRecorder()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(buffer_db=buffer_db, recorder=recorder)
    metadata = {"world": {f"cell-{i}": {"active": True} for i in range(80)}}

    await logger.complete_sample(
        _sample().model_copy(update={"metadata": metadata}), flush=False
    )

    assert buffer_db.completed_metadata == [metadata]


@pytest.mark.anyio
async def test_task_logger_samples_logged_counts_distinct_samples() -> None:
    # a re-log of the same (id, epoch) — a requeued sample's re-run — replaces
    # the sample's log entry rather than adding one, so it must not inflate
    # samples_logged (consumed by eval-set's completeness check: an inflated
    # count could classify a drained log complete and silently drop the
    # abandoned remainder)
    logger = _flush_logger(flush_buffer=10)

    await logger.complete_sample(_sample(), flush=False)
    assert logger.samples_logged == 1
    await logger.complete_sample(_sample(), flush=False)
    assert logger.samples_logged == 1

    other_epoch = EvalSample(id="sample", epoch=2, input="question", target="answer")
    await logger.complete_sample(other_epoch, flush=False)
    assert logger.samples_logged == 2


@pytest.mark.anyio
async def test_task_logger_samples_logged_excludes_cancelled_samples() -> None:
    # a cancellation-resolved sample (operator `sample cancel`, or a drain
    # landing while the sample materialized) is in the log but is not a
    # resolution — counting it toward samples_logged could classify a drained
    # log complete and silently drop those samples from a later eval-set
    # re-invocation. A re-log of the same key (a requeue's re-run superseding
    # the cancelled record) counts again.
    logger = _flush_logger(flush_buffer=10)

    cancelled = _sample().model_copy(
        update={
            "error": EvalError(
                message="CancelledError('cancelled by operator')",
                traceback="",
                traceback_ansi="",
            )
        }
    )
    await logger.complete_sample(cancelled, flush=False)
    assert logger.samples_logged == 0

    errored = _sample().model_copy(
        update={
            "error": EvalError(
                message="RuntimeError('boom')", traceback="", traceback_ansi=""
            )
        }
    )
    await logger.complete_sample(
        errored.model_copy(update={"id": "sample-2"}), flush=False
    )
    assert logger.samples_logged == 1

    # requeued re-run supersedes the cancelled record
    await logger.complete_sample(_sample(), flush=False)
    assert logger.samples_logged == 2


@pytest.mark.parametrize(
    ("appended_key", "expected_pending"),
    [
        (("sample-2", 1), [("sample-2", 1)]),
        (("sample", 1), [("sample", 1)]),
    ],
)
@pytest.mark.anyio
async def test_task_logger_flush_removes_only_snapshot_pending_samples(
    appended_key: tuple[str | int, int],
    expected_pending: list[tuple[str | int, int]],
) -> None:
    recorder = _FlushRecorder()
    recorder.allow_flush = anyio.Event()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger.flush_pending = [("sample", 1)]

    async with _running_stale_flush_timer(logger, start=False):
        async with anyio.create_task_group() as tg:
            tg.start_soon(logger._flush_pending_samples)
            await recorder.flush_started.wait()
            logger.flush_pending.append(appended_key)
            recorder.allow_flush.set()

    assert recorder.flush_count == 1
    assert logger.flush_pending == expected_pending
    assert buffer_db.removed == [("sample", 1)]


@pytest.mark.anyio
async def test_task_logger_concurrent_flushes_do_not_double_remove_pending() -> None:
    recorder = _FlushRecorder()
    recorder.allow_flush = anyio.Event()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger.flush_pending = [("sample", 1)]

    async with anyio.create_task_group() as tg:
        tg.start_soon(logger._flush_pending_samples)
        await recorder.flush_started.wait()
        tg.start_soon(logger._flush_pending_samples)
        recorder.allow_flush.set()

    assert recorder.flush_count == 1
    assert logger.flush_pending == []
    assert buffer_db.removed == [("sample", 1)]


@pytest.mark.anyio
async def test_task_logger_threshold_flush_cancels_scheduled_stale_flush() -> None:
    recorder = _FlushRecorder()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=2, buffer_db=buffer_db, recorder=recorder)
    logger._stale_flush_interval = 60

    async with _running_stale_flush_timer(logger, start=False):
        await logger.complete_sample(_sample(), flush=True)
        assert logger._stale_flush_cancel_scope is not None

        second = _sample().model_copy(update={"id": "sample-2"})
        await logger.complete_sample(second, flush=True)

        assert logger._stale_flush_cancel_scope is None

    assert recorder.flush_count == 1
    assert logger.flush_pending == []
    assert buffer_db.removed == [("sample", 1), ("sample-2", 1)]


async def _call_log_finish(logger: TaskLogger) -> None:
    await logger.log_finish("success", EvalStats())


@pytest.mark.anyio
async def test_log_finish_cancels_stale_timer_rearmed_by_racing_flush() -> None:
    # Repro: an on-demand flush_samples() is mid-flush (holding _flush_lock) when
    # a new sample appends to pending; log_finish() runs concurrently. The flush
    # re-arms the stale-flush timer *outside* _flush_lock — after log_finish's
    # pre-lock stop — so without a second stop the timer would survive finish
    # (armed scope + empty pending). log_finish must cancel it.
    recorder = _FinishRecorder()
    recorder.allow_flush = anyio.Event()
    recorder.allow_log_finish = anyio.Event()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger.header_only = False
    logger._stale_flush_interval = 60
    logger.flush_pending = [("sample", 1)]

    async with _running_stale_flush_timer(logger, start=False):
        async with anyio.create_task_group() as tg:
            tg.start_soon(logger.flush_samples)
            await recorder.flush_started.wait()

            # a sample completes during the flush → the flush re-arms a timer
            # for the leftover pending sample once it releases _flush_lock
            logger.flush_pending.append(("sample-2", 1))

            tg.start_soon(_call_log_finish, logger)
            recorder.allow_flush.set()

            # finish is now parked inside recorder.log_finish (holding _flush_lock,
            # _finished not yet set); wait for the racing re-arm to land
            await recorder.log_finish_entered.wait()
            while logger._stale_flush_cancel_scope is None:
                await anyio.sleep(0)

            recorder.allow_log_finish.set()

        # both tasks joined: finish must have cancelled the racing timer
        assert logger._finished is True
        assert logger.flush_pending == []
        assert logger._stale_flush_cancel_scope is None


@pytest.mark.anyio
async def test_flush_samples_failure_rearms_stale_timer() -> None:
    # an on-demand flush stops the stale timer before flushing; if the flush
    # fails it must re-arm so below-threshold pending samples are still retried
    # automatically (not stranded until the next sample completes), and the
    # error still propagates to the caller.
    recorder = _FlushRecorder()
    recorder.fail_times = 1
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger._stale_flush_interval = 60
    logger.flush_pending = [("sample", 1)]

    async with _running_stale_flush_timer(logger, start=False):
        with pytest.raises(RuntimeError, match="flush failed"):
            await logger.flush_samples()

        # samples weren't dropped, and a stale timer is now armed to retry them
        assert logger.flush_pending == [("sample", 1)]
        assert buffer_db.removed == []
        assert logger._stale_flush_cancel_scope is not None


@pytest.mark.anyio
async def test_task_logger_threshold_flush_prevents_racing_stale_start(
    monkeypatch,
) -> None:
    recorder = _FlushRecorder()
    recorder.allow_flush = anyio.Event()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=2, buffer_db=buffer_db, recorder=recorder)
    first_stale_start_attempted = anyio.Event()
    allow_first_stale_start = anyio.Event()
    original_start_stale_flush_timer = logger._start_stale_flush_timer_if_needed
    original_flush_pending = logger._flush_pending_samples

    async def gated_start_stale_flush_timer() -> None:
        first_stale_start_attempted.set()
        await allow_first_stale_start.wait()
        await original_start_stale_flush_timer()

    async def observed_flush_pending(
        *, stale_flush_generation: int | None = None
    ) -> None:
        await original_flush_pending(stale_flush_generation=stale_flush_generation)
        assert logger._stale_flush_cancel_scope is None

    monkeypatch.setattr(
        logger, "_start_stale_flush_timer_if_needed", gated_start_stale_flush_timer
    )
    monkeypatch.setattr(logger, "_flush_pending_samples", observed_flush_pending)

    async def complete_sample(sample: EvalSample) -> None:
        await logger.complete_sample(sample, flush=True)

    async with _running_stale_flush_timer(logger, start=False):
        async with anyio.create_task_group() as tg:
            tg.start_soon(complete_sample, _sample())
            with anyio.fail_after(5):
                await first_stale_start_attempted.wait()

            second = _sample().model_copy(update={"id": "sample-2"})
            tg.start_soon(complete_sample, second)
            with anyio.fail_after(5):
                await recorder.flush_started.wait()

            allow_first_stale_start.set()
            recorder.allow_flush.set()

    assert recorder.flush_count == 1
    assert logger.flush_pending == []
    assert logger._stale_flush_cancel_scope is None
    assert buffer_db.removed == [("sample", 1), ("sample-2", 1)]


@pytest.mark.anyio
async def test_task_logger_start_stale_flush_timer_rolls_back_failed_start(
    monkeypatch,
) -> None:
    recorder = _FlushRecorder()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger._stale_flush_interval = 0.01
    logger.flush_pending = [("sample", 1)]

    def fail_background_start(*args: object, **kwargs: object) -> None:
        raise RuntimeError("background unavailable")

    monkeypatch.setattr(
        "inspect_ai._eval.task.log.run_in_background", fail_background_start
    )

    with pytest.raises(RuntimeError, match="background unavailable"):
        await logger._start_stale_flush_timer_if_needed()

    monkeypatch.undo()

    async with _running_stale_flush_timer(logger, start=False):
        await logger._start_stale_flush_timer_if_needed()
        with anyio.fail_after(5):
            await buffer_db.removed_samples.wait()

    assert recorder.flush_count == 1
    assert logger.flush_pending == []
    assert buffer_db.removed == [("sample", 1)]


@pytest.mark.anyio
async def test_task_logger_schedules_stale_flush_when_pending_appears() -> None:
    recorder = _FlushRecorder()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger._stale_flush_interval = 0.01

    async with _running_stale_flush_timer(logger, start=False):
        await logger.complete_sample(_sample(), flush=True)
        with anyio.fail_after(5):
            await buffer_db.removed_samples.wait()

    assert recorder.flush_count == 1
    assert logger.flush_pending == []
    assert buffer_db.removed == [("sample", 1)]


@pytest.mark.anyio
async def test_task_logger_scheduled_stale_flush_flushes_below_threshold_pending_samples() -> (
    None
):
    recorder = _FlushRecorder()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger._stale_flush_interval = 0.01

    async with _running_stale_flush_timer(logger):
        await logger.complete_sample(_sample(), flush=True)

        with anyio.fail_after(5):
            await buffer_db.removed_samples.wait()

    assert recorder.flush_count == 1
    assert logger.flush_pending == []
    assert buffer_db.removed == [("sample", 1)]


@pytest.mark.anyio
async def test_task_logger_stale_flush_reschedules_pending_tail() -> None:
    recorder = _FlushRecorder()
    recorder.allow_flush = anyio.Event()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger._stale_flush_interval = 0.01
    logger.flush_pending = [("sample", 1)]

    async with _running_stale_flush_timer(logger):
        with anyio.fail_after(5):
            await recorder.flush_started.wait()
        logger.flush_pending.append(("sample-2", 1))
        recorder.allow_flush.set()
        with anyio.fail_after(5):
            await buffer_db.removed_samples.wait()
        assert logger.flush_pending == [("sample-2", 1)]
        buffer_db.removed_samples = anyio.Event()
        recorder.flush_started = anyio.Event()
        with anyio.fail_after(5):
            await buffer_db.removed_samples.wait()

    assert recorder.flush_count == 2
    assert logger.flush_pending == []
    assert buffer_db.removed == [("sample", 1), ("sample-2", 1)]


@pytest.mark.anyio
async def test_task_logger_stop_prevents_pending_tail_reschedule() -> None:
    recorder = _FlushRecorder()
    recorder.allow_flush = anyio.Event()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger._stale_flush_interval = 0.01
    logger.flush_pending = [("sample", 1)]
    stop_finished = anyio.Event()

    async def stop_timer() -> None:
        await logger._stop_stale_flush_timer()
        stop_finished.set()

    async with _running_stale_flush_timer(logger):
        with anyio.fail_after(5):
            await recorder.flush_started.wait()
        logger.flush_pending.append(("sample-2", 1))
        async with anyio.create_task_group() as stopper_tg:
            stopper_tg.start_soon(stop_timer)
            await anyio.sleep(0)
            assert not stop_finished.is_set()
            recorder.allow_flush.set()
            with anyio.fail_after(5):
                await stop_finished.wait()
        with anyio.fail_after(5):
            await buffer_db.removed_samples.wait()
        assert logger.flush_pending == [("sample-2", 1)]
        assert logger._stale_flush_cancel_scope is None
        await anyio.sleep(0)
        assert recorder.flush_count == 1

    assert recorder.flush_count == 1
    assert logger.flush_pending == [("sample-2", 1)]
    assert buffer_db.removed == [("sample", 1)]


@pytest.mark.anyio
async def test_task_logger_stop_during_tail_reschedule_gap_prevents_timer(
    monkeypatch,
) -> None:
    recorder = _FlushRecorder()
    recorder.allow_flush = anyio.Event()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger.flush_pending = [("sample", 1)]
    reschedule_attempted = anyio.Event()
    allow_reschedule = anyio.Event()
    original_arm_stale_flush_timer = logger._arm_stale_flush_timer

    async def gated_arm_stale_flush_timer(*, generation: int | None = None) -> None:
        reschedule_attempted.set()
        await allow_reschedule.wait()
        await original_arm_stale_flush_timer(generation=generation)

    async def flush_pending() -> None:
        await logger._flush_pending_samples(
            stale_flush_generation=logger._stale_flush_generation
        )

    monkeypatch.setattr(logger, "_arm_stale_flush_timer", gated_arm_stale_flush_timer)

    async with _running_stale_flush_timer(logger, start=False):
        async with anyio.create_task_group() as tg:
            tg.start_soon(flush_pending)
            with anyio.fail_after(5):
                await recorder.flush_started.wait()
            logger.flush_pending.append(("sample-2", 1))
            recorder.allow_flush.set()
            with anyio.fail_after(5):
                await reschedule_attempted.wait()
            await logger._stop_stale_flush_timer()
            allow_reschedule.set()

        assert logger.flush_pending == [("sample-2", 1)]
        assert logger._stale_flush_cancel_scope is None
        await anyio.sleep(0)
        assert recorder.flush_count == 1

    assert recorder.flush_count == 1
    assert buffer_db.removed == [("sample", 1)]


@pytest.mark.anyio
async def test_task_logger_new_work_during_stop_does_not_enable_old_tail_reschedule() -> (
    None
):
    recorder = _FlushRecorder()
    recorder.allow_flush = anyio.Event()
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger._stale_flush_interval = 0.01
    logger.flush_pending = [("sample", 1)]
    stop_finished = anyio.Event()

    async def stop_timer() -> None:
        await logger._stop_stale_flush_timer()
        stop_finished.set()

    async with _running_stale_flush_timer(logger):
        with anyio.fail_after(5):
            await recorder.flush_started.wait()
        logger._stale_flush_interval = 5
        logger.flush_pending.append(("sample-2", 1))
        async with anyio.create_task_group() as stopper_tg:
            stopper_tg.start_soon(stop_timer)
            await anyio.sleep(0)
            assert not stop_finished.is_set()
            await logger.complete_sample(
                _sample().model_copy(update={"id": "sample-3"}), flush=True
            )
            recorder.allow_flush.set()
            with anyio.fail_after(5):
                await stop_finished.wait()
        with anyio.fail_after(5):
            await buffer_db.removed_samples.wait()
        assert logger.flush_pending == [("sample-2", 1), ("sample-3", 1)]
        assert logger._stale_flush_cancel_scope is None
        await anyio.sleep(0)
        assert recorder.flush_count == 1

    assert recorder.flush_count == 1
    assert logger.flush_pending == [("sample-2", 1), ("sample-3", 1)]
    assert buffer_db.removed == [("sample", 1)]


@pytest.mark.anyio
async def test_task_logger_stop_prevents_failed_stale_flush_retry() -> None:
    recorder = _FlushRecorder()
    recorder.allow_flush = anyio.Event()
    recorder.fail_times = 1
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger._stale_flush_interval = 0.01
    logger.flush_pending = [("sample", 1)]
    stop_finished = anyio.Event()

    async def stop_timer() -> None:
        await logger._stop_stale_flush_timer()
        stop_finished.set()

    async with _running_stale_flush_timer(logger):
        with anyio.fail_after(5):
            await recorder.flush_started.wait()
        async with anyio.create_task_group() as stopper_tg:
            stopper_tg.start_soon(stop_timer)
            await anyio.sleep(0)
            assert not stop_finished.is_set()
            recorder.allow_flush.set()
            with anyio.fail_after(5):
                await stop_finished.wait()
        assert logger.flush_pending == [("sample", 1)]
        assert logger._stale_flush_cancel_scope is None
        await anyio.sleep(0)
        assert recorder.flush_count == 1

    assert recorder.flush_count == 1
    assert logger.flush_pending == [("sample", 1)]
    assert buffer_db.removed == []


@pytest.mark.anyio
async def test_task_logger_scheduled_stale_flush_failure_recovers_on_next_timer(
    monkeypatch,
) -> None:
    recorder = _FlushRecorder()
    recorder.fail_times = 1
    buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db, recorder=recorder)
    logger.flush_pending = [("sample", 1)]
    logger._stale_flush_interval = 0.01
    warnings: list[str] = []
    warning_logged = anyio.Event()

    def capture_warning(message: str, *args: object, **kwargs: object) -> None:
        warnings.append(message % args)
        warning_logged.set()

    monkeypatch.setattr(task_log_module.logger, "warning", capture_warning)

    async with _running_stale_flush_timer(logger):
        with anyio.fail_after(5):
            await warning_logged.wait()
        assert logger.flush_pending == [("sample", 1)]

        with anyio.fail_after(5):
            await buffer_db.removed_samples.wait()

    assert recorder.flush_count >= 2
    assert logger.flush_pending == []
    assert any("Stale eval log flush failed" in warning for warning in warnings)


@pytest.mark.anyio
async def test_task_logger_reinit_waits_for_in_flight_stale_flush_and_restarts(
    monkeypatch,
    tmp_path,
) -> None:
    recorder = _FlushRecorder(str(tmp_path / "reinit.eval"))
    recorder.allow_flush = anyio.Event()
    old_buffer_db = _FlushBufferDB()
    new_buffer_db = _FlushBufferDB()
    logger = _flush_logger(flush_buffer=10, buffer_db=old_buffer_db, recorder=recorder)
    logger._stale_flush_interval = 0.01
    logger.flush_pending = [("sample", 1)]
    logger._samples_completed = 1
    original_eval_id = logger.eval.eval_id

    monkeypatch.setattr(
        task_log_module, "SampleBufferDatabase", lambda **kwargs: new_buffer_db
    )

    async with _running_stale_flush_timer(logger):
        with anyio.fail_after(5):
            await recorder.flush_started.wait()
        recorder.allow_flush.set()
        await logger.reinit()
        await logger.complete_sample(
            _sample().model_copy(update={"id": "after-retry"}), flush=True
        )
        with anyio.fail_after(5):
            await new_buffer_db.removed_samples.wait()

    assert old_buffer_db.removed == [("sample", 1)]
    assert new_buffer_db.removed == [("after-retry", 1)]
    assert recorder.init_count == 1
    # the attempt never finished its log, so reinit released its recorder entry
    assert recorder.discard_count == 1
    assert logger.eval.eval_id != original_eval_id
    assert logger.samples_completed == 1
    assert logger.flush_pending == []


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
async def test_task_logger_reinit_releases_unfinished_attempt_but_keeps_its_log(
    recorder_type: type, tmp_path: Path
) -> None:
    # an attempt that never reached log_finish (a log write failed) still
    # holds its recorder entry (open temp zip); reinit releases it, as discard
    # does for an abandoned attempt, but leaves the `started` destination its
    # flushes wrote: it holds every sample flushed so far and is the next
    # attempt's sample source
    recorder = recorder_type(str(tmp_path))
    logger = _seed_logger(recorder)
    logger.eval = logger.eval.model_copy(
        update={"config": EvalConfig(log_realtime=False)}
    )
    logger._location = await recorder.log_init(logger.eval)
    await logger.log_start(EvalPlan())
    failed_location = logger.location
    assert Path(failed_location).exists()
    (failed_key,) = recorder.data
    assert not logger.finished
    assert logger.destination_written

    await logger.reinit()

    assert Path(failed_location).exists()
    assert failed_key not in recorder.data
    assert len(recorder.data) == 1
    assert logger.location != failed_location
    await logger.log_start(EvalPlan())
    assert Path(logger.location).exists()


async def test_task_logger_reinit_leaves_finished_attempt_log(
    tmp_path: Path,
) -> None:
    # a finished attempt's log (the errored log the retry seeds from) is not
    # a stray: reinit must leave it in place
    recorder = EvalRecorder(str(tmp_path))
    logger = _seed_logger(recorder)
    logger.eval = logger.eval.model_copy(
        update={"config": EvalConfig(log_realtime=False)}
    )
    logger._location = await recorder.log_init(logger.eval)
    await logger.log_start(EvalPlan())
    await logger.log_finish("error", EvalStats(), None, None, _error("boom"))
    finished_location = logger.location
    assert logger.finished

    await logger.reinit()

    assert Path(finished_location).exists()
    assert not logger.finished
    assert len(recorder.data) == 1


@pytest.mark.anyio
async def test_log_start_flushes_immediately() -> None:
    recorder = _FlushRecorder()
    logger = _flush_logger(recorder=recorder)

    await logger.log_start(EvalPlan())

    assert recorder.flush_count == 1


@pytest.mark.anyio
async def test_read_sample_disk_fallback_returns_none_when_no_destination(
    tmp_path,
) -> None:
    # before log_start's flush the destination log doesn't exist; a ctl
    # per-sample read must degrade to None (like a not-found sample) rather
    # than raising
    recorder = _FlushRecorder()
    logger = _flush_logger(recorder=recorder)
    logger._location = str(tmp_path / "missing.eval")

    assert await logger.read_sample("sample", 1) is None


# ---------------------------------------------------------------------------
# seed_from_prior: a retry attempt's log starts out holding the prior
# attempt's sample records (design/retry-seeded-attempt-log.md)
# ---------------------------------------------------------------------------


def _error(message: str) -> EvalError:
    return EvalError(message=message, traceback="", traceback_ansi="")


async def _write_prior_log(recorder: Recorder, samples: list[EvalSample]) -> str:
    spec = _eval_spec().model_copy(update={"eval_id": "prior-attempt"})
    location = await recorder.log_init(spec)
    await recorder.log_start(spec, EvalPlan())
    for sample in samples:
        await recorder.log_sample(spec, sample)
    await recorder.log_finish(spec, "error", EvalStats(), None, None, _error("boom"))
    return location


def _prior_samples() -> list[EvalSample]:
    return [
        EvalSample(id=1, epoch=1, input="q1", target="a", output=ModelOutput()),
        EvalSample(
            id=2, epoch=1, input="q2", target="a", error=_error("RuntimeError('boom')")
        ),
        EvalSample(
            id=3,
            epoch=1,
            input="q3",
            target="a",
            error=_error("CancelledError('cancelled by operator')"),
        ),
        EvalSample(id=4, epoch=1, input="q4", target="a", output=ModelOutput()),
    ]


def _seed_logger(recorder: Recorder) -> TaskLoggerShim:
    logger = TaskLoggerShim(_FlushBufferDB())
    logger.recorder = recorder
    # a later `created` so the attempt's log path differs from the prior's
    logger.eval = _eval_spec().model_copy(
        update={"eval_id": "retry-attempt", "created": "2026-05-18T00:00:01+00:00"}
    )
    logger.header_only = False
    logger.flush_buffer = 10
    logger.flush_pending = []
    return logger


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("from_file", [False, True])
async def test_json_seed_yields_between_samples(
    cancel: bool, from_file: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = JSONRecorder(str(tmp_path))
    samples = [_sample().model_copy(update={"id": i}) for i in range(32)]
    prior = await _write_prior_log(recorder, samples) if from_file else samples
    spec = _eval_spec().model_copy(
        update={"eval_id": "retry-attempt", "created": "2026-05-18T00:00:01+00:00"}
    )
    location = await recorder.log_init(spec)
    first_sample = anyio.Event()
    logged = 0
    observed: list[int] = []
    log_sample = recorder.log_sample

    async def record_sample(
        eval: EvalSpec, sample: EvalSample, *, write_through: bool = False
    ) -> None:
        nonlocal logged
        await log_sample(eval, sample, write_through=write_through)
        logged += 1
        first_sample.set()

    async def sibling() -> None:
        await first_sample.wait()
        observed.append(logged)
        if cancel:
            scope.cancel()

    monkeypatch.setattr(recorder, "log_sample", record_sample)
    async with anyio.create_task_group() as group:
        group.start_soon(sibling)
        with anyio.CancelScope() as scope:
            await recorder.log_seed(spec, prior, keep=None)

    assert len(observed) == 1 and 0 < observed[0] < len(samples)
    assert scope.cancelled_caught == cancel
    assert (0 < logged < len(samples)) if cancel else logged == len(samples)
    assert not Path(location).exists()
    await recorder.log_discard(spec)
    assert not recorder.data
    if from_file:
        assert isinstance(prior, str)
        original = await read_eval_log_async(prior)
        assert original.samples is not None and len(original.samples) == len(samples)


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
@pytest.mark.parametrize("prior_format", ["eval", "json", "memory"])
@pytest.mark.parametrize("epochs", [None, 1])
async def test_dynamic_seed_filters_epochs_without_sample_ids(
    recorder_type: type[EvalRecorder] | type[JSONRecorder],
    prior_format: str,
    epochs: int | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zipfile import ZIP_STORED

    import inspect_ai.log._recorders.eval as eval_module

    monkeypatch.setattr(
        eval_module, "zipfile_compress_kwargs", {"compression": ZIP_STORED}
    )
    monkeypatch.setattr(eval_module, "COMPACT_DEAD_BYTES_FRACTION", 2.0)
    samples = [
        _prior_samples()[0],
        _prior_samples()[0].model_copy(
            update={"epoch": 2, "input": "excluded-epoch-private-payload"}
        ),
    ]
    prior = (
        samples
        if prior_format == "memory"
        else await _write_prior_log(
            (EvalRecorder if prior_format == "eval" else JSONRecorder)(
                str(tmp_path / "prior")
            ),
            samples,
        )
    )
    recorder = recorder_type(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger.eval.config.epochs = epochs
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep=None)
    await logger.log_start(EvalPlan())
    for finish in (False, True):
        if finish:
            logger.note_reused_sample(samples[0])
            await logger.log_finish("success", EvalStats(), prune_unplanned=True)
        assert (
            b"excluded-epoch-private-payload" not in Path(logger.location).read_bytes()
        )
        log = await read_eval_log_async(logger.location)
        assert {(s.id, s.epoch) for s in log.samples or []} == {(1, 1)}
        assert {
            (s.id, s.epoch)
            for s in await read_eval_log_sample_summaries_async(logger.location)
        } == {(1, 1)}


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
@pytest.mark.parametrize("prior_format", ["eval", "json", "memory"])
async def test_dynamic_seed_adds_only_admitted_samples(
    recorder_type: type[EvalRecorder] | type[JSONRecorder],
    prior_format: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples = _prior_samples()
    if prior_format == "json":
        samples[1] = samples[1].model_copy(update={"id": "002"})
    prior = (
        samples
        if prior_format == "memory"
        else await _write_prior_log(
            (EvalRecorder if prior_format == "eval" else JSONRecorder)(
                str(tmp_path / "prior")
            ),
            samples,
        )
    )
    recorder = recorder_type(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep={(1, 1)})
    await logger.log_start(EvalPlan())
    logger.note_reused_sample(samples[0])
    log_sample = recorder.log_sample

    async def check_pending_during_copy(
        eval: EvalSpec, sample: EvalSample, *, write_through: bool = False
    ) -> None:
        await log_sample(eval, sample, write_through=write_through)
        assert {s.id for s in await logger.sample_summaries() or []} == {1}
        assert await logger.read_sample(sample.id, sample.epoch) is None
        assert await logger.read_sample(2, sample.epoch) is None

    monkeypatch.setattr(recorder, "log_sample", check_pending_during_copy)
    await logger.seed_added_samples(prior, keep={(2, 1)})
    assert {s.id for s in await logger.sample_summaries() or []} == {1}
    admitted = await logger.read_prior_sample(2, 1)
    assert admitted is not None and admitted.error == samples[1].error
    assert await logger.read_sample(admitted.id, 1) is None
    assert await logger.read_prior_sample(3, 1) is None
    await logger.log_finish("error", EvalStats(), error=_error("interrupted retry"))
    log = await read_eval_log_async(logger.location)
    assert {(s.id, s.epoch) for s in log.samples or []} == {
        (1, 1),
        (samples[1].id, 1),
    }


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
async def test_dynamic_seed_alias_does_not_overwrite_current_attempt(
    recorder_type: type[EvalRecorder] | type[JSONRecorder], tmp_path: Path
) -> None:
    prior_sample = _prior_samples()[1].model_copy(update={"id": "002"})
    prior = await _write_prior_log(
        JSONRecorder(str(tmp_path / "prior")), [prior_sample]
    )
    recorder = recorder_type(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep={("002", 1)})
    await logger.log_start(EvalPlan())
    fresh = EvalSample(id="002", epoch=1, input="fresh rerun", target="a")
    await logger.complete_sample(fresh, flush=False)
    await logger.seed_added_samples(prior, keep={(2, 1)})
    assert not logger._seeded_pending
    assert await logger.read_prior_sample(2, 1) == fresh
    assert await logger.read_sample("002", 1) == fresh
    await logger.log_finish("success", EvalStats(), prune_unplanned=True)
    final = await read_eval_log_async(logger.location)
    assert final.samples == [fresh]


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
@pytest.mark.parametrize("prior_type", [EvalRecorder, JSONRecorder])
@pytest.mark.parametrize("discard", [False, True])
async def test_dynamic_seed_reads_prior_once_per_attempt(
    recorder_type: type[EvalRecorder] | type[JSONRecorder],
    prior_type: type[EvalRecorder] | type[JSONRecorder],
    discard: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect_ai.log._file as log_file
    from inspect_ai._util.async_zip import AsyncZipReader

    samples = [_prior_samples()[0].model_copy(update={"id": i}) for i in range(13)]
    prior = await _write_prior_log(prior_type(str(tmp_path / "prior")), samples)
    recorder = recorder_type(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    full_reads: list[str] = []
    member_reads: list[tuple[AsyncZipReader, str]] = []
    read_log = log_file.read_eval_log_async
    read_member = AsyncZipReader.read_member_fully

    async def count_log(location: str) -> EvalLog:
        if location == prior:
            full_reads.append(location)
        return await read_log(location)

    async def count_member(reader: AsyncZipReader, name: str) -> bytes:
        if reader._filename == prior:
            member_reads.append((reader, name))
        return await read_member(reader, name)

    monkeypatch.setattr(log_file, "read_eval_log_async", count_log)
    monkeypatch.setattr(AsyncZipReader, "read_member_fully", count_member)
    await logger.seed_from_prior(prior, keep=set())
    await logger.log_start(EvalPlan())
    for id in range(12):
        await logger.seed_added_samples(prior, keep={(id, 1)})
        sample = await logger.read_prior_sample(id, 1)
        assert sample is not None and sample.id == id
        logger.note_reused_sample(sample)
    # Repeated admissions must not overwrite this attempt's records or read
    # bodies again; the unselected thirteenth body must never be loaded.
    await logger.seed_added_samples(prior, keep={(0, 1)})
    if prior_type is JSONRecorder:
        assert full_reads == [prior]
        assert not member_reads
    else:
        assert not full_reads
        assert len({reader for reader, _ in member_reads}) == 1
        assert sum(name == "summaries.json" for _, name in member_reads) == 1
        assert [name for _, name in member_reads if name.startswith("samples/")] == [
            f"samples/{id}_epoch_1.json" for id in range(12)
        ]
    assert await logger.read_prior_sample(12, 1) is None
    source = await recorder.seed_source(logger.eval, prior)
    closed: list[bool] = []
    close = source._fs.close

    async def close_source() -> None:
        await anyio.lowlevel.checkpoint()
        await close()
        closed.append(True)

    monkeypatch.setattr(source._fs, "close", close_source)
    if discard:
        await recorder.log_discard(logger.eval)
    else:
        await logger.log_finish("success", EvalStats(), prune_unplanned=True)
        final = await read_log(logger.location)
        assert {s.id for s in final.samples or []} == set(range(12))
    assert closed == [True]
    assert not recorder._seed_sources
    assert not source.keys and not source._samples and source._reader is None


@pytest.mark.parametrize("cancel", [False, True])
async def test_seed_source_initial_read_failure_closes_filesystem(
    cancel: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai._util.asyncfiles import AsyncFilesystem
    from inspect_ai.log._recorders.recorder import SeedSamples

    recorder = JSONRecorder(str(tmp_path))
    spec = _eval_spec()
    await recorder.log_init(spec)
    loading = anyio.Event()
    closed: list[AsyncFilesystem] = []
    close = AsyncFilesystem.close

    async def fail_load(source: SeedSamples, prior: str) -> None:
        loading.set()
        if cancel:
            await anyio.sleep_forever()
        raise OSError("prior read failed")

    async def close_source(fs: AsyncFilesystem) -> None:
        await anyio.lowlevel.checkpoint()
        await close(fs)
        closed.append(fs)

    async def cancel_loading() -> None:
        await loading.wait()
        scope.cancel()

    monkeypatch.setattr(SeedSamples, "load", fail_load)
    monkeypatch.setattr(AsyncFilesystem, "close", close_source)
    async with anyio.create_task_group() as group:
        with anyio.CancelScope() as scope:
            if cancel:
                group.start_soon(cancel_loading)
                await recorder.seed_source(spec, "prior.eval")
            else:
                with pytest.raises(OSError, match="prior read failed"):
                    await recorder.seed_source(spec, "prior.eval")
    assert scope.cancelled_caught == cancel
    assert len(closed) == 1
    assert not recorder._seed_sources
    await recorder.log_discard(spec)


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
@pytest.mark.parametrize("planned", [None, {(1, 1), ("001", 1)}, {(1, 1), ("01", 1)}])
@pytest.mark.parametrize("finish_second", [False, True])
async def test_json_seed_preserves_history_for_shared_normalized_ids(
    recorder_type: type[EvalRecorder] | type[JSONRecorder],
    planned: set[tuple[str | int, int]] | None,
    finish_second: bool,
    tmp_path: Path,
) -> None:
    from inspect_ai._eval.task.run import _seed_error_retries

    prior_sample = _prior_samples()[1].model_copy(update={"id": "001"})
    prior = await _write_prior_log(
        JSONRecorder(str(tmp_path / "prior")), [prior_sample]
    )
    recorder = recorder_type(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep=planned)
    await logger.log_start(EvalPlan())
    first = await logger.read_prior_sample(1, 1)
    assert first is not None
    await logger.complete_sample(
        EvalSample(
            id=1,
            epoch=1,
            input="first",
            target="a",
            error_retries=_seed_error_retries(first),
        ),
        flush=False,
    )
    await recorder.flush(logger.eval)
    second_id = "01" if planned is not None and ("01", 1) in planned else "001"
    second = await logger.read_prior_sample(second_id, 1)
    assert second is not None and second.error == prior_sample.error
    history = _seed_error_retries(second)
    assert len(history) == 1
    assert await logger.read_sample(second_id, 1) is None
    snapshot = await read_eval_log_async(logger.location)
    assert {s.id for s in snapshot.samples or []} == {1, "001"}
    if finish_second:
        await logger.complete_sample(
            EvalSample(
                id=second_id, epoch=1, input="second", target="a", error_retries=history
            ),
            flush=False,
        )
    await logger.log_finish(
        "success" if finish_second else "cancelled",
        EvalStats(),
        prune_unplanned=finish_second,
    )
    final = await read_eval_log_async(logger.location)
    assert final.samples is not None
    by_id = {s.id: s for s in final.samples}
    assert set(by_id) == {1, second_id if finish_second else "001"}
    assert len(by_id[1].error_retries or []) == 1
    if finish_second:
        assert by_id[second_id].error_retries == history
    else:
        assert by_id["001"].error == prior_sample.error


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
async def test_dynamic_seed_restores_shared_alias_on_later_admission(
    recorder_type: type[EvalRecorder] | type[JSONRecorder], tmp_path: Path
) -> None:
    prior_sample = _prior_samples()[1].model_copy(update={"id": "001"})
    prior = await _write_prior_log(
        JSONRecorder(str(tmp_path / "prior")), [prior_sample]
    )
    recorder = recorder_type(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep={(1, 1)})
    await logger.log_start(EvalPlan())
    await logger.complete_sample(
        EvalSample(id=1, epoch=1, input="first", target="a"), flush=False
    )
    await logger.seed_added_samples(prior, keep={("001", 1)})
    second = await logger.read_prior_sample("001", 1)
    assert second is not None and second.error == prior_sample.error
    await logger.log_finish("cancelled", EvalStats())
    final = await read_eval_log_async(logger.location)
    assert {s.id for s in final.samples or []} == {1, "001"}


async def test_dynamic_admission_cannot_race_shared_seed_pruning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_sample = _prior_samples()[1].model_copy(update={"id": "001"})
    prior = await _write_prior_log(
        JSONRecorder(str(tmp_path / "prior")), [prior_sample]
    )
    recorder = JSONRecorder(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep={(1, 1)})
    await logger.log_start(EvalPlan())
    pruning = anyio.Event()
    admission_started = anyio.Event()
    prune = recorder.log_prune

    async def pause_prune(eval: EvalSpec, keys: set[SampleRecordKey]) -> None:
        pruning.set()
        await admission_started.wait()
        await prune(eval, keys)

    async def complete() -> None:
        await logger.complete_sample(
            EvalSample(id=1, epoch=1, input="first", target="a"), flush=False
        )

    async def admit() -> None:
        await pruning.wait()
        admission_started.set()
        await logger.seed_added_samples(prior, keep={("001", 1)})

    monkeypatch.setattr(recorder, "log_prune", pause_prune)
    async with anyio.create_task_group() as group:
        group.start_soon(complete)
        group.start_soon(admit)
    second = await logger.read_prior_sample("001", 1)
    assert second is not None and second.error == prior_sample.error
    assert await logger.read_sample("001", 1) is None
    await logger.log_finish("cancelled", EvalStats())
    final = await read_eval_log_async(logger.location)
    assert {s.id for s in final.samples or []} == {1, "001"}


@pytest.mark.parametrize("initial_live", [False, True])
@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
async def test_dynamic_seed_keeps_json_source_lookup(
    initial_live: bool,
    recorder_type: type[EvalRecorder] | type[JSONRecorder],
    tmp_path: Path,
) -> None:
    samples = [
        _prior_samples()[0].model_copy(update={"id": "001", "input": "first"}),
        _prior_samples()[0].model_copy(update={"id": "01", "input": "second"}),
    ]
    # A different prior ID leaves both requested IDs absent, so a live result
    # must not become a normalized prior match for the later sample.
    if initial_live:
        samples = [_prior_samples()[0].model_copy(update={"id": 9})]
    prior = await _write_prior_log(JSONRecorder(str(tmp_path / "prior")), samples)
    recorder = recorder_type(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep={("01", 1)})
    await logger.log_start(EvalPlan())
    if initial_live:
        await logger.complete_sample(
            EvalSample(id="01", epoch=1, input="live", target="a"), flush=False
        )
    else:
        logger.note_reused_sample(samples[1])
    await logger.seed_added_samples(prior, keep={("0001", 1)})
    actual = await logger.read_prior_sample("0001", 1)
    if initial_live:
        assert actual is None
    else:
        assert actual is not None and actual.id == "001" and actual.input == "first"
    await logger.log_finish("error", EvalStats(), error=_error("done"))


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("prior_format", ["eval", "json", "memory"])
async def test_dynamic_seed_admission_failure_releases_recorder(
    cancel: bool, prior_format: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior = (
        _prior_samples()
        if prior_format == "memory"
        else await _write_prior_log(
            (EvalRecorder if prior_format == "eval" else JSONRecorder)(
                str(tmp_path / "prior")
            ),
            _prior_samples(),
        )
    )
    recorder = EvalRecorder(str(tmp_path))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep={(1, 1)})
    await logger.log_start(EvalPlan())
    log_sample = recorder.log_sample

    async def interrupt_copy(
        eval: EvalSpec, sample: EvalSample, *, write_through: bool = False
    ) -> None:
        await log_sample(eval, sample, write_through=write_through)
        if cancel:
            scope.cancel()
            await anyio.lowlevel.checkpoint()
        raise RuntimeError("admission copy failed")

    monkeypatch.setattr(recorder, "log_sample", interrupt_copy)
    with anyio.CancelScope() as scope:
        if cancel:
            await logger.seed_added_samples(prior, keep={(2, 1), (3, 1)})
        else:
            with pytest.raises(RuntimeError, match="admission copy failed"):
                await logger.seed_added_samples(prior, keep={(2, 1), (3, 1)})
    assert scope.cancelled_caught == cancel
    assert await logger.read_sample(2, 1) is None
    await logger.log_finish("error", EvalStats(), error=_error("admission interrupted"))
    assert not recorder.data
    assert not recorder._seed_sources
    final = await read_eval_log_async(logger.location)
    assert {s.id for s in final.samples or []} == {1, 2}


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
async def test_memory_seed_does_not_normalize_padded_ids(
    recorder_type: type[EvalRecorder] | type[JSONRecorder], tmp_path: Path
) -> None:
    recorder = recorder_type(str(tmp_path))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    prior = [_prior_samples()[0].model_copy(update={"id": "001"})]
    await logger.seed_from_prior(prior, keep={(1, 1)})
    assert await recorder.sample_summaries(logger.eval) == []
    assert await logger.read_prior_sample(1, 1) is None
    await recorder.log_discard(logger.eval)


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
@pytest.mark.parametrize("keep", [None, {(1, 1)}])
@pytest.mark.parametrize("errored", [False, True])
async def test_json_seed_preserves_normalized_prior_lookup(
    recorder_type: type[EvalRecorder] | type[JSONRecorder],
    keep: set[tuple[str | int, int]] | None,
    errored: bool,
    tmp_path: Path,
) -> None:
    sample = _prior_samples()[1 if errored else 0].model_copy(update={"id": "001"})
    prior = await _write_prior_log(JSONRecorder(str(tmp_path / "prior")), [sample])
    expected = await read_eval_log_sample_async(prior, 1, 1)
    recorder = recorder_type(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep)

    reused = await logger.read_prior_sample(1, 1)
    assert reused is not None
    assert reused.id == expected.id == "001"
    assert reused.input == expected.input
    assert reused.error == expected.error
    assert await logger.read_prior_sample(1, 2) is None
    assert await logger.sample_summaries() == []

    history: list[EvalRetryError] = []
    if errored:
        from inspect_ai._eval.task.run import _seed_error_retries

        history = _seed_error_retries(reused)
        assert expected.error is not None
        assert history and history[-1].message == expected.error.message
        await logger.complete_sample(
            EvalSample(id=1, epoch=1, input="retry", target="a", error_retries=history),
            flush=False,
        )
    else:
        logger.note_reused_sample(reused)
    if errored and keep is None:
        assert logger._seeded_pending == {SampleRecordKey("001", 1)}
    else:
        assert not logger._seeded_pending
    await logger.log_start(EvalPlan())
    await logger.log_finish("success", EvalStats(), prune_unplanned=True)
    final = await read_eval_log_async(logger.location)
    assert final.samples is not None and len(final.samples) == 1
    assert final.samples[0].id == (1 if errored else "001")
    if errored:
        assert final.samples[0].error_retries == history


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
@pytest.mark.parametrize("keep", [None, {(1, 1)}, {("001", 1)}, {(1, 1), ("001", 1)}])
async def test_json_seed_prefers_distinct_exact_ids(
    recorder_type: type[EvalRecorder] | type[JSONRecorder],
    keep: set[tuple[str | int, int]] | None,
    tmp_path: Path,
) -> None:
    samples = [
        _prior_samples()[0].model_copy(update={"id": "001", "input": "padded"}),
        _prior_samples()[0].model_copy(update={"input": "integer"}),
    ]
    prior = await _write_prior_log(JSONRecorder(str(tmp_path / "prior")), samples)
    recorder = recorder_type(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep)
    expected_keys: set[tuple[str | int, int]] = (
        keep if keep is not None else {(1, 1), ("001", 1)}
    )
    assert {
        (s.id, s.epoch) for s in await recorder.sample_summaries(logger.eval) or []
    } == expected_keys
    for id, epoch in expected_keys:
        expected = await read_eval_log_sample_async(prior, id, epoch)
        actual = await logger.read_prior_sample(id, epoch)
        assert actual is not None and actual.input == expected.input
        logger.note_reused_sample(actual)
    await logger.log_start(EvalPlan())
    await logger.log_finish("success", EvalStats(), prune_unplanned=True)
    final = await read_eval_log_async(logger.location)
    assert final.samples is not None
    assert {(s.id, s.epoch) for s in final.samples} == expected_keys


@pytest.mark.parametrize("prior_type", [EvalRecorder, JSONRecorder])
@pytest.mark.parametrize("distinct_id", [None, 1, "001"])
async def test_json_seed_pending_guard_uses_the_readers_matched_id(
    prior_type: type[EvalRecorder] | type[JSONRecorder],
    distinct_id: str | int | None,
    tmp_path: Path,
) -> None:
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai._control.state import _full_sample

    samples = [_prior_samples()[1].model_copy(update={"id": "001"})]
    if distinct_id is not None:
        samples.append(_prior_samples()[0])
    prior = await _write_prior_log(prior_type(str(tmp_path / "prior")), samples)
    recorder = JSONRecorder(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep=None)
    await logger.log_start(EvalPlan())
    register_eval(logger.eval.eval_id, len(samples), live=logger)
    try:
        assert await _full_sample(logger.eval.eval_id, "001", 1) is None
        for id in ("001", "1", 1, "0001"):
            assert await logger.read_sample(id, 1) is None

        if distinct_id is not None:
            resolved = await logger.read_prior_sample(distinct_id, 1)
            assert resolved is not None and resolved.id == distinct_id
            logger.note_reused_sample(resolved)
            actual = await logger.read_sample(distinct_id, 1)
            assert actual is not None and actual.id == distinct_id
            pending_id = "001" if distinct_id == 1 else 1
            assert await logger.read_sample(pending_id, 1) is None
        else:
            resolved = await logger.read_prior_sample("001", 1)
            assert resolved is not None
            logger.note_reused_sample(resolved)
            actual = await _full_sample(logger.eval.eval_id, "001", 1)
            assert actual is not None and actual.id == "001"
            actual = await logger.read_sample(1, 1)
            assert actual is not None and actual.id == "001"
    finally:
        clear_all_eval_states()
        await recorder.log_discard(logger.eval)


@pytest.mark.parametrize("intervening_flush", [False, True])
async def test_normalized_seed_pruning_survives_intermediate_flushes(
    intervening_flush: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior = await _write_prior_log(
        JSONRecorder(str(tmp_path / "prior")),
        [_prior_samples()[1].model_copy(update={"id": "001"})],
    )
    recorder = EvalRecorder(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep={(1, 1)})
    await logger.log_start(EvalPlan())
    prune = recorder.log_prune

    async def flush_then_prune(eval: EvalSpec, keys: set[SampleRecordKey]) -> None:
        if intervening_flush:
            await recorder.flush(eval)
        await prune(eval, keys)

    monkeypatch.setattr(recorder, "log_prune", flush_then_prune)
    await logger.complete_sample(
        EvalSample(id=1, epoch=1, input="rerun", target="a"), flush=False
    )

    async def check_snapshot(expected_ids: set[int]) -> None:
        log = await read_eval_log_async(logger.location)
        assert log.samples is not None
        assert {s.id for s in log.samples} == expected_ids
        assert {
            s.id for s in await read_eval_log_sample_summaries_async(logger.location)
        } == expected_ids
        with pytest.raises(IndexError):
            await read_eval_log_sample_async(logger.location, "001", 1)

    for _ in range(2):
        await recorder.flush(logger.eval)
        await check_snapshot({1})
    await logger.complete_sample(
        EvalSample(id=2, epoch=1, input="next", target="a"), flush=False
    )
    await recorder.flush(logger.eval)
    await check_snapshot({1, 2})
    await logger.log_finish("success", EvalStats(), prune_unplanned=True)
    await check_snapshot({1, 2})


@pytest.mark.parametrize("cancel", [False, True])
async def test_pruning_all_seeds_persists_an_empty_journal(
    cancel: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = EvalRecorder(str(tmp_path))
    prior = await _write_prior_log(recorder, _prior_samples())
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep=None)
    await logger.log_start(EvalPlan())
    run_sync = anyio.to_thread.run_sync

    async def cancel_before_worker(func: Any, *args: Any, **kwargs: Any) -> Any:
        if cancel:
            scope.cancel()
            await anyio.lowlevel.checkpoint()
        return await run_sync(func, *args, **kwargs)

    with monkeypatch.context() as pruning:
        pruning.setattr(anyio.to_thread, "run_sync", cancel_before_worker)
        with anyio.CancelScope() as scope:
            await recorder.log_prune(logger.eval, set(logger._seeded_pending))
    assert scope.cancelled_caught == cancel
    for _ in range(2):
        await recorder.flush(logger.eval)
        log = await read_eval_log_async(logger.location)
        expected = {1, 2, 3, 4} if cancel else set()
        assert {s.id for s in log.samples or []} == expected
        assert {
            s.id for s in await read_eval_log_sample_summaries_async(logger.location)
        } == expected
    await recorder.log_discard(logger.eval)


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
async def test_task_logger_seed_from_prior_log(
    recorder_type: type, tmp_path: Path
) -> None:
    # same-format seed (a byte copy for .eval, a re-log for .json): the kept
    # keys are in the log before any sample runs, minus the planned key the
    # prior never held; the first destination write (log_start) already
    # carries them. Seeded records are not this attempt's resolutions until
    # the sweep accepts them (a drained attempt must not read complete on the
    # strength of a prior attempt's errored record it never re-ran)
    recorder = recorder_type(str(tmp_path))
    prior = await _write_prior_log(recorder, _prior_samples())
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)

    await logger.seed_from_prior(prior, keep={(1, 1), (2, 1), (3, 1), (5, 1)})

    assert logger.prior_seeded
    assert logger.samples_logged == 0
    assert logger.samples_completed == 0
    # the seeded records are in the log but not yet this attempt's: the live
    # listing source withholds them until the sweep resolves each one
    assert await logger.sample_summaries() == []

    clean = await logger.read_prior_sample(1, 1)
    assert clean is not None and clean.error is None and clean.input == "q1"
    errored = await logger.read_prior_sample(2, 1)
    assert errored is not None and errored.error is not None
    assert await logger.read_prior_sample(4, 1) is None
    assert await logger.read_prior_sample(5, 1) is None

    logger.note_reused_sample(clean)
    assert logger.samples_completed == 1
    assert logger.samples_logged == 1
    summaries = await logger.sample_summaries()
    assert summaries is not None and {s.id for s in summaries} == {1}

    await logger.log_start(EvalPlan())
    assert {
        s.id for s in await read_eval_log_sample_summaries_async(logger.location)
    } == {1, 2, 3}
    header = await read_eval_log_async(logger.location, header_only=True)
    assert header.eval.eval_id == "retry-attempt"


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
async def test_task_logger_seeded_records_surface_as_the_sweep_resolves_them(
    recorder_type: type, tmp_path: Path
) -> None:
    # the control channel lists an attempt's samples from sample_summaries
    # (EvalState.live). A seeded prior record must not appear there while its
    # sample is still to be re-run: listed, the prior's error would hide the
    # re-run's running row or read as this attempt's error while the sample
    # merely waits its turn. Each record surfaces only once the sweep accepts
    # it (clean) or the re-run's completion supersedes it (errored/cancelled)
    recorder = recorder_type(str(tmp_path))
    prior = await _write_prior_log(recorder, _prior_samples())
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep={(1, 1), (2, 1), (3, 1)})
    await logger.log_start(EvalPlan())

    assert await logger.sample_summaries() == []
    # withheld from the listing and from the per-sample read the requeue /
    # cancel / error-detail directives resolve state from; still served to
    # the sweep
    assert await logger.read_sample(2, 1) is None
    # the control channel supplies the id as a string, which the recorder
    # resolves to the same record: the guard must hold for that form too, or
    # a requeue/cancel resolving state through it sees the prior's error as
    # this attempt's terminal state (a duplicate re-run, a "finished" cancel)
    assert await logger.read_sample("2", 1) is None
    assert await logger.read_prior_sample(2, 1) is not None

    clean = await logger.read_prior_sample(1, 1)
    assert clean is not None
    logger.note_reused_sample(clean)
    listed = await logger.sample_summaries()
    assert listed is not None and {s.id for s in listed} == {1}
    assert await logger.read_sample(1, 1) is not None

    rerun = EvalSample(
        id=2,
        epoch=1,
        input="q2",
        target="a",
        output=ModelOutput(),
        error_retries=[
            EvalRetryError(
                message="RuntimeError('boom')", traceback="", traceback_ansi=""
            )
        ],
    )
    await logger.complete_sample(rerun, flush=False)
    listed = await logger.sample_summaries()
    assert listed is not None
    by_id = {s.id: s for s in listed}
    assert set(by_id) == {1, 2}
    # the listed record is the re-run's, not the seeded prior error
    assert by_id[2].error is None and by_id[2].retries == 1
    request_ids: tuple[str | int, ...] = (2, "2")
    for id in request_ids:
        read = await logger.read_sample(id, 1)
        assert read is not None and read.error is None
        assert read.error_retries == rerun.error_retries
    # the cancelled prior record stays withheld until its own re-run completes
    assert 3 not in by_id
    assert await logger.read_sample("3", 1) is None

    await logger.log_finish("error", EvalStats(), None, None, _error("boom"))
    # torn down: the control channel falls back to the on-disk log, where the
    # unresolved seeded record is the sample's final record
    assert await logger.sample_summaries() is None
    assert {
        s.id for s in await read_eval_log_sample_summaries_async(logger.location)
    } == {1, 2, 3}


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
@pytest.mark.parametrize(
    "status,prune_unplanned,rerun,expected_ids",
    [
        # a natural success drops the seeded records nothing resolved
        ("success", True, True, {1, 2}),
        # ... also when the attempt wrote nothing of its own (every sample
        # reused): the prune must survive compaction even though nothing has
        # rewritten the zip's on-disk central directory since it
        ("success", True, False, {1}),
        # a graceful resolution (score/error/drain) keeps them for the next pass
        ("success", False, True, {1, 2, 3, 4}),
        # a non-success log is the next attempt's seed: everything stays
        ("error", True, True, {1, 2, 3, 4}),
    ],
)
async def test_task_logger_finish_prunes_unresolved_seeded_records_on_natural_success(
    recorder_type: type,
    status: str,
    prune_unplanned: bool,
    rerun: bool,
    expected_ids: set[int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a dynamic feed seeds with no plan (keep=None), so prior records for
    # samples the feed does not produce this attempt are never consulted.
    # Sample 1 is reused and sample 2 re-run (when `rerun`); the rest are
    # never resolved. Compaction is forced (any dead byte) so the success
    # path always rewrites the zip from its live set
    import inspect_ai.log._recorders.eval as eval_module

    monkeypatch.setattr(eval_module, "COMPACT_DEAD_BYTES_FRACTION", 0.0)
    recorder = recorder_type(str(tmp_path))
    prior = await _write_prior_log(recorder, _prior_samples())
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep=None)
    await logger.log_start(EvalPlan())

    clean = await logger.read_prior_sample(1, 1)
    assert clean is not None
    logger.note_reused_sample(clean)
    if rerun:
        await logger.complete_sample(
            EvalSample(id=2, epoch=1, input="q2", target="a", output=ModelOutput()),
            flush=False,
        )

    await logger.log_finish(
        cast(Any, status),
        EvalStats(),
        None,
        None,
        _error("boom") if status == "error" else None,
        prune_unplanned=prune_unplanned,
    )

    log = await read_eval_log_async(logger.location)
    assert log.status == status
    assert log.samples is not None
    assert {s.id for s in log.samples} == expected_ids
    assert {
        s.id for s in await read_eval_log_sample_summaries_async(logger.location)
    } == expected_ids


async def test_task_logger_prune_survives_failed_compaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # compaction closes the zip and reopens the original temp file when the
    # rewrite fails; the reopened zip re-reads the on-disk central directory,
    # which a prune with nothing written behind it has not reached
    # (ZipFile.close rewrites it only after a write). The pruned members must
    # not come back: a success log with summaries [1] but bodies [1, 2, 3, 4]
    import inspect_ai.log._recorders.eval as eval_module

    monkeypatch.setattr(eval_module, "COMPACT_DEAD_BYTES_FRACTION", 0.0)

    def failing_compact(src_file: Any, live: Any) -> Any:
        raise RuntimeError("simulated compaction failure")

    recorder = EvalRecorder(str(tmp_path))
    prior = await _write_prior_log(recorder, _prior_samples())
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep=None)
    await logger.log_start(EvalPlan())
    clean = await logger.read_prior_sample(1, 1)
    assert clean is not None
    logger.note_reused_sample(clean)

    monkeypatch.setattr(eval_module, "_compact_zip", failing_compact)
    with patch.object(eval_module.logger, "warning") as warning:
        await logger.log_finish("success", EvalStats(), prune_unplanned=True)
    assert warning.call_count == 1
    assert "simulated compaction failure" in warning.call_args.args[0]

    log = await read_eval_log_async(logger.location)
    assert log.samples is not None
    assert {s.id for s in log.samples} == {1}
    assert {
        s.id for s in await read_eval_log_sample_summaries_async(logger.location)
    } == {1}


async def test_compact_reopens_the_zip_when_cancelled_before_the_worker_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # compaction closes the zip before handing the rewrite to a worker thread;
    # a cancellation landing at that await (before the worker starts) must
    # still leave the zip reopened — the cancel path's finish/discard asserts
    # on it — and with the live set intact, not the stale on-disk directory
    import inspect_ai.log._recorders.eval as eval_module

    monkeypatch.setattr(eval_module, "COMPACT_DEAD_BYTES_FRACTION", 0.0)
    recorder = EvalRecorder(str(tmp_path))
    prior = await _write_prior_log(recorder, _prior_samples())
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep=None)
    await logger.log_start(EvalPlan())
    clean = await logger.read_prior_sample(1, 1)
    assert clean is not None
    logger.note_reused_sample(clean)
    await recorder.log_prune(logger.eval, set(logger._seeded_pending))
    (zip_log,) = recorder.data.values()

    original_run_sync = anyio.to_thread.run_sync
    cancelled_once = {"done": False}

    async def cancel_at_the_await(func: Any, *args: Any, **kwargs: Any) -> Any:
        if func is eval_module._compact_zip and not cancelled_once["done"]:
            cancelled_once["done"] = True
            scope.cancel()
            await anyio.lowlevel.checkpoint()
        return await original_run_sync(func, *args, **kwargs)

    monkeypatch.setattr(anyio.to_thread, "run_sync", cancel_at_the_await)
    with anyio.CancelScope() as scope:
        await zip_log.compact()
    assert scope.cancelled_caught

    assert zip_log._zip is not None
    assert {n for n in zip_log._zip.NameToInfo if n.startswith("samples/")} == {
        "samples/1_epoch_1.json"
    }
    # the finish that follows (compacting for real this time) sees the same
    await logger.log_finish("success", EvalStats(), prune_unplanned=True)
    log = await read_eval_log_async(logger.location)
    assert log.samples is not None and {s.id for s in log.samples} == {1}


async def test_compact_cancels_between_chunks_and_preserves_original_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inspect_ai.log._recorders.eval as eval_module

    monkeypatch.setattr(eval_module, "COMPACT_DEAD_BYTES_FRACTION", 0.0)
    recorder = EvalRecorder(str(tmp_path))
    samples = _prior_samples()
    samples[0].input = "x" * (3 * 1024 * 1024)
    prior = await _write_prior_log(recorder, samples)
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep=None)
    await logger.log_start(EvalPlan())
    clean = await logger.read_prior_sample(1, 1)
    assert clean is not None
    logger.note_reused_sample(clean)
    await recorder.log_prune(logger.eval, set(logger._seeded_pending))
    (zip_log,) = recorder.data.values()
    original_file = zip_log._temp_file
    temporary_files: list[BinaryIO] = []
    chunks_read = 0
    read = ZipExtFile.read
    temporary_file = tempfile.TemporaryFile

    def track_temporary_file() -> BinaryIO:
        result = temporary_file()
        temporary_files.append(result)
        return result

    def cancel_after_first_chunk(reader: ZipExtFile, n: int = -1) -> bytes:
        nonlocal chunks_read
        chunk = read(reader, n)
        if chunk:
            chunks_read += 1
            if chunks_read == 1:
                anyio.from_thread.run_sync(scope.cancel)
        return chunk

    with monkeypatch.context() as copying:
        copying.setattr(tempfile, "TemporaryFile", track_temporary_file)
        copying.setattr(ZipExtFile, "read", cancel_after_first_chunk)
        with anyio.CancelScope() as scope:
            await zip_log.compact()

    assert scope.cancelled_caught
    assert chunks_read == 1
    assert len(temporary_files) == 1 and temporary_files[0].closed
    assert zip_log._temp_file is original_file and not original_file.closed
    assert zip_log._zip is not None
    assert {n for n in zip_log._zip.NameToInfo if n.startswith("samples/")} == {
        "samples/1_epoch_1.json"
    }
    with anyio.CancelScope(shield=True):
        await logger.log_finish("cancelled", EvalStats())
    assert original_file.closed
    assert not recorder.data
    log = await read_eval_log_async(logger.location)
    assert log.status == "cancelled"
    assert log.samples is not None and {s.id for s in log.samples} == {1}
    assert log.samples[0].input == samples[0].input
    assert {
        s.id for s in await read_eval_log_sample_summaries_async(logger.location)
    } == {1}


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
async def test_task_logger_seeded_sample_reads_resolved(
    recorder_type: type, tmp_path: Path
) -> None:
    # a seeded prior record is stored condensed (model-event inputs pooled in
    # events_data). Both reads must serve it resolved — the sweep's, whose
    # result reaches a SampleSource.sample_complete callback, and the control
    # channel's — or the callback sees ModelEvent.input == [] for a reused
    # sample whose original input carried a message
    prior_sample = EvalSample(
        id=1,
        epoch=1,
        input="q1",
        target="a",
        output=ModelOutput(),
        events=[
            ModelEvent(
                model="test",
                input=[ChatMessageUser(content="hello")],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput.from_content("test", "response"),
            )
        ],
    )
    prior_sample.timelines = [timeline_build(prior_sample.events)]
    recorder = recorder_type(str(tmp_path))
    prior = await _write_prior_log(recorder, [prior_sample])
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep={(1, 1)})
    await logger.log_start(EvalPlan())

    def input_texts(sample: EvalSample) -> list[str]:
        assert sample.events_data is None
        event = next(e for e in sample.events if isinstance(e, ModelEvent))
        return [message.text for message in event.input]

    reused = await logger.read_prior_sample(1, 1)
    assert reused is not None
    assert input_texts(reused) == ["hello"]

    logger.note_reused_sample(reused)
    served = await logger.read_sample(1, 1)
    assert served is not None
    assert input_texts(served) == ["hello"]

    excluded = await logger.read_sample(1, 1, exclude_fields={"events"})
    assert excluded is not None and excluded.events == []
    assert excluded.events_data is None and excluded.timelines is None
    included = await logger.read_sample(1, 1, exclude_fields={"events_data"})
    assert included is not None and input_texts(included) == ["hello"]
    assert included.timelines
    await logger.log_finish("success", EvalStats())


@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
async def test_task_logger_read_sample_exclude_fields_keeps_required_fields(
    recorder_type: type, tmp_path: Path
) -> None:
    # a record served from the recorder's copy honours exclude_fields by
    # resetting the fields to their defaults; a required field has none, so
    # excluding it must leave the field alone rather than plant
    # PydanticUndefined in the copy (which fails at serialization)
    recorder = recorder_type(str(tmp_path))
    prior = await _write_prior_log(
        recorder,
        [
            EvalSample(
                id=1,
                epoch=1,
                input="q1",
                target="a",
                output=ModelOutput(),
                store={"k": 1},
            )
        ],
    )
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior(prior, keep={(1, 1)})
    await logger.log_start(EvalPlan())
    seeded = await logger.read_prior_sample(1, 1)
    assert seeded is not None
    logger.note_reused_sample(seeded)

    read = await logger.read_sample(1, 1, exclude_fields={"store", "id", "input"})
    assert read is not None
    assert read.store == {}
    assert read.id == 1 and read.input == "q1"
    assert read.model_dump(mode="json")["id"] == 1


async def test_task_logger_seed_from_prior_relogs_across_formats(
    tmp_path: Path,
) -> None:
    # a .eval prior retried into a .json log cannot be byte-copied: the kept
    # samples are re-logged through the recorder instead, with the same
    # bookkeeping and the same local read-back
    prior = await _write_prior_log(
        EvalRecorder(str(tmp_path / "prior")), _prior_samples()
    )
    recorder = JSONRecorder(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)

    await logger.seed_from_prior(prior, keep={(1, 1), (2, 1)})

    assert logger.prior_seeded
    assert await logger.sample_summaries() == []
    clean = await logger.read_prior_sample(1, 1)
    assert clean is not None and clean.input == "q1"
    logger.note_reused_sample(clean)
    summaries = await logger.sample_summaries()
    assert summaries is not None and {s.id for s in summaries} == {1}
    await logger.log_start(EvalPlan())
    assert {
        s.id for s in await read_eval_log_sample_summaries_async(logger.location)
    } == {1, 2}


@pytest.mark.parametrize("prior_type", [EvalRecorder, JSONRecorder, None])
@pytest.mark.parametrize("recorder_type", [EvalRecorder, JSONRecorder])
@pytest.mark.parametrize("string_ids", [False, True])
async def test_task_logger_seed_preserves_record_id_matching(
    prior_type: type[EvalRecorder] | type[JSONRecorder] | None,
    recorder_type: type[EvalRecorder] | type[JSONRecorder],
    string_ids: bool,
    tmp_path: Path,
) -> None:
    samples = _prior_samples()
    if string_ids:
        samples = [s.model_copy(update={"id": str(s.id)}) for s in samples]
    samples[1].error_retries = [
        EvalRetryError(message="earlier error", traceback="", traceback_ansi="")
    ]
    prior = (
        await _write_prior_log(prior_type(str(tmp_path / "prior")), samples)
        if prior_type is not None
        else samples
    )
    recorder = recorder_type(str(tmp_path / "retry"))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    keep: set[tuple[str | int, int]] = (
        {(1, 1), (2, 1)} if string_ids else {("1", 1), ("2", 1)}
    )
    await logger.seed_from_prior(prior, keep=keep)
    assert logger.prior_seeded
    await logger.log_start(EvalPlan())

    for id, epoch in keep:
        seeded = await logger.read_prior_sample(id, epoch)
        assert seeded is not None
        expected = samples[int(id) - 1]
        assert seeded.id == expected.id
        assert seeded.error == expected.error
        assert seeded.error_retries == expected.error_retries
        if str(id) == "1":
            logger.note_reused_sample(seeded)
    assert await logger.read_prior_sample("3", 1) is None

    rerun = samples[1].model_copy(
        update={"id": 2 if string_ids else "2", "error": None}
    )
    await logger.complete_sample(rerun, flush=False)
    request_ids: tuple[str | int, ...] = (2, "2")
    for id in request_ids:
        read = await logger.read_sample(id, 1)
        assert read is not None and read.error is None
        assert read.error_retries == samples[1].error_retries
    summaries = await logger.sample_summaries()
    assert summaries is not None and len(summaries) == 2
    await recorder.flush(logger.eval)
    disk_summaries = await read_eval_log_sample_summaries_async(logger.location)
    assert len(disk_summaries) == 2
    assert all(s.error is None for s in disk_summaries)

    await logger.log_finish("success", EvalStats())
    finished = await read_eval_log_async(logger.location)
    assert finished.samples is not None and len(finished.samples) == 2
    for id in request_ids:
        read = await read_eval_log_sample_async(logger.location, id, 1)
        assert read.error is None
        assert read.error_retries == samples[1].error_retries


@pytest.mark.parametrize("write_through", [False, True])
async def test_task_logger_seeded_read_excludes_before_materializing(
    write_through: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inspect_ai.log._recorders.eval as eval_module

    sample = EvalSample(
        id=1,
        epoch=1,
        input="q1",
        target="a",
        store={"retained": [1, {"nested": True}]},
        attachments={"large": "excluded attachment" * 100_000},
    )
    recorder = EvalRecorder(str(tmp_path))
    prior = await _write_prior_log(recorder, [sample])
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)
    await logger.seed_from_prior([sample] if write_through else prior, keep=None)
    await logger.log_start(EvalPlan())
    logger.note_reused_sample(sample)

    original_parse = eval_module._parse_sample_data

    def parse_included_fields(data: bytes | dict[str, Any]) -> EvalSample:
        # Exclusions must precede both whole-body JSON loading and validation.
        assert isinstance(data, dict)
        assert "attachments" not in data
        assert "events" not in data and "events_data" not in data
        return original_parse(data)

    monkeypatch.setattr(eval_module, "_parse_sample_data", parse_included_fields)
    event_patch = patch(
        "inspect_ai.log._recorders.eval.ObjectBuilder.event",
        autospec=True,
    )
    original_event, _ = event_patch.get_original()
    with event_patch as build_event:
        build_event.side_effect = original_event
        read = await logger.read_sample(
            "1", 1, exclude_fields={"attachments", "events", "id", "input"}
        )
        assert read is not None and read.attachments == {}
        assert read.id == 1 and read.input == "q1"
        assert read.store == sample.store
        assert all(
            call.args[-1] != sample.attachments["large"]
            for call in build_event.call_args_list
        )
    monkeypatch.undo()
    full = await logger.read_sample("1", 1)
    assert full is not None and full.attachments == sample.attachments
    await logger.log_finish("success", EvalStats())


async def test_task_logger_seed_from_prior_in_memory_samples(tmp_path: Path) -> None:
    # an in-memory prior log (eval_retry on a loaded EvalLog) seeds by
    # re-logging its samples before the log starts
    recorder = EvalRecorder(str(tmp_path))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)

    await logger.seed_from_prior(_prior_samples(), keep=None)

    assert logger.prior_seeded
    prior = await logger.read_prior_sample(4, 1)
    assert prior is not None and prior.input == "q4"
    await logger.log_start(EvalPlan())
    assert {
        s.id for s in await read_eval_log_sample_summaries_async(logger.location)
    } == {
        1,
        2,
        3,
        4,
    }


async def test_task_logger_seed_from_prior_missing_log_runs_unseeded(
    tmp_path: Path,
) -> None:
    # a prior log that no longer exists is not a storage failure worth burning
    # the attempt (and every later retry, which would keep the same missing
    # source) on: the attempt runs unseeded, as the reuse sweep's own lookup
    # degrades for a missing log
    recorder = EvalRecorder(str(tmp_path))
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)

    with patch.object(task_log_module.logger, "warning") as warning:
        await logger.seed_from_prior(str(tmp_path / "never-written.eval"), keep=None)

    assert not logger.prior_seeded
    assert any("not found" in str(call.args[0]) for call in warning.call_args_list)
    assert not Path(logger.location).exists()
    await logger.log_start(EvalPlan())
    assert Path(logger.location).exists()


async def test_task_logger_seed_from_prior_storage_failure_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # any other read failure (after the recorder's retries) fails the attempt
    # before its first destination write, so the retry keeps the prior source
    import inspect_ai.log._recorders.eval as eval_recorder_module

    async def failing_copy(prior_log: str, dest: object) -> None:
        raise OSError("simulated storage failure")

    monkeypatch.setattr(eval_recorder_module, "_copy_prior_log", failing_copy)
    recorder = EvalRecorder(str(tmp_path))
    prior = await _write_prior_log(recorder, _prior_samples())
    logger = _seed_logger(recorder)
    logger._location = await recorder.log_init(logger.eval)

    with pytest.raises(OSError, match="simulated storage failure"):
        await logger.seed_from_prior(prior, keep=None)

    assert not logger.prior_seeded
    assert not Path(logger.location).exists()


async def test_task_logger_log_finish_stops_stale_flush_timer(tmp_path) -> None:
    recorder = EvalRecorder(str(tmp_path))
    spec = _eval_spec()
    await recorder.log_init(spec, str(tmp_path / "streaming.eval"), clean=True)
    await recorder.log_start(spec, EvalPlan())
    buffer_db = SampleBufferDatabase(str(tmp_path / "streaming.eval"), db_dir=tmp_path)
    task_logger = _flush_logger(flush_buffer=10, buffer_db=buffer_db)
    task_logger.recorder = cast(Recorder, recorder)
    task_logger.eval = spec
    task_logger.header_only = False
    # long interval so the armed timer stays pending until log_finish stops it
    task_logger._stale_flush_interval = 60

    async with _running_stale_flush_timer(task_logger, start=False):
        # a sub-threshold sample arms a stale-flush timer
        await task_logger.complete_sample(_sample(), flush=True)
        assert task_logger._stale_flush_cancel_scope is not None

        await task_logger.log_finish("success", EvalStats(), EvalResults())

        # log_finish must stop the timer itself, not the CM's finally
        assert task_logger._stale_flush_cancel_scope is None

    assert task_logger._buffer_db is None


class TestResolvePackageRevision:
    def test_returns_none_for_none_distribution(self):
        assert resolve_package_revision(None) is None

    def test_returns_none_when_not_a_vcs_install(self):
        dist = _fake_dist("external-package")
        direct_url = DirectUrl(url="https://example.com/external_package-1.0.0.tar.gz")
        with patch(
            "inspect_ai._eval.task.log.get_distribution_direct_url",
            return_value=direct_url,
        ):
            assert resolve_package_revision(dist) is None

    def test_returns_revision_for_git_install(self):
        dist = _fake_dist("harder-tasks-judge-run", "0.1.0")
        direct_url = DirectUrl(
            url="https://github.com/METR/harder-tasks",
            vcs_info=VcsInfo(
                vcs="git", commit_id="523c14f000000000000000000000000000000000"
            ),
        )
        with patch(
            "inspect_ai._eval.task.log.get_distribution_direct_url",
            return_value=direct_url,
        ):
            assert resolve_package_revision(dist) == EvalRevision(
                type="git",
                origin="https://github.com/METR/harder-tasks",
                commit="523c14f000000000000000000000000000000000",
            )

    def test_strips_git_plus_prefix_from_origin(self):
        dist = _fake_dist("harder-tasks-judge-run", "0.1.0")
        direct_url = DirectUrl(
            url="git+https://github.com/METR/harder-tasks",
            vcs_info=VcsInfo(
                vcs="git", commit_id="523c14f000000000000000000000000000000000"
            ),
        )
        with patch(
            "inspect_ai._eval.task.log.get_distribution_direct_url",
            return_value=direct_url,
        ):
            result = resolve_package_revision(dist)
        assert result is not None
        assert result.origin == "https://github.com/METR/harder-tasks"

    def test_redacts_credentials_in_origin(self):
        # a private package installed from an authenticated git URL records the
        # credentialed URL in direct_url.json; it must not leak into the log
        dist = _fake_dist("harder-tasks-judge-run", "0.1.0")
        direct_url = DirectUrl(
            url="git+https://x-access-token:ghs_secret@github.com/METR/harder-tasks",
            vcs_info=VcsInfo(
                vcs="git", commit_id="523c14f000000000000000000000000000000000"
            ),
        )
        with patch(
            "inspect_ai._eval.task.log.get_distribution_direct_url",
            return_value=direct_url,
        ):
            result = resolve_package_revision(dist)
        assert result is not None
        assert result.origin == "https://github.com/METR/harder-tasks"
        assert "ghs_secret" not in result.origin


def test_package_and_revision_logged_for_git_install():
    task = Task()
    dist = _fake_dist("harder-tasks-judge-run", "0.1.0")
    direct_url = DirectUrl(
        url="https://github.com/METR/harder-tasks",
        vcs_info=VcsInfo(
            vcs="git", commit_id="523c14f000000000000000000000000000000000"
        ),
    )
    with (
        patch("inspect_ai._eval.task.log.resolve_task_distribution", return_value=dist),
        patch(
            "inspect_ai._eval.task.log.get_distribution_direct_url",
            return_value=direct_url,
        ),
    ):
        [log] = eval(task, model="mockllm/model")

    assert log.eval.packages["harder-tasks-judge-run"] == "0.1.0"
    assert log.eval.revision is not None
    assert log.eval.revision.origin == "https://github.com/METR/harder-tasks"
    assert log.eval.revision.commit == "523c14f000000000000000000000000000000000"


def test_package_revision_preferred_over_cwd_git_context():
    task = Task()
    dist = _fake_dist("harder-tasks-judge-run", "0.1.0")
    direct_url = DirectUrl(
        url="https://github.com/METR/harder-tasks",
        vcs_info=VcsInfo(
            vcs="git", commit_id="523c14f000000000000000000000000000000000"
        ),
    )
    with (
        patch("inspect_ai._eval.task.log.resolve_task_distribution", return_value=dist),
        patch(
            "inspect_ai._eval.task.log.get_distribution_direct_url",
            return_value=direct_url,
        ),
        patch(
            "inspect_ai._eval.task.log.git_context",
            return_value=GitContext(
                origin="https://github.com/some/cwd-repo",
                commit="cwd0cwd0cwd0cwd0cwd0cwd0cwd0cwd0cwd0cwd0",
                dirty=False,
            ),
        ),
    ):
        [log] = eval(task, model="mockllm/model")

    assert log.eval.revision is not None
    assert log.eval.revision.origin == "https://github.com/METR/harder-tasks"
    assert log.eval.revision.commit == "523c14f000000000000000000000000000000000"


def test_revision_none_when_task_not_from_package():
    task = Task()
    with patch(
        "inspect_ai._eval.task.log.resolve_task_distribution", return_value=None
    ):
        [log] = eval(task, model="mockllm/model")

    assert log.eval.revision is None


def test_falls_back_to_cwd_git_context_when_no_package_revision():
    task = Task()
    with (
        patch("inspect_ai._eval.task.log.resolve_task_distribution", return_value=None),
        patch(
            "inspect_ai._eval.task.log.git_context",
            return_value=GitContext(
                origin="https://github.com/some/cwd-repo",
                commit="cwd0cwd0cwd0cwd0cwd0cwd0cwd0cwd0cwd0cwd0",
                dirty=True,
            ),
        ),
    ):
        [log] = eval(task, model="mockllm/model")

    assert log.eval.revision is not None
    assert log.eval.revision.origin == "https://github.com/some/cwd-repo"
    assert log.eval.revision.dirty is True


# ---------------------------------------------------------------------------
# log_discard: an abandoned retry attempt's never-finished log
# (design/ctl/task-drain.md "Tasks between attempts")
# ---------------------------------------------------------------------------


async def test_eval_recorder_log_discard_removes_flushed_destination(
    tmp_path: Path,
) -> None:
    # a zero-seed retry attempt has no destination hold, so log_start flushes
    # a `started` header — discarding the abandoned attempt must remove it,
    # or the end-of-run retry-cleanup sweep would prefer it (by mtime) over
    # the errored prior attempt's log and delete the wrong file
    spec = _eval_spec()
    recorder = EvalRecorder(str(tmp_path))
    location = await recorder.log_init(spec)
    await recorder.log_start(spec, EvalPlan())
    await recorder.flush(spec)
    assert Path(location).exists()

    await recorder.log_discard(spec)
    assert not Path(location).exists()
    assert recorder.data == {}
    # a repeat discard is a no-op
    await recorder.log_discard(spec)


async def test_eval_recorder_log_discard_without_flush_drops_tracking_only(
    tmp_path: Path,
) -> None:
    # the common abandon paths (dispatch-pick drop, held retry attempts)
    # never wrote the destination: discard just drops the in-memory entry
    spec = _eval_spec()
    recorder = EvalRecorder(str(tmp_path))
    location = await recorder.log_init(spec)
    await recorder.log_start(spec, EvalPlan())

    await recorder.log_discard(spec)
    assert not Path(location).exists()
    assert recorder.data == {}


async def test_eval_recorder_log_discard_preserves_seeded_destination(
    tmp_path: Path,
) -> None:
    # a log re-initialized from an existing file (re-logging into an existing
    # log) doesn't own the destination — discard must leave it in place even
    # after a flush
    spec = _eval_spec()
    recorder = EvalRecorder(str(tmp_path))
    location = await recorder.log_init(spec)
    await recorder.log_start(spec, EvalPlan())
    await recorder.log_finish(spec, "success", EvalStats(), None, None)
    assert Path(location).exists()

    await recorder.log_init(spec, location)
    await recorder.flush(spec)
    await recorder.log_discard(spec)
    assert Path(location).exists()


async def test_json_recorder_log_discard_removes_flushed_destination(
    tmp_path: Path,
) -> None:
    spec = _eval_spec()
    recorder = JSONRecorder(str(tmp_path))
    location = await recorder.log_init(spec)
    await recorder.log_start(spec, EvalPlan())
    await recorder.flush(spec)
    assert Path(location).exists()

    await recorder.log_discard(spec)
    assert not Path(location).exists()
    assert recorder.data == {}


async def test_json_recorder_log_discard_without_flush_drops_tracking_only(
    tmp_path: Path,
) -> None:
    spec = _eval_spec()
    recorder = JSONRecorder(str(tmp_path))
    location = await recorder.log_init(spec)

    await recorder.log_discard(spec)
    assert not Path(location).exists()
    assert recorder.data == {}


async def test_task_logger_discard_drops_recorder_entry_and_flushed_file(
    tmp_path: Path,
) -> None:
    # TaskLogger.discard composes cleanup (buffer db + flush timer) with the
    # recorder-level log_discard — the abandoned-retry finalize in _eval/run.py
    spec = _eval_spec()
    recorder = EvalRecorder(str(tmp_path))
    logger = TaskLoggerShim(_FlushBufferDB())
    logger.recorder = cast(Recorder, recorder)
    logger.eval = spec
    location = await recorder.log_init(spec)
    await logger.log_start(EvalPlan())
    assert Path(location).exists()

    await logger.discard()
    assert not Path(location).exists()
    assert recorder.data == {}


async def test_task_logger_discard_contains_recorder_failures() -> None:
    # discard's callers run inside the dispatcher task group: a storage error
    # from the destination removal must be logged, not raised — an escaping
    # exception would cancel every in-flight task in the run
    class _FailingDiscardRecorder:
        async def log_discard(
            self, eval: EvalSpec, *, keep_destination: bool = False
        ) -> None:
            raise OSError("simulated transient storage failure")

    logger = TaskLoggerShim(_FlushBufferDB())
    logger.recorder = cast(Recorder, _FailingDiscardRecorder())
    logger.eval = _eval_spec()
    logger._location = "test.eval"

    # assert on the module logger directly rather than via caplog: an eval
    # run in an earlier test reconfigures inspect's logging, which stops
    # records propagating to caplog's root-level handler
    with patch.object(task_log_module.logger, "warning") as warning:
        await logger.discard()

    assert any(
        "Error discarding abandoned log entry" in str(call.args[0])
        for call in warning.call_args_list
    )


async def test_task_logger_discard_drops_recorder_entry_when_cleanup_fails(
    tmp_path: Path,
) -> None:
    # a failing buffer-db removal in cleanup must not skip the recorder drop:
    # the in-memory entry (open temp file included) is the leak discard exists
    # to close, so each step is contained on its own
    class _FailingCleanupBufferDB(_FlushBufferDB):
        def cleanup(self) -> None:
            raise OSError("simulated buffer db removal failure")

    spec = _eval_spec()
    recorder = EvalRecorder(str(tmp_path))
    logger = TaskLoggerShim(_FailingCleanupBufferDB())
    logger.recorder = cast(Recorder, recorder)
    logger.eval = spec
    location = await recorder.log_init(spec)
    logger._location = location
    await logger.log_start(EvalPlan())
    assert Path(location).exists()

    with patch.object(task_log_module.logger, "warning") as warning:
        await logger.discard()

    assert not Path(location).exists()
    assert recorder.data == {}
    assert any(
        "Error cleaning up abandoned log entry" in str(call.args[0])
        for call in warning.call_args_list
    )


@pytest.mark.anyio
@pytest.mark.parametrize("recorder_cls", [EvalRecorder, JSONRecorder])
async def test_recorder_destination_written_tracks_in_progress_log_only(
    recorder_cls: type[EvalRecorder] | type[JSONRecorder], tmp_path: Path
) -> None:
    """Recorders answer destination_written only for a log they are tracking.

    False after init (nothing flushed), True once a flush lands, and an
    error for an eval they don't know about — before init or after finish
    (the finished case is TaskLogger's to answer, see the test below).
    """
    recorder = recorder_cls(str(tmp_path))
    spec = _eval_spec()

    with pytest.raises(RuntimeError, match="No log in progress"):
        recorder.destination_written(spec)

    await recorder.log_init(spec)
    assert recorder.destination_written(spec) is False

    await recorder.log_start(spec, EvalPlan())
    await recorder.flush(spec)
    assert recorder.destination_written(spec) is True

    await recorder.log_finish(spec, "error", EvalStats(), None, None)
    with pytest.raises(RuntimeError, match="No log in progress"):
        recorder.destination_written(spec)


class _DestinationRecorder(_FlushRecorder):
    def __init__(self, written: bool) -> None:
        super().__init__()
        self.written = written
        self.asked = 0

    def destination_written(self, eval_spec: EvalSpec) -> bool:
        self.asked += 1
        return self.written


@pytest.mark.anyio
async def test_task_logger_destination_written_finished_without_recorder() -> None:
    """A finished log is written by definition; the recorder is not consulted.

    The recorder stops tracking the eval when log_finish pops it, so asking
    it would raise. Before finish the recorder's answer is passed through.
    """
    recorder = _DestinationRecorder(written=False)
    logger = _flush_logger(recorder=recorder)

    assert logger.destination_written is False
    assert recorder.asked == 1

    logger._finished = True
    assert logger.destination_written is True
    assert recorder.asked == 1
