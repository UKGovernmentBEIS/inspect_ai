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
    EvalSpec,
    EvalStats,
    EvalStatus,
)
from inspect_ai.log._recorders.buffer.filestore import SampleBufferFilestore
from inspect_ai.log._recorders.eval import EvalRecorder
from inspect_ai.model._model_output import ModelUsage

from ._read import CrashedEvalLog, read_flushed_sample
from ._reconstruct import IncompleteAction
from ._stream import _write_sample_streaming

logger = getLogger(__name__)

# Flush to disk every N samples to bound memory
_FLUSH_INTERVAL = 10


@dataclass
class RecoveryStats:
    """Counts tracked during streaming recovery, without re-reading samples."""

    sample_count: int = 0
    failed_count: int = 0
    in_progress_count: int = 0


def expected_samples(eval: EvalSpec) -> int:
    """Total samples the eval expected to run (dataset samples x epochs)."""
    dataset_samples = (eval.dataset.samples or 0) if eval.dataset else 0
    return dataset_samples * (eval.config.epochs or 1)


async def write_recovered_eval_log(
    crashed: CrashedEvalLog,
    buffer_samples: Iterator[tuple[EvalSample, bool]],
    output: str,
    *,
    streaming_buffer: SampleBufferFilestore | None = None,
    streaming_summaries: list[tuple[EvalSampleSummary, bool]] | None = None,
    flushed_keys: set[str] | None = None,
    no_events: bool = False,
    incomplete_action: IncompleteAction = "retry",
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
        buffer_samples: Iterator of (reconstructed buffer DB sample,
            is_in_progress) tuples.
        output: Output file path.
        streaming_buffer: If set, use streaming segment-at-a-time path.
        streaming_summaries: (summary, is_in_progress) tuples for streaming.
        flushed_keys: Sample entry keys already flushed (for dedup).
        no_events: Exclude event transcript from recovered samples.
        incomplete_action: Disposition for samples in progress at crash.
            With `"error"` they are resolved (final, recorded as operator
            terminations), and when every expected sample is then final the
            recovered log is finalized with `status="success"`; with
            `"retry"` (default) they become cancelled errors and the log
            keeps `status="error"` so retries re-run them.
        stats: If provided, populated with sample and failed counts so
            callers can report progress without re-reading the just-written
            file (which would trigger lazy loading of all samples).

    Returns:
        The written EvalLog (header only, samples on disk).
    """
    from inspect_ai._eval.score import (
        metrics_from_log_header,
        reducers_from_log_header,
        resolve_scorers_info,
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
    in_progress_count = 0
    stats_acc = _StatsAccumulator(crashed)
    scores_acc: list[dict[str, SampleScore]] = []

    async def _write_sample(sample: EvalSample, in_progress: bool = False) -> None:
        nonlocal sample_count, failed_count, in_progress_count
        if in_progress:
            in_progress_count += 1
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
                if is_in_progress:
                    in_progress_count += 1
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
                written_summary, sample_metadata = _write_sample_streaming(
                    zip_log,
                    streaming_buffer,
                    summary,
                    manifest,
                    eval_spec=crashed.eval,
                    is_in_progress=is_in_progress,
                    incomplete_action=incomplete_action,
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
                                sample_metadata=sample_metadata,
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
        for sample, in_progress in buffer_samples:
            await _write_sample(sample, in_progress)

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
        scorers_info = resolve_scorers_info(header)
        results, reductions = eval_results(
            samples=sample_count,
            scores=scores_acc,
            reducers=reducers,
            scorers=scorers_info,
            metrics=metrics,
            # failed_count covers errored and still-in-progress samples, so
            # the remainder is exactly the samples that completed cleanly
            completed_samples=sample_count - failed_count,
            headline_metric=header.eval.headline_metric,
        )
    except Exception as ex:
        logger.warning(f"Unable to recompute metrics for recovered log: {ex}")

    # A resolving disposition finalizes the log with status "success" when
    # every expected sample is final (present in the recovered log: flushed,
    # buffer-complete, or resolved) — nothing is left to run, so eval_set's
    # completeness predicate is satisfied and nothing will retry it. If
    # expected samples are missing entirely (never started, or lost between
    # flush and crash), the log keeps status "error" and stays retryable.
    # `fail_on_error` is deliberately not applied: the operator explicitly
    # chose to complete the eval; recording the resolved samples as errors
    # is for analysis honesty, not for status computation. Finalization also
    # requires recomputed results — without them the log would fail the
    # completeness predicate and be re-run despite its "success" status.
    expected = expected_samples(crashed.eval)
    finalized = (
        incomplete_action == "error"
        and results is not None
        and expected > 0
        and sample_count >= expected
    )

    status: EvalStatus
    if finalized:
        status = "success"
        error = None
    else:
        status = "error"
        error = EvalError(
            message="Eval recovered from crash",
            traceback="Eval process crashed; log recovered from sample buffer database.\n",
            traceback_ansi="Eval process crashed; log recovered from sample buffer database.\n",
        )

    if stats is not None:
        stats.sample_count = sample_count
        stats.failed_count = failed_count
        stats.in_progress_count = in_progress_count

    return await recorder.log_finish(
        crashed.eval,
        status,
        stats_acc.stats(),
        results,
        reductions,
        error=error,
        config_updates=crashed.config_updates or None,
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
            self._model_usage[model] += usage
        for role, usage in role_usage.items():
            if role not in self._role_usage:
                self._role_usage[role] = ModelUsage()
            self._role_usage[role] += usage

    def stats(self) -> EvalStats:
        return EvalStats(
            started_at=self._started_at or "",
            completed_at=datetime.now(timezone.utc).isoformat(),
            model_usage=self._model_usage,
            role_usage=self._role_usage,
        )
