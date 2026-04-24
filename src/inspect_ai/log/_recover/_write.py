"""Write recovered .eval files."""

from __future__ import annotations

from dataclasses import dataclass
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
from inspect_ai.log._recorders.buffer.filestore import SampleBufferFilestore
from inspect_ai.log._recorders.eval import EvalRecorder
from inspect_ai.model._model_output import ModelUsage

from ._read import CrashedEvalLog, read_flushed_sample
from ._stream import _write_sample_streaming

logger = getLogger(__name__)

# Flush to disk every N samples to bound memory
_FLUSH_INTERVAL = 10


@dataclass
class RecoveryStats:
    """Counts tracked during streaming recovery, without re-reading samples."""

    sample_count: int = 0
    failed_count: int = 0


async def write_recovered_eval_log(
    crashed: CrashedEvalLog,
    buffer_samples: Iterator[EvalSample],
    output: str,
    *,
    streaming_buffer: SampleBufferFilestore | None = None,
    streaming_summaries: list[tuple[EvalSampleSummary, bool]] | None = None,
    flushed_keys: set[str] | None = None,
    no_events: bool = False,
    stats: RecoveryStats | None = None,
) -> EvalLog:
    """Write a recovered .eval file with true streaming.

    Flushed samples are read from the crashed .eval file one at a time
    via AsyncZipReader. Buffer DB samples are consumed from the provided
    iterator one at a time. Each sample is condensed and flushed to disk
    incrementally -- memory usage is bounded to a small batch of samples.

    When ``streaming_buffer`` is provided (filestore recovery), segments
    are processed one at a time via ``_write_sample_streaming`` and the
    ``buffer_samples`` iterator is ignored.

    Args:
        crashed: Start data from the crashed .eval file.
        buffer_samples: Iterator of reconstructed buffer DB samples.
        output: Output file path.
        streaming_buffer: If set, use streaming segment-at-a-time path.
        streaming_summaries: (summary, is_in_progress) tuples for streaming.
        flushed_keys: Sample entry keys already flushed (for dedup).
        no_events: Exclude event transcript from recovered samples.
        stats: If provided, populated with sample and failed counts so
            callers can report progress without re-reading the just-written
            file (which would trigger lazy loading of all samples).

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
    failed_count = 0
    stats_acc = _StatsAccumulator(crashed)
    scores_acc: list[dict[str, SampleScore]] = []

    async def _write_sample(sample: EvalSample) -> None:
        nonlocal sample_count, failed_count
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
        if sample.error is not None:
            failed_count += 1
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

    # Stream buffer samples
    if streaming_buffer is not None and streaming_summaries is not None:
        # Streaming path: process segments one at a time with bounded memory
        manifest = streaming_buffer.read_manifest()
        if manifest is not None:
            zip_log = recorder.data[recorder._log_file_key(crashed.eval)]
            effective_flushed = flushed_keys or set()
            total_streaming = len(streaming_summaries)
            processed = 0
            for summary, is_in_progress in streaming_summaries:
                entry = f"samples/{summary.id}_epoch_{summary.epoch}.json"
                if entry in effective_flushed:
                    continue
                processed += 1
                seg_count = next(
                    (
                        len(sm.segments)
                        for sm in manifest.samples
                        if sm.summary.id == summary.id
                        and sm.summary.epoch == summary.epoch
                    ),
                    0,
                )
                logger.info(
                    f"Recovering sample {processed}/{total_streaming} "
                    f"id={summary.id} epoch={summary.epoch} segments={seg_count}"
                )
                written_summary = _write_sample_streaming(
                    zip_log,
                    streaming_buffer,
                    summary,
                    manifest,
                    eval_spec=crashed.eval,
                    is_in_progress=is_in_progress,
                    include_events=not no_events,
                )
                stats_acc.add_summary(written_summary)
                if is_in_progress or written_summary.error is not None:
                    failed_count += 1
                zip_log._summaries.append(written_summary)
                if written_summary.scores:
                    scores_acc.append(
                        {
                            name: SampleScore(
                                score=score,
                                sample_id=written_summary.id,
                                sample_metadata=written_summary.metadata,
                            )
                            for name, score in written_summary.scores.items()
                        }
                    )
                sample_count += 1
                logger.info(
                    f"Recovered sample {processed}/{total_streaming} "
                    f"id={summary.id} epoch={summary.epoch}"
                )
                if sample_count % _FLUSH_INTERVAL == 0:
                    await recorder.flush(crashed.eval)
    else:
        # Non-streaming path: consume buffer_samples iterator
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

    if stats is not None:
        stats.sample_count = sample_count
        stats.failed_count = failed_count

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
