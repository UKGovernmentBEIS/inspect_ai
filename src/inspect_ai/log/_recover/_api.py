"""Public API for eval log recovery."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from inspect_ai._util._async import run_coroutine
from inspect_ai._util.file import dirname, filesystem
from inspect_ai.log._file import (
    EvalLogInfo,
    list_eval_logs_async,
    read_eval_log_async,
)
from inspect_ai.log._log import EvalLog, EvalSample, EvalSampleSummary
from inspect_ai.log._recorders.buffer.filestore import SampleBufferFilestore

from ._buffer import read_buffer_recovery_data
from ._read import read_crashed_eval_log
from ._reconstruct import IncompleteAction, reconstruct_eval_sample
from ._write import (
    RecoveryStats,
    default_output_path,
    expected_samples,
    write_recovered_eval_log,
)

logger = logging.getLogger(__name__)


class RecoveryNotAvailable(Exception):
    """Recovery data is not available for the given log.

    Raised when there is nothing to recover — the log is already complete,
    or no sample buffer database exists. This is a normal condition, not an
    error. Opportunistic callers should catch this silently.
    """


class RecoveryThresholdExceeded(Exception):
    """More samples were in progress at crash than `incomplete_max` allows.

    Raised before any recovery output is written, so the log remains
    recoverable exactly as it was. A large in-progress set usually signals a
    systemic failure (e.g. a provider outage) rather than a stalled tail, so
    resolving it per the disposition would silently complete an eval whose
    samples should re-run. Callers that recover opportunistically
    (`eval_retry` / `eval_set`) catch this and fall back to the default
    `"retry"` disposition.
    """


@dataclass
class RecoverableEvalLog:
    """A crashed eval log that can be recovered."""

    log: EvalLogInfo
    """File info and task identifiers."""

    flushed_samples: int
    """Number of samples already flushed to the .eval file."""

    completed_samples: int
    """Number of completed (scored) samples in the buffer DB."""

    in_progress_samples: int
    """Number of in-progress (unscored) samples in the buffer DB."""

    total_samples: int
    """Total expected samples (dataset samples * epochs)."""

    source: str = "database"
    """Recovery data source: "database" or "filestore"."""


def recover_eval_log(
    log: str,
    output: str | None = None,
    overwrite: bool = False,
    cleanup: bool = True,
    no_events: bool = False,
    incomplete_action: IncompleteAction = "retry",
    incomplete_max: int | float | None = None,
    _stats: RecoveryStats | None = None,
) -> EvalLog:
    """Recover a crashed eval log.

    Combines flushed samples from the .eval file with unflushed samples
    from the sample buffer database to produce a recovered log file.

    Args:
        log: Path to the crashed .eval file.
        output: Output path (default: <name>-recovered.eval alongside original).
        overwrite: Write the recovered log to the same path as the input,
            replacing the crashed log in-place.
        cleanup: Remove the buffer DB after recovery.
        no_events: Exclude event transcript from recovered samples.
        incomplete_action: Disposition for samples that were in progress at
            crash. `"retry"` (default) marks them as cancelled errors that a
            later retry re-runs; `"error"` resolves them as operator
            terminations, and when every expected sample is then final the
            recovered log is finalized with `status="success"` (nothing will
            retry it).
        incomplete_max: Safety threshold for `incomplete_action="error"`
            (count, or proportion of expected samples if < 1): raise
            `RecoveryThresholdExceeded` — before writing anything — when more
            than this many samples are in progress. `None` = no guard.

    Returns:
        The recovered EvalLog.

    Raises:
        RecoveryNotAvailable: There is nothing to recover.
        RecoveryThresholdExceeded: More samples were in progress than
            `incomplete_max` allows.
    """
    return run_coroutine(
        recover_eval_log_async(
            log,
            output=output,
            overwrite=overwrite,
            cleanup=cleanup,
            no_events=no_events,
            incomplete_action=incomplete_action,
            incomplete_max=incomplete_max,
            _stats=_stats,
        )
    )


async def recover_eval_log_async(
    log: str,
    output: str | None = None,
    overwrite: bool = False,
    cleanup: bool = True,
    _db_dir: str | Path | None = None,
    no_events: bool = False,
    incomplete_action: IncompleteAction = "retry",
    incomplete_max: int | float | None = None,
    _stats: RecoveryStats | None = None,
) -> EvalLog:
    """Async implementation of recover_eval_log."""
    # Step 1: Read the crashed .eval file metadata
    try:
        crashed = await read_crashed_eval_log(log)
    except ValueError:
        raise RecoveryNotAvailable(f"Log is not recoverable: {log}")

    # Resolve output paths. When overwriting, write to a temp sibling path
    # first to avoid corrupting the source file (which is read during
    # recovery), then move to the final path after successful write.
    if overwrite:
        final_output = log
        write_output = default_output_path(log)
    else:
        final_output = None
        write_output = output or default_output_path(log)

    # Guard: if a successful log for this task already exists in the
    # output directory, recovery would create a newer file that interferes
    # with eval set state (mtime-based log selection). This naturally
    # allows automatic recovery (eval_retry/eval_set) since they recover
    # crashed logs before a successful retry exists.
    output_dir = dirname(write_output)
    task_id = crashed.eval.task_id
    existing = await list_eval_logs_async(
        log_dir=output_dir,
        filter=lambda log_header: (
            log_header.status == "success" and log_header.eval.task_id == task_id
        ),
        recursive=False,
    )
    if existing:
        raise RecoveryNotAvailable(
            f"A successful log for task '{crashed.eval.task}' already "
            f"exists in {output_dir}. Use output= to write the recovered "
            f"file to a different location."
        )

    # Step 2: Read buffer DB metadata (lightweight — just summaries)
    recovery_data = read_buffer_recovery_data(log, db_dir=_db_dir)
    if recovery_data is None:
        raise RecoveryNotAvailable(f"No sample buffer database found for {log}")

    # Derive flushed sample keys for deduplication against buffer DB
    flushed_keys = set(crashed.sample_entries)

    # Guard: refuse a resolving disposition when more samples are in progress
    # than incomplete_max allows (checked before anything is written)
    if incomplete_action != "retry" and incomplete_max is not None:
        unresolved = [
            summary
            for summary in recovery_data.in_progress
            if f"samples/{summary.id}_epoch_{summary.epoch}.json" not in flushed_keys
        ]
        threshold = (
            incomplete_max
            if incomplete_max >= 1
            else incomplete_max * expected_samples(crashed.eval)
        )
        if len(unresolved) > threshold:
            raise RecoveryThresholdExceeded(
                f"Refusing to resolve {len(unresolved)} in-progress samples "
                f"(incomplete_max={incomplete_max}). The log remains recoverable; "
                f"recover with incomplete_action='retry' or raise the threshold."
            )

    # Step 3: Determine recovery path and write
    buffer = recovery_data.buffer if recovery_data else None
    streaming_buffer: SampleBufferFilestore | None = None
    streaming_summaries: list[tuple[EvalSampleSummary, bool]] | None = None

    if isinstance(buffer, SampleBufferFilestore):
        # Streaming path: pass buffer handle to writer for segment-at-a-time
        streaming_buffer = buffer
        streaming_summaries = [
            (summary, False) for summary in recovery_data.completed
        ] + [(summary, True) for summary in recovery_data.in_progress]

    # Lazy generator for non-filestore (database) buffers
    def _buffer_samples() -> Iterator[tuple[EvalSample, bool]]:
        if buffer is None or isinstance(buffer, SampleBufferFilestore):
            return

        all_summaries = [
            (summary, False)
            for summary in recovery_data.completed  # type: ignore[union-attr]
        ] + [
            (summary, True)
            for summary in recovery_data.in_progress  # type: ignore[union-attr]
        ]

        for summary, is_in_progress in all_summaries:
            entry = f"samples/{summary.id}_epoch_{summary.epoch}.json"
            if entry in flushed_keys:
                continue

            sample_data = buffer.get_sample_data(summary.id, summary.epoch)

            if sample_data is not None:
                yield (
                    reconstruct_eval_sample(
                        summary,
                        sample_data,
                        sample_metadata=buffer.get_sample_metadata(
                            summary.id, summary.epoch
                        ),
                        cancelled=is_in_progress,
                        incomplete_action=incomplete_action,
                        include_events=not no_events,
                    ),
                    is_in_progress,
                )

    # Step 4: Stream all samples into the recovered file.
    recovered_log = await write_recovered_eval_log(
        crashed,
        _buffer_samples(),
        write_output,
        streaming_buffer=streaming_buffer,
        streaming_summaries=streaming_summaries,
        flushed_keys=flushed_keys,
        no_events=no_events,
        incomplete_action=incomplete_action,
        stats=_stats,
    )

    # For overwrite mode, move the temp file over the original and
    # re-read so lazy sample data points to the correct location.
    if final_output is not None:
        fs = filesystem(final_output)
        fs.rm(final_output)
        fs.mv(write_output, final_output)
        recovered_log = await read_eval_log_async(final_output)

    # Cleanup buffer DB (only after successful write)
    if cleanup and recovery_data is not None and recovery_data.buffer is not None:
        recovery_data.buffer.cleanup()

    return recovered_log


def recoverable_eval_logs(
    log_dir: str | None = None,
    _db_dir: str | Path | None = None,
) -> list[RecoverableEvalLog]:
    """List eval logs that can be recovered.

    A log is recoverable when it has status "started" (crashed before
    completion), a corresponding sample buffer database exists (with a
    dead owning process), and no recovered file already exists.

    Args:
        log_dir: Log directory (defaults to INSPECT_LOG_DIR or ./logs).

    Returns:
        List of recoverable logs with recovery stats.
    """
    return run_coroutine(_recoverable_eval_logs_async(log_dir, _db_dir=_db_dir))


async def _recoverable_eval_logs_async(
    log_dir: str | None = None,
    _db_dir: str | Path | None = None,
) -> list[RecoverableEvalLog]:
    log_dir = log_dir or os.environ.get("INSPECT_LOG_DIR", "./logs") or "./logs"

    crashed_logs = await list_eval_logs_async(
        log_dir=log_dir,
        filter=lambda log: log.status == "started",
    )

    result: list[RecoverableEvalLog] = []

    for log_info in crashed_logs:
        location = log_info.name

        recovered_path = default_output_path(location)
        fs = filesystem(recovered_path)
        if fs.exists(recovered_path):
            continue

        recovery_data = read_buffer_recovery_data(location, db_dir=_db_dir)
        if recovery_data is None:
            continue

        completed = len(recovery_data.completed)
        in_progress = len(recovery_data.in_progress)

        try:
            crashed = await read_crashed_eval_log(location)
            flushed = len(crashed.sample_entries)
            dataset_samples = (
                (crashed.eval.dataset.samples or 0) if crashed.eval.dataset else 0
            )
            epochs = crashed.eval.config.epochs or 1
            total = dataset_samples * epochs
        except Exception:
            flushed = 0
            total = 0

        result.append(
            RecoverableEvalLog(
                log=log_info,
                flushed_samples=flushed,
                completed_samples=completed,
                in_progress_samples=in_progress,
                total_samples=total,
                source=recovery_data.source,
            )
        )

    return result
