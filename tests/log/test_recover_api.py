"""End-to-end tests for the recovery API."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic_core import to_jsonable_python

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._file import read_eval_log
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
    recover_eval_log_async,
    recoverable_eval_logs,
)
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer._metric import Score


def _make_eval_spec(task: str = "test_task") -> EvalSpec:
    return EvalSpec(
        created=datetime.now(timezone.utc).isoformat(),
        task=task,
        model="mockllm/model",
        dataset=EvalDataset(name="test", samples=4),
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
) -> LogStart:
    """Write a synthetic crashed .eval ZIP file (no header.json)."""
    eval_spec = _make_eval_spec(task)
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


_DEAD_PID = 99999999  # PID that doesn't exist


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
        buffer.complete_sample(completed)

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

    # Rename DB file to use a dead PID (simulating a crashed process)
    old_path = buffer.db_path
    new_path = old_path.parent / old_path.name.replace(
        f".{os.getpid()}.", f".{_DEAD_PID}."
    )
    old_path.rename(new_path)
    buffer.db_path = new_path

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

            read_log = read_eval_log(output_path)
            assert read_log.status == "error"
            assert read_log.samples is not None
            assert len(read_log.samples) == 4


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
