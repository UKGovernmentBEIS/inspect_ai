"""Read recovery data from the sample buffer database."""

from dataclasses import dataclass, field
from pathlib import Path

import psutil

from inspect_ai._util.file import filesystem
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer.database import (
    SampleBufferDatabase,
    location_dir_and_file,
    resolve_db_dir,
)


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

    Locates the buffer database for the given log file, filtering out
    databases whose owning process is still alive (those belong to
    running evals, not crashed ones). When multiple databases exist,
    picks the one with the newest modification time.

    Args:
        location: Path to the .eval log file (used to locate the corresponding
            buffer database).
        db_dir: Optional override for the buffer database directory.

    Returns:
        BufferRecoveryData with completed/in-progress samples and an open
        database handle, or None if no eligible buffer database exists.
    """
    db_path = _find_crashed_buffer_db(location, db_dir)
    if db_path is None:
        return None

    # Open the database using the resolved db_dir, then override db_path
    # to ensure we use the specific file we selected (not an arbitrary glob match)
    resolved_db_dir = db_path.parent.parent
    buffer = SampleBufferDatabase(location, create=False, db_dir=resolved_db_dir)
    buffer.db_path = db_path

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


def _find_crashed_buffer_db(
    location: str, db_dir: str | Path | None = None
) -> Path | None:
    """Find the buffer DB for a crashed eval, filtering out live processes.

    Args:
        location: Path to the .eval log file.
        db_dir: Optional override for the buffer database directory.

    Returns:
        Path to the best candidate buffer DB, or None if none found.
    """
    resolved_dir = resolve_db_dir(Path(db_dir) if db_dir is not None else None)
    uri = filesystem(location).path_as_uri(location)
    dir_hash, file = location_dir_and_file(uri)
    log_subdir = resolved_dir / dir_hash

    if not log_subdir.exists():
        return None

    # Find all matching DB files
    candidates: list[Path] = []
    for db_file in log_subdir.glob(f"{file}.*.db"):
        # Extract PID from filename: {file}.{pid}.db
        parts = db_file.name.rsplit(".", 2)
        if len(parts) != 3:
            continue
        pid_str = parts[1]
        if not pid_str.isdigit():
            continue

        # Skip if the owning process is still alive (eval still running)
        pid = int(pid_str)
        if psutil.pid_exists(pid):
            continue

        candidates.append(db_file)

    if not candidates:
        return None

    # Pick the newest by modification time
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]
