"""Tests for writing recovered .eval files."""

import os
import tempfile
from datetime import datetime, timezone

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
from inspect_ai.log._recover import (
    CrashedEvalLog,
    default_output_path,
    write_recovered_eval_log,
)
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.scorer._metric import Score


def _make_crashed_log(task: str = "test_task") -> CrashedEvalLog:
    return CrashedEvalLog(
        location="/tmp/test.eval",
        version=LOG_SCHEMA_VERSION,
        eval=EvalSpec(
            created=datetime.now(timezone.utc).isoformat(),
            task=task,
            model="mockllm/model",
            dataset=EvalDataset(name="test", samples=4),
            config=EvalConfig(),
        ),
        plan=EvalPlan(),
        summaries=[],
        sample_entries=[],
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
            crashed = _make_crashed_log()
            flushed = [_make_sample(1), _make_sample(2)]
            buffer = [_make_sample(3)]

            log = await write_recovered_eval_log(
                crashed, flushed, buffer, output=output
            )

            assert log.status == "error"
            assert log.error is not None
            assert (
                "recovered" in log.error.message.lower()
                or "crash" in log.error.message.lower()
            )
            assert log.eval.task == "test_task"
            assert log.samples is not None
            assert len(log.samples) == 3

            # Read back and verify
            read_log = read_eval_log(output)
            assert read_log.status == "error"
            assert read_log.samples is not None
            assert len(read_log.samples) == 3
            assert read_log.eval.task == "test_task"
            assert read_log.plan is not None


async def test_write_recovered_eval_log_sorted() -> None:
    """Test that samples are sorted by epoch then id."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "recovered.eval")
            crashed = _make_crashed_log()

            # Create samples out of order
            samples = [_make_sample(3), _make_sample(1), _make_sample(2)]

            log = await write_recovered_eval_log(crashed, samples, [], output=output)

            assert log.samples is not None
            ids = [s.id for s in log.samples]
            assert ids == [1, 2, 3]


async def test_write_recovered_eval_log_stats() -> None:
    """Test that EvalStats are computed from samples."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "recovered.eval")
            crashed = _make_crashed_log()
            samples = [_make_sample(1), _make_sample(2)]

            log = await write_recovered_eval_log(crashed, samples, [], output=output)

            assert log.stats is not None
            assert log.stats.started_at != ""
            assert log.stats.completed_at != ""
            # Model usage should be aggregated
            assert "mockllm/model" in log.stats.model_usage
            usage = log.stats.model_usage["mockllm/model"]
            assert usage.input_tokens == 20  # 10 * 2 samples
            assert usage.output_tokens == 10  # 5 * 2 samples


async def test_write_recovered_eval_log_mixed_scored() -> None:
    """Test recovery with mix of scored and unscored samples."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "recovered.eval")
            crashed = _make_crashed_log()
            scored = [_make_sample(1, scored=True)]
            unscored = [_make_sample(2, scored=False)]

            log = await write_recovered_eval_log(
                crashed, scored, unscored, output=output
            )

            assert log.samples is not None
            assert len(log.samples) == 2

            # Read back
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


async def test_write_recovered_eval_log_empty_samples() -> None:
    """Test recovery with no samples at all."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "recovered.eval")
            crashed = _make_crashed_log()

            log = await write_recovered_eval_log(crashed, [], [], output=output)

            assert log.status == "error"
            assert log.samples is not None
            assert len(log.samples) == 0

            read_log = read_eval_log(output)
            assert read_log.status == "error"
