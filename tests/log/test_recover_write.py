"""Tests for writing recovered .eval files."""

import json
import os
import tempfile
from datetime import datetime, timezone
from zipfile import ZipFile

from pydantic_core import to_jsonable_python

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai.log._file import read_eval_log
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalPlan,
    EvalSample,
    EvalSpec,
)
from inspect_ai.log._recorders.eval import LogStart
from inspect_ai.log._recover import (
    CrashedEvalLog,
    default_output_path,
    write_recovered_eval_log,
)
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.scorer._metric import Score


def _to_json(obj: object) -> str:
    return json.dumps(to_jsonable_python(obj, exclude_none=True))


def _make_crashed_log(
    temp_dir: str, task: str = "test_task", samples: list[EvalSample] | None = None
) -> CrashedEvalLog:
    """Create a CrashedEvalLog backed by an actual .eval ZIP file."""
    eval_spec = EvalSpec(
        created=datetime.now(timezone.utc).isoformat(),
        task=task,
        model="mockllm/model",
        dataset=EvalDataset(name="test", samples=4),
        config=EvalConfig(),
    )
    plan = EvalPlan()
    log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

    eval_path = os.path.join(temp_dir, "crashed.eval")
    sample_entries: list[str] = []

    with ZipFile(eval_path, "w") as zf:
        zf.writestr("_journal/start.json", _to_json(log_start))
        if samples:
            summaries = []
            for sample in samples:
                entry = f"samples/{sample.id}_epoch_{sample.epoch}.json"
                zf.writestr(entry, _to_json(sample))
                sample_entries.append(entry)
                summaries.append(sample.summary())
            zf.writestr("_journal/summaries/1.json", _to_json(summaries))

    return CrashedEvalLog(
        location=eval_path,
        version=LOG_SCHEMA_VERSION,
        eval=eval_spec,
        plan=plan,
        summaries=[s.summary() for s in samples] if samples else [],
        sample_entries=sample_entries,
    )


def _make_sample(id: int, epoch: int = 1, scored: bool = True) -> EvalSample:
    return EvalSample(
        id=id,
        epoch=epoch,
        input=f"input {id}",
        target=f"target {id}",
        output=ModelOutput.from_content(model="mockllm/model", content=f"output {id}"),
        messages=[],
        scores={"accuracy": Score(value="C", answer="C")} if scored else None,
        model_usage={
            "mockllm/model": ModelUsage(
                input_tokens=10, output_tokens=5, total_tokens=15
            )
        },
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat() if scored else None,
    )


async def test_write_recovered_eval_log_basic() -> None:
    """Test writing a recovered log and reading it back."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "recovered.eval")
            flushed = [_make_sample(1), _make_sample(2)]
            buffer = [_make_sample(3)]
            crashed = _make_crashed_log(temp_dir, samples=flushed)

            log = await write_recovered_eval_log(crashed, iter(buffer), output)

            assert log.status == "error"
            assert log.error is not None

            read_log = read_eval_log(output)
            assert read_log.status == "error"
            assert read_log.samples is not None
            assert len(read_log.samples) == 3  # 2 flushed + 1 buffer
            assert read_log.eval.task == "test_task"


async def test_write_recovered_eval_log_stats() -> None:
    """Test that EvalStats are computed from samples."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "recovered.eval")
            samples = [_make_sample(1), _make_sample(2)]
            crashed = _make_crashed_log(temp_dir, samples=samples)

            log = await write_recovered_eval_log(crashed, iter([]), output)

            assert log.stats is not None
            assert log.stats.started_at != ""
            assert log.stats.completed_at != ""
            assert "mockllm/model" in log.stats.model_usage
            usage = log.stats.model_usage["mockllm/model"]
            assert usage.input_tokens == 20
            assert usage.output_tokens == 10


async def test_write_recovered_eval_log_mixed_scored() -> None:
    """Test recovery with mix of scored and unscored samples."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "recovered.eval")
            scored = [_make_sample(1, scored=True)]
            crashed = _make_crashed_log(temp_dir, samples=scored)

            # Buffer has unscored sample
            unscored = [_make_sample(2, scored=False)]
            await write_recovered_eval_log(crashed, iter(unscored), output)

            read_log = read_eval_log(output)
            assert read_log.samples is not None
            scored_samples = [s for s in read_log.samples if s.scores]
            unscored_samples = [s for s in read_log.samples if not s.scores]
            assert len(scored_samples) == 1
            assert len(unscored_samples) == 1


def test_default_output_path() -> None:
    """Test default output path computation."""
    assert default_output_path("/tmp/mylog.eval") == "/tmp/mylog-recovered.eval"
    assert default_output_path("logs/test.eval") == "logs/test-recovered.eval"


async def test_write_recovered_eval_log_empty() -> None:
    """Test recovery with no samples at all."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "recovered.eval")
            crashed = _make_crashed_log(temp_dir)

            log = await write_recovered_eval_log(crashed, iter([]), output)

            assert log.status == "error"
            read_log = read_eval_log(output)
            assert read_log.status == "error"
