"""End-to-end tests for the recovery API."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import anyio
import pytest
from pydantic_core import to_jsonable_python
from test_helpers.buffer import simulate_crashed_buffer_db

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._file import read_eval_log_async
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalPlan,
    EvalSample,
    EvalSampleSummary,
    EvalSpec,
)
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.eval import HEADER_JSON, LogStart
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._recover import (
    RecoveryNotAvailable,
    RecoveryThresholdExceeded,
    recover_eval_log_async,
    recoverable_eval_logs,
)
from inspect_ai.log._recover._api import _recoverable_eval_logs_async
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer._metric import Score


def _make_eval_spec(
    task: str = "test_task",
    samples: int = 4,
    sample_ids: list[int] | None = None,
) -> EvalSpec:
    return EvalSpec(
        created=datetime.now(timezone.utc).isoformat(),
        task=task,
        model="mockllm/model",
        dataset=EvalDataset(name="test", samples=samples, sample_ids=sample_ids),
        config=EvalConfig(),
    )


def _make_sample(id: int, epoch: int = 1) -> EvalSample:
    return EvalSample(
        id=id,
        epoch=epoch,
        input=f"input {id}",
        target=f"target {id}",
        output=ModelOutput.from_content(model="mockllm/model", content=f"output {id}"),
        messages=[],
        scores={"accuracy": Score(value="C", answer="C")},
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
    )


def _to_json(obj: object) -> str:
    return json.dumps(to_jsonable_python(obj, exclude_none=True))


def _make_model_event(content: str) -> ModelEvent:
    return ModelEvent(
        model="mockllm/model",
        input=[ChatMessageUser(content="test input")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content(model="mockllm/model", content=content),
    )


def _write_crashed_eval(
    path: str,
    samples: list[EvalSample] | None = None,
    task: str = "test_task",
    eval_spec: EvalSpec | None = None,
) -> LogStart:
    """Write a synthetic crashed .eval ZIP file (no header.json)."""
    eval_spec = eval_spec or _make_eval_spec(task)
    plan = EvalPlan()
    log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

    with ZipFile(path, "w") as zf:
        zf.writestr("_journal/start.json", _to_json(log_start))
        if samples:
            summaries = []
            for sample in samples:
                zf.writestr(
                    f"samples/{sample.id}_epoch_{sample.epoch}.json",
                    _to_json(sample),
                )
                summaries.append(sample.summary())
            zf.writestr("_journal/summaries/1.json", _to_json(summaries))

    return log_start


def _create_buffer_db(
    location: str,
    completed_ids: list[int],
    in_progress_ids: list[int],
    db_dir: str | None = None,
) -> SampleBufferDatabase:
    """Create a buffer DB with a dead PID (simulating crashed process)."""
    db_path = Path(db_dir) if db_dir else None
    buffer = SampleBufferDatabase(location, create=True, db_dir=db_path)

    for id in completed_ids:
        started = EvalSampleSummary(
            id=id,
            epoch=1,
            input=f"input {id}",
            target=f"target {id}",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        buffer.start_sample(started)
        buffer.log_events(
            [SampleEvent(id=id, epoch=1, event=_make_model_event(f"output {id}"))]
        )
        completed = EvalSampleSummary(
            id=id,
            epoch=1,
            input=f"input {id}",
            target=f"target {id}",
            scores={"accuracy": Score(value="C", answer="C")},
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        buffer.complete_sample(completed, sample_metadata=None)

    for id in in_progress_ids:
        started = EvalSampleSummary(
            id=id,
            epoch=1,
            input=f"input {id}",
            target=f"target {id}",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        buffer.start_sample(started)
        buffer.log_events(
            [SampleEvent(id=id, epoch=1, event=_make_model_event(f"partial {id}"))]
        )

    # simulate a crashed process: snapshot the DB (incl. hot WAL) under a dead PID
    simulate_crashed_buffer_db(buffer)

    return buffer


async def test_recover_eval_log_end_to_end() -> None:
    """Full recovery: crashed .eval + buffer DB with mixed samples."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            flushed = [_make_sample(1), _make_sample(2)]
            _write_crashed_eval(eval_path, samples=flushed)
            _create_buffer_db(
                eval_path, completed_ids=[3], in_progress_ids=[4], db_dir=db_dir
            )

            log = await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            assert log.status == "error"
            assert log.error is not None
            assert log.samples is not None
            assert len(log.samples) == 4

            read_log = await read_eval_log_async(output_path)
            assert read_log.status == "error"
            assert read_log.samples is not None
            assert len(read_log.samples) == 4


