"""Tests for reading crashed .eval files for recovery."""

import json
import os
import tempfile
from datetime import datetime, timezone
from zipfile import ZipFile

import pytest
from pydantic_core import to_jsonable_python

from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem, get_async_filesystem
from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalPlan,
    EvalSample,
    EvalSpec,
)
from inspect_ai.log._recorders.eval import (
    HEADER_JSON,
    LogStart,
)
from inspect_ai.log._recover import (
    CrashedEvalLog,
    read_crashed_eval_log,
    read_flushed_sample,
)
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
        output=ModelOutput.from_content(
            model="mockllm/model",
            content=f"output {id}",
        ),
        messages=[],
        scores={"accuracy": Score(value="C", answer="C")},
    )


def _to_json(obj: object) -> str:
    return json.dumps(to_jsonable_python(obj, exclude_none=True))


def _write_crashed_eval(
    path: str,
    *,
    task: str = "test_task",
    samples: list[EvalSample] | None = None,
    include_header: bool = False,
) -> LogStart:
    """Write a synthetic crashed .eval ZIP file."""
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

            zf.writestr(
                "_journal/summaries/1.json",
                _to_json(summaries),
            )

        if include_header:
            from inspect_ai.log._log import EvalLog

            header = EvalLog(
                version=LOG_SCHEMA_VERSION,
                eval=eval_spec,
                plan=plan,
                status="success",
            )
            zf.writestr(HEADER_JSON, _to_json(header))

    return log_start


async def test_read_crashed_eval_log_basic() -> None:
    """Test reading a crashed .eval file with flushed samples."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            samples = [_make_sample(1), _make_sample(2), _make_sample(3)]
            _write_crashed_eval(eval_path, samples=samples)

            crashed = await read_crashed_eval_log(eval_path)

            assert isinstance(crashed, CrashedEvalLog)
            assert crashed.location == eval_path
            assert crashed.version == LOG_SCHEMA_VERSION
            assert crashed.eval.task == "test_task"
            assert crashed.eval.model == "mockllm/model"
            assert crashed.plan is not None
            assert len(crashed.summaries) == 3
            assert len(crashed.sample_entries) == 3
            assert all(
                entry.startswith("samples/") and entry.endswith(".json")
                for entry in crashed.sample_entries
            )


async def test_read_crashed_eval_log_no_samples() -> None:
    """Test reading a crashed .eval file with no flushed samples."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            _write_crashed_eval(eval_path, samples=None)

            crashed = await read_crashed_eval_log(eval_path)

            assert crashed.eval.task == "test_task"
            assert len(crashed.summaries) == 0
            assert len(crashed.sample_entries) == 0


async def test_read_crashed_eval_log_rejects_complete() -> None:
    """Test that a complete log (with header.json) is rejected."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            _write_crashed_eval(eval_path, include_header=True)

            with pytest.raises(ValueError, match="not crashed"):
                await read_crashed_eval_log(eval_path)


async def test_read_crashed_eval_log_rejects_invalid() -> None:
    """Test that a ZIP without start.json is rejected."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            with ZipFile(eval_path, "w") as zf:
                zf.writestr("dummy.txt", "not a valid eval log")

            with pytest.raises(ValueError, match="invalid"):
                await read_crashed_eval_log(eval_path)


async def test_read_flushed_sample() -> None:
    """Test reading individual flushed samples from a crashed .eval file."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            original_samples = [_make_sample(1), _make_sample(2)]
            _write_crashed_eval(eval_path, samples=original_samples)

            crashed = await read_crashed_eval_log(eval_path)

            fs = get_async_filesystem()
            reader = AsyncZipReader(fs, eval_path)
            for entry_name in crashed.sample_entries:
                sample = await read_flushed_sample(reader, entry_name)
                assert isinstance(sample, EvalSample)
                assert sample.input in ["input 1", "input 2"]
                assert sample.target in ["target 1", "target 2"]


async def test_read_crashed_eval_log_multiple_flush_batches() -> None:
    """Test reading a crashed log with multiple flush batches of summaries."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")

            eval_spec = _make_eval_spec()
            plan = EvalPlan()
            log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

            batch1 = [_make_sample(1), _make_sample(2)]
            batch2 = [_make_sample(3), _make_sample(4)]

            with ZipFile(eval_path, "w") as zf:
                zf.writestr("_journal/start.json", _to_json(log_start))

                for sample in batch1 + batch2:
                    zf.writestr(
                        f"samples/{sample.id}_epoch_{sample.epoch}.json",
                        _to_json(sample),
                    )

                zf.writestr(
                    "_journal/summaries/1.json",
                    _to_json([s.summary() for s in batch1]),
                )
                zf.writestr(
                    "_journal/summaries/2.json",
                    _to_json([s.summary() for s in batch2]),
                )

            crashed = await read_crashed_eval_log(eval_path)

            assert len(crashed.summaries) == 4
            assert len(crashed.sample_entries) == 4
            summary_ids = [s.id for s in crashed.summaries]
            assert summary_ids == [1, 2, 3, 4]
