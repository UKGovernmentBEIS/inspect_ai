"""Read recovery data from the sample buffer database."""

from dataclasses import dataclass, field
from pathlib import Path

from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase


@dataclass
class BufferRecoveryData:
    """Recovery data extracted from a sample buffer database."""

    completed: list[EvalSampleSummary] = field(default_factory=list)
    """Samples that finished (scored) before the crash."""

    in_progress: list[EvalSampleSummary] = field(default_factory=list)
    """Samples that were still running when the crash happened."""

    buffer: SampleBufferDatabase | None = None
    """Open database handle for per-sample event/attachment queries."""


def read_buffer_recovery_data(
    location: str, db_dir: str | Path | None = None
) -> BufferRecoveryData | None:
    """Read unflushed sample data from the buffer database for a crashed eval.

    Args:
        location: Path to the .eval log file (used to locate the corresponding
            buffer database).
        db_dir: Optional override for the buffer database directory.

    Returns:
        BufferRecoveryData with completed/in-progress samples and an open
        database handle, or None if no buffer database exists for this log.
    """
    db_path = Path(db_dir) if db_dir is not None else None
    try:
        buffer = SampleBufferDatabase(location, create=False, db_dir=db_path)
    except FileNotFoundError:
        return None

    result = buffer.get_samples()
    if result is None or result == "NotModified":
        return BufferRecoveryData(buffer=buffer)

    completed: list[EvalSampleSummary] = []
    in_progress: list[EvalSampleSummary] = []

    for sample in result.samples:
        if sample.completed_at is not None:
            completed.append(sample)
        else:
            in_progress.append(sample)

    return BufferRecoveryData(
        completed=completed,
        in_progress=in_progress,
        buffer=buffer,
    )
