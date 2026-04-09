"""Public API for eval log recovery."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from inspect_ai._util._async import run_coroutine
from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.file import filesystem
from inspect_ai.log._file import EvalLogInfo, list_eval_logs
from inspect_ai.log._log import EvalLog, EvalSample

from ._buffer import read_buffer_recovery_data
from ._read import read_crashed_eval_log, read_flushed_sample
from ._reconstruct import reconstruct_eval_sample
from ._write import default_output_path, write_recovered_eval_log

logger = logging.getLogger(__name__)


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


async def recover_eval_log(
    log: str,
    output: str | None = None,
    cleanup: bool = True,
    _db_dir: str | Path | None = None,
) -> EvalLog:
    """Recover a crashed eval log.

    Combines flushed samples from the .eval file with unflushed samples
    from the sample buffer database to produce a recovered log file.

    Args:
        log: Path to the crashed .eval file.
        output: Output path (default: <name>-recovered.eval alongside original).
        cleanup: Remove the buffer DB after recovery.

    Returns:
        The recovered EvalLog.

    Raises:
        ValueError: If the log is not crashed or is invalid.
    """
    # Step 1: Read the crashed .eval file
    crashed = await read_crashed_eval_log(log)

    # Read flushed samples from the .eval file
    flushed_samples: list[EvalSample] = []
    if crashed.sample_entries:
        async with AsyncFilesystem() as fs:
            reader = AsyncZipReader(fs, log)
            for entry_name in crashed.sample_entries:
                sample = await read_flushed_sample(reader, entry_name)
                flushed_samples.append(sample)

    # Track flushed sample keys to deduplicate against buffer DB
    # (crash can occur between recorder.flush() and buffer_db.remove_samples(),
    # leaving a sample in both the .eval file and the buffer DB)
    flushed_keys = {(str(s.id), s.epoch) for s in flushed_samples}

    # Step 2: Read buffer DB
    buffer_samples: list[EvalSample] = []
    recovery_data = read_buffer_recovery_data(log, db_dir=_db_dir)

    if recovery_data is not None and recovery_data.buffer is not None:
        # Step 3: Reconstruct samples from buffer DB (skip duplicates)
        for summary in recovery_data.completed:
            if (str(summary.id), summary.epoch) in flushed_keys:
                continue
            sample_data = recovery_data.buffer.get_sample_data(
                summary.id, summary.epoch
            )
            if sample_data is not None:
                sample = reconstruct_eval_sample(summary, sample_data)
                buffer_samples.append(sample)

        for summary in recovery_data.in_progress:
            if (str(summary.id), summary.epoch) in flushed_keys:
                continue
            sample_data = recovery_data.buffer.get_sample_data(
                summary.id, summary.epoch
            )
            if sample_data is not None:
                sample = reconstruct_eval_sample(summary, sample_data, cancelled=True)
                buffer_samples.append(sample)
    else:
        logger.warning(
            f"No sample buffer database found for {log}. "
            "Only flushed samples will be recovered."
        )

    # Step 4: Write the recovered file
    output = output or default_output_path(log)
    recovered_log = await write_recovered_eval_log(
        crashed, flushed_samples, buffer_samples, output=output
    )

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
    log_dir = log_dir or os.environ.get("INSPECT_LOG_DIR", "./logs")

    # Find crashed logs (status == "started")
    crashed_logs = list_eval_logs(
        log_dir=log_dir,
        filter=lambda log: log.status == "started",
    )

    result: list[RecoverableEvalLog] = []

    for log_info in crashed_logs:
        location = log_info.name

        # Check if already recovered
        recovered_path = default_output_path(location)
        fs = filesystem(recovered_path)
        if fs.exists(recovered_path):
            continue

        # Check if buffer DB exists (filters out live PIDs, picks newest)
        recovery_data = read_buffer_recovery_data(location, db_dir=_db_dir)
        if recovery_data is None:
            continue

        completed = len(recovery_data.completed)
        in_progress = len(recovery_data.in_progress)

        # Read crashed log for flushed count and total expected (S3-compatible)
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
            )
        )

    return result