async def test_recover_incomplete_action_error_finalizes() -> None:
    """incomplete_action='error' resolves in-progress samples and finalizes.

    All 4 expected samples are present (2 flushed, 1 buffer-complete, 1
    in-progress resolved as an error), so the recovered log finalizes with
    status 'success' and results covering the expected sample count.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            flushed = [_make_sample(1), _make_sample(2)]
            _write_crashed_eval(eval_path, samples=flushed)
            _create_buffer_db(
                eval_path, completed_ids=[3], in_progress_ids=[4], db_dir=db_dir
            )

            log = await recover_eval_log_async(
                eval_path,
                output=output_path,
                cleanup=False,
                _db_dir=db_dir,
                incomplete_action="error",
            )

            assert log.status == "success"
            assert log.error is None
            assert log.results is not None
            assert log.results.total_samples == 4

            read_log = await read_eval_log_async(output_path)
            assert read_log.status == "success"
            assert read_log.samples is not None
            assert len(read_log.samples) == 4

            resolved = next(s for s in read_log.samples if s.id == 4)
            assert resolved.error is not None
            assert "terminated by operator during recovery" in resolved.error.message
            assert resolved.scores is None

            completed = next(s for s in read_log.samples if s.id == 3)
            assert completed.error is None
            assert completed.scores is not None


async def test_recover_incomplete_action_error_missing_samples_stays_error() -> None:
    """Missing (never started) samples prevent finalization.

    Only 3 of the 4 expected samples are present, so the log keeps status
    'error' and remains retryable — while the in-progress sample is still
    marked with the operator-termination error.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            flushed = [_make_sample(1), _make_sample(2)]
            _write_crashed_eval(eval_path, samples=flushed)
            _create_buffer_db(
                eval_path, completed_ids=[], in_progress_ids=[3], db_dir=db_dir
            )

            log = await recover_eval_log_async(
                eval_path,
                output=output_path,
                cleanup=False,
                _db_dir=db_dir,
                incomplete_action="error",
            )

            assert log.status == "error"
            assert log.error is not None

            read_log = await read_eval_log_async(output_path)
            assert read_log.samples is not None
            assert len(read_log.samples) == 3
            resolved = next(s for s in read_log.samples if s.id == 3)
            assert resolved.error is not None
            assert "terminated by operator during recovery" in resolved.error.message


async def test_recover_incomplete_max() -> None:
    """incomplete_max refuses to resolve too many in-progress samples."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            flushed = [_make_sample(1), _make_sample(2)]
            _write_crashed_eval(eval_path, samples=flushed)
            _create_buffer_db(
                eval_path, completed_ids=[], in_progress_ids=[3, 4], db_dir=db_dir
            )

            # count form: 2 in-progress > 1
            with pytest.raises(RecoveryThresholdExceeded):
                await recover_eval_log_async(
                    eval_path,
                    output=output_path,
                    cleanup=False,
                    _db_dir=db_dir,
                    incomplete_action="error",
                    incomplete_max=1,
                )

            # proportion form: 2 of 4 expected = 0.5 > 0.25
            with pytest.raises(RecoveryThresholdExceeded):
                await recover_eval_log_async(
                    eval_path,
                    output=output_path,
                    cleanup=False,
                    _db_dir=db_dir,
                    incomplete_action="error",
                    incomplete_max=0.25,
                )

            # nothing was written by the refused recoveries
            assert not os.path.exists(output_path)

            # at the threshold the recovery proceeds and finalizes
            log = await recover_eval_log_async(
                eval_path,
                output=output_path,
                cleanup=False,
                _db_dir=db_dir,
                incomplete_action="error",
                incomplete_max=2,
            )
            assert log.status == "success"


async def test_recover_incomplete_action_error_finalizes_limited_eval() -> None:
    """A limited eval is sized from its selected sample ids, not the dataset.

    The dataset has 100 samples but the eval ran with a limit of 4 (recorded
    as `sample_ids`), and all 4 are present after recovery — so the log
    finalizes even though far fewer than `dataset.samples` were run.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            flushed = [_make_sample(1), _make_sample(2)]
            _write_crashed_eval(
                eval_path,
                samples=flushed,
                eval_spec=_make_eval_spec(samples=100, sample_ids=[1, 2, 3, 4]),
            )
            _create_buffer_db(
                eval_path, completed_ids=[3], in_progress_ids=[4], db_dir=db_dir
            )

            log = await recover_eval_log_async(
                eval_path,
                output=output_path,
                cleanup=False,
                _db_dir=db_dir,
                incomplete_action="error",
            )

            assert log.status == "success"
            assert log.error is None
            assert log.results is not None
            assert log.results.total_samples == 4


