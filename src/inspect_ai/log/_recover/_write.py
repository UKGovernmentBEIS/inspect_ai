"""Write recovered .eval files."""

from datetime import datetime, timezone
from logging import getLogger
from typing import Iterator

from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.error import EvalError
from inspect_ai.log._condense import condense_sample
from inspect_ai.log._log import (
    EvalLog,
    EvalResults,
    EvalSample,
    EvalSampleReductions,
    EvalSampleSummary,
    EvalStats,
)
from inspect_ai.log._recorders.eval import EvalRecorder
from inspect_ai.model._model_output import ModelUsage

from ._read import CrashedEvalLog, read_flushed_sample

logger = getLogger(__name__)

# Flush to disk every N samples to bound memory
_FLUSH_INTERVAL = 10


async def write_recovered_eval_log(
    crashed: CrashedEvalLog,
    buffer_samples: Iterator[EvalSample],
    output: str,
) -> EvalLog:
    """Write a recovered .eval file with true streaming.

    Flushed samples are read from the crashed .eval file one at a time
    via AsyncZipReader. Buffer DB samples are consumed from the provided
    iterator one at a time. Each sample is condensed and flushed to disk
    incrementally — memory usage is bounded to a small batch of samples.

    Args:
        crashed: Start data from the crashed .eval file.
        buffer_samples: Iterator of reconstructed buffer DB samples.
        output: Output file path.

    Returns:
        The written EvalLog (header only, samples on disk).
    """
    from inspect_ai._eval.score import (
        metrics_from_log_header,
        reducers_from_log_header,
        resolve_scorers,
    )
    from inspect_ai._eval.task.results import eval_results
    from inspect_ai._util.file import dirname
    from inspect_ai.scorer._metric import SampleScore

    output_dir = dirname(output)
    recorder = EvalRecorder(output_dir)

    await recorder.log_init(crashed.eval, location=output, clean=True)
    await recorder.log_start(crashed.eval, crashed.plan)

    sample_count = 0
    stats_acc = _StatsAccumulator(crashed)
    scores_acc: list[dict[str, SampleScore]] = []

    async def _write_sample(sample: EvalSample) -> None:
        nonlocal sample_count
        stats_acc.add_sample(sample)
        if sample.scores:
            scores_acc.append(
                {
                    name: SampleScore(
                        score=score,
                        sample_id=sample.id,
                        sample_metadata=sample.metadata,
                    )
                    for name, score in sample.scores.items()
                }
            )
        sample = condense_sample(sample)
        await recorder.log_sample(crashed.eval, sample)
        sample_count += 1
        if sample_count % _FLUSH_INTERVAL == 0:
            await recorder.flush(crashed.eval)

    # Stream flushed samples from the crashed .eval file one at a time
    if crashed.sample_entries:
        async with AsyncFilesystem() as fs:
            reader = AsyncZipReader(fs, crashed.location)
            for entry_name in crashed.sample_entries:
                sample = await read_flushed_sample(reader, entry_name)
                await _write_sample(sample)

    # Stream buffer DB samples from the iterator
    for sample in buffer_samples:
        await _write_sample(sample)

    # Compute results from collected scores
    results: EvalResults | None = None
    reductions: list[EvalSampleReductions] | None = None

    header = EvalLog(
        version=crashed.version,
        eval=crashed.eval,
        plan=crashed.plan,
        status="error",
    )

    try:
        reducers = reducers_from_log_header(header)
        metrics = metrics_from_log_header(header)
        scorers = resolve_scorers(header)
        results, reductions = eval_results(
            samples=sample_count,
            scores=scores_acc,
            reducers=reducers,
            scorers=scorers,
            metrics=metrics,
        )
    except Exception as ex:
        logger.warning(f"Unable to recompute metrics for recovered log: {ex}")

    error = EvalError(
        message="Eval recovered from crash",
        traceback="Eval process crashed; log recovered from sample buffer database.\n",
        traceback_ansi="Eval process crashed; log recovered from sample buffer database.\n",
    )

    return await recorder.log_finish(
        crashed.eval,
        "error",
        stats_acc.stats(),
        results,
        reductions,
        error=error,
    )


def default_output_path(location: str) -> str:
    """Compute default output path for a recovered .eval file."""
    if location.endswith(".eval"):
        return location[:-5] + "-recovered.eval"
    return location + "-recovered"


class _StatsAccumulator:
    """Incrementally accumulates EvalStats from streamed samples."""

    def __init__(self, crashed: CrashedEvalLog) -> None:
        self._started_at: str | None = crashed.eval.created
        self._model_usage: dict[str, ModelUsage] = {}
        self._role_usage: dict[str, ModelUsage] = {}

    def add_sample(self, sample: EvalSample) -> None:
        self._add_stats(sample.started_at, sample.model_usage, sample.role_usage)

    def add_summary(self, summary: EvalSampleSummary) -> None:
        self._add_stats(summary.started_at, summary.model_usage, summary.role_usage)

    def _add_stats(
        self,
        started_at: str | None,
        model_usage: dict[str, ModelUsage],
        role_usage: dict[str, ModelUsage],
    ) -> None:
        if started_at and (not self._started_at or started_at < self._started_at):
            self._started_at = started_at

        for model, usage in model_usage.items():
            if model not in self._model_usage:
                self._model_usage[model] = ModelUsage()
            self._model_usage[model] = _add_usage(self._model_usage[model], usage)
        for role, usage in role_usage.items():
            if role not in self._role_usage:
                self._role_usage[role] = ModelUsage()
            self._role_usage[role] = _add_usage(self._role_usage[role], usage)

    def stats(self) -> EvalStats:
        return EvalStats(
            started_at=self._started_at or "",
            completed_at=datetime.now(timezone.utc).isoformat(),
            model_usage=self._model_usage,
            role_usage=self._role_usage,
        )


def _add_usage(a: ModelUsage, b: ModelUsage) -> ModelUsage:
    """Sum two ModelUsage instances."""
    return ModelUsage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        total_tokens=a.total_tokens + b.total_tokens,
        input_tokens_cache_write=_add_optional(
            a.input_tokens_cache_write, b.input_tokens_cache_write
        ),
        input_tokens_cache_read=_add_optional(
            a.input_tokens_cache_read, b.input_tokens_cache_read
        ),
    )


def _add_optional(a: int | None, b: int | None) -> int | None:
    """Add two optional ints, returning None only if both are None."""
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)
