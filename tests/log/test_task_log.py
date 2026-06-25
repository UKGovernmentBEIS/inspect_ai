from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast
from unittest.mock import patch

import anyio
import pytest
from test_helpers.task_logger import TaskLoggerShim

from inspect_ai import Task, eval
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.run import eval_run
from inspect_ai._eval.task import log as task_log_module
from inspect_ai._eval.task.log import (
    TaskLogger,
    resolve_external_registry_package_version,
)
from inspect_ai._util.background import background_task_group, set_background_task_group
from inspect_ai._util.constants import PKG_NAME
from inspect_ai.dataset import Sample
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSampleSummary,
    EvalSpec,
    EvalStats,
)
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.eval import EvalRecorder
from inspect_ai.log._recorders.recorder import Recorder
from inspect_ai.model import get_model


def test_external_package_version_logged():
    task = Task()

    # Imaginary package `eval_registry` v1.0.0
    with (
        patch.object(
            type(task),
            "registry_name",
            property(lambda self: "eval_registry/my_task"),
        ),
        patch(
            "inspect_ai._eval.task.log.importlib_metadata.version",
            return_value="1.0.0",
        ),
    ):
        [log] = eval(task, model="mockllm/model")

    assert "eval_registry" in log.eval.packages
    assert log.eval.packages["eval_registry"] == "1.0.0"


class TestResolveExternalRegistryPackageVersion:
    def test_returns_none_when_task_registry_name_is_none(self):
        assert resolve_external_registry_package_version(None) is None

    def test_returns_none_when_registry_package_name_returns_none(self):
        with patch(
            "inspect_ai._eval.task.log.registry_package_name", return_value=None
        ):
            result = resolve_external_registry_package_version("some_task")

        assert result is None

    def test_returns_none_when_package_is_internal(self):
        # i.e. if the task happened to live in `inspect_ai`
        with patch(
            "inspect_ai._eval.task.log.registry_package_name", return_value=PKG_NAME
        ):
            result = resolve_external_registry_package_version("inspect_ai/some_task")

        assert result is None

    def test_returns_package_name_and_version_for_external_package(self):
        with (
            patch(
                "inspect_ai._eval.task.log.registry_package_name",
                return_value="external_package",
            ),
            patch(
                "inspect_ai._eval.task.log.importlib_metadata.version",
                return_value="1.2.3",
            ),
        ):
            result = resolve_external_registry_package_version(
                "external_package/some_task"
            )

        assert result is not None
        assert result == ("external_package", "1.2.3")

    def test_returns_none_when_package_not_found(self):
        from importlib import metadata as importlib_metadata

        with (
            patch(
                "inspect_ai._eval.task.log.registry_package_name",
                return_value="nonexistent_package",
            ),
            patch(
                "inspect_ai._eval.task.log.importlib_metadata.version",
                side_effect=importlib_metadata.PackageNotFoundError(
                    "nonexistent_package"
                ),
            ),
        ):
            result = resolve_external_registry_package_version(
                "nonexistent_package/some_task"
            )

        assert result is None


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

    async def flush(self, eval_spec: EvalSpec) -> None:
        self.flush_count += 1
        self.flush_started.set()
        await self.allow_flush.wait()
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("flush failed")

    async def log_sample(self, eval_spec: EvalSpec, sample: EvalSample) -> None:
        pass


class _FlushBufferDB:
    def __init__(self) -> None:
        self.removed: list[tuple[str | int, int]] = []
        self.removed_samples = anyio.Event()

    def complete_sample(self, summary: EvalSampleSummary) -> None:
        pass

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
    assert logger.eval.eval_id != original_eval_id
    assert logger.samples_completed == 1
    assert logger.flush_pending == []


@pytest.mark.anyio
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