async def test_recover_incomplete_max_proportion_of_limited_eval() -> None:
    """The proportion form of incomplete_max is relative to the selected samples.

    2 of the 4 selected samples are in progress (50%). Against the unsliced
    dataset size of 100 that would be 2%, so a guard of 0.4 must still refuse.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            flushed = [_make_sample(1), _make_sample(2)]
            _write_crashed_eval(
                eval_path,
                samples=flushed,
                eval_spec=_make_eval_spec(samples=100, sample_ids=[1, 2, 3, 4]),
            )
            _create_buffer_db(
                eval_path, completed_ids=[], in_progress_ids=[3, 4], db_dir=db_dir
            )

            with pytest.raises(RecoveryThresholdExceeded):
                await recover_eval_log_async(
                    eval_path,
                    output=output_path,
                    cleanup=False,
                    _db_dir=db_dir,
                    incomplete_action="error",
                    incomplete_max=0.4,
                )
            assert not os.path.exists(output_path)


async def test_recover_eval_log_preserves_completed_sample_metadata() -> None:
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")
            _write_crashed_eval(eval_path)

            initial = {"world": {f"cell-{i}": {"active": True} for i in range(80)}}
            final = {
                "world": {
                    **initial["world"],
                    "solver-added": {"active": False},
                }
            }
            summary = EvalSampleSummary(
                id=1,
                epoch=1,
                input="input 1",
                target="target 1",
                metadata=initial,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            assert summary.metadata["world"] == "Key removed from summary (> 1k)"

            buffer = SampleBufferDatabase(eval_path, create=True, db_dir=Path(db_dir))
            buffer.start_sample(summary)
            buffer.log_events(
                [SampleEvent(id=1, epoch=1, event=_make_model_event("output 1"))]
            )
            buffer.complete_sample(summary, sample_metadata=final)
            simulate_crashed_buffer_db(buffer)

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            recovered = await read_eval_log_async(output_path)
            assert recovered.samples is not None
            assert recovered.samples[0].metadata == final


async def test_recover_eval_log_no_buffer_db() -> None:
    """Recovery with no buffer DB raises RecoveryNotAvailable."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            flushed = [_make_sample(1), _make_sample(2)]
            _write_crashed_eval(eval_path, samples=flushed)

            with pytest.raises(RecoveryNotAvailable):
                await recover_eval_log_async(
                    eval_path, output=output_path, _db_dir=db_dir
                )


async def test_recover_eval_log_cleanup() -> None:
    """Verify buffer DB is cleaned up after recovery and content is preserved."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            _write_crashed_eval(eval_path)
            buffer = _create_buffer_db(
                eval_path, completed_ids=[1], in_progress_ids=[], db_dir=db_dir
            )
            db_path = buffer.db_path

            assert db_path.exists()

            log = await recover_eval_log_async(
                eval_path, output=output_path, cleanup=True, _db_dir=db_dir
            )

            assert not db_path.exists()
            assert log.samples is not None
            assert len(log.samples) >= 1


async def test_recover_eval_log_no_cleanup() -> None:
    """Verify buffer DB is preserved when cleanup=False."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            _write_crashed_eval(eval_path)
            _create_buffer_db(
                eval_path, completed_ids=[1], in_progress_ids=[], db_dir=db_dir
            )

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            # Buffer DB dir should still have files
            assert any(Path(db_dir).rglob("*.db"))


async def test_recover_eval_log_default_output_path() -> None:
    """Verify default output path is <name>-recovered.eval."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "mylog.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")

            _write_crashed_eval(eval_path)
            _create_buffer_db(
                eval_path, completed_ids=[1], in_progress_ids=[], db_dir=db_dir
            )

            await recover_eval_log_async(eval_path, _db_dir=db_dir)

            expected = os.path.join(temp_dir, "mylog-recovered.eval")
            assert os.path.exists(expected)


def test_recoverable_eval_logs() -> None:
    """Test discovery of recoverable logs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_dir = os.path.join(temp_dir, "bufferdb")

        crashed_path = os.path.join(temp_dir, "crashed.eval")
        _write_crashed_eval(crashed_path)
        _create_buffer_db(
            crashed_path, completed_ids=[1], in_progress_ids=[2], db_dir=db_dir
        )

        # Create a complete log (should be excluded)
        complete_path = os.path.join(temp_dir, "complete.eval")
        eval_spec = _make_eval_spec("complete_task")
        plan = EvalPlan()
        log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)
        with ZipFile(complete_path, "w") as zf:
            zf.writestr("_journal/start.json", _to_json(log_start))
            header = EvalLog(
                version=LOG_SCHEMA_VERSION,
                eval=eval_spec,
                plan=plan,
                status="success",
            )
            zf.writestr(HEADER_JSON, _to_json(header))

        result = recoverable_eval_logs(log_dir=temp_dir, _db_dir=db_dir)

        assert len(result) == 1
        assert "crashed.eval" in result[0].log.name
        assert result[0].completed_samples == 1
        assert result[0].in_progress_samples == 1


def test_recoverable_eval_logs_excludes_already_recovered() -> None:
    """Test that already-recovered logs are excluded."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_dir = os.path.join(temp_dir, "bufferdb")

        crashed_path = os.path.join(temp_dir, "test.eval")
        _write_crashed_eval(crashed_path)
        _create_buffer_db(
            crashed_path, completed_ids=[1], in_progress_ids=[], db_dir=db_dir
        )

        # Create the recovered file (simulating prior recovery)
        recovered_path = os.path.join(temp_dir, "test-recovered.eval")
        eval_spec = _make_eval_spec()
        plan = EvalPlan()
        log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)
        with ZipFile(recovered_path, "w") as zf:
            zf.writestr("_journal/start.json", _to_json(log_start))
            header = EvalLog(
                version=LOG_SCHEMA_VERSION,
                eval=eval_spec,
                plan=plan,
                status="error",
            )
            zf.writestr(HEADER_JSON, _to_json(header))

        result = recoverable_eval_logs(log_dir=temp_dir, _db_dir=db_dir)
        assert len(result) == 0


def test_recover_async_paths_trio() -> None:
    """Regression: async recovery + discovery must work under a trio backend.

    ``recover_eval_log_async()`` and ``_recoverable_eval_logs_async()`` list
    logs through ``list_eval_logs_async`` / the async header read. A regression
    would let them fall through to the sync ``read_eval_log()``, which raises
    ``RuntimeError`` inside a trio async context. Runs via
    ``anyio.run(backend="trio")`` so the trio path is exercised on regular CI,
    which has no ``--runtrio`` leg (see the NOTE above the trio tests in
    test_eval_log.py). Deliberately runs without a caller-provided
    ``AsyncFilesystem`` — the public API must be self-contained, entering one
    itself wherever it needs async file access.
    """

    async def check() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            flushed = [_make_sample(1), _make_sample(2)]
            _write_crashed_eval(eval_path, samples=flushed)
            _create_buffer_db(
                eval_path, completed_ids=[3], in_progress_ids=[4], db_dir=db_dir
            )

            # Async discovery helper must resolve the crashed log under trio.
            recoverable = await _recoverable_eval_logs_async(
                log_dir=temp_dir, _db_dir=db_dir
            )
            assert len(recoverable) == 1
            assert "test.eval" in recoverable[0].log.name

            # Async recovery must combine flushed + buffered samples under trio.
            log = await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )
            assert log.samples is not None
            assert len(log.samples) == 4

    anyio.run(check, backend="trio")


def test_sync_recoverable_eval_logs_raises_under_trio() -> None:
    """Sync discovery is still trio-prohibited (the run_coroutine guard)."""
    import warnings

    async def check() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with warnings.catch_warnings():
                # run_coroutine raises before awaiting the coroutine it was given.
                warnings.simplefilter("ignore", RuntimeWarning)
                with pytest.raises(RuntimeError, match="run_coroutine"):
                    recoverable_eval_logs(log_dir=temp_dir)

    anyio.run(check, backend="trio")
