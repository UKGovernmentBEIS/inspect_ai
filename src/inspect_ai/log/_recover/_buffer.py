"""Read recovery data from the sample buffer database or filestore."""

import logging
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
from inspect_ai.log._recorders.buffer.filestore import SampleBufferFilestore
from inspect_ai.log._recorders.buffer.types import SampleBuffer

logger = logging.getLogger(__name__)


@dataclass
class BufferRecoveryData:
    """Recovery data extracted from a sample buffer database or filestore."""

    completed: list[EvalSampleSummary] = field(default_factory=list)
    """Samples that finished (scored) before the crash."""

    in_progress: list[EvalSampleSummary] = field(default_factory=list)
    """Samples that were still running when the crash happened."""

    buffer: SampleBuffer | None = None
    """Open buffer handle for per-sample event/attachment queries."""

    source: str = "database"
    """Recovery data source: "database" or "filestore"."""


def read_buffer_recovery_data(
    location: str, db_dir: str | Path | None = None
) -> BufferRecoveryData | None:
    """Read unflushed sample data from the buffer database or filestore.

    First tries the local SQLite buffer database. If none exists, falls
    back to the filestore (.buffer/ directory alongside the .eval file).

    Args:
        location: Path to the .eval log file.
        db_dir: Optional override for the buffer database directory.

    Returns:
        BufferRecoveryData with completed/in-progress samples and a buffer
        handle, or None if no recovery data exists.
    """
    # Try SQLite buffer database first
    result = _read_db_recovery_data(location, db_dir)
    if result is not None:
        return result

    # Fall back to filestore segments
    result = _read_filestore_recovery_data(location)
    if result is not None:
        logger.warning(
            "No local buffer database found. "
            f"Recovering from segment files for {location}."
        )
        return result

    return None


def _read_db_recovery_data(
    location: str, db_dir: str | Path | None = None
) -> BufferRecoveryData | None:
    """Try reading recovery data from the local SQLite buffer database."""
    db_path = _find_crashed_buffer_db(location, db_dir)
    if db_path is None:
        return None

    resolved_db_dir = db_path.parent.parent
    try:
        buffer = SampleBufferDatabase(location, create=False, db_dir=resolved_db_dir)
    except FileNotFoundError:
        return None
    buffer.db_path = db_path

    result = buffer.get_samples()
    if result is None or result == "NotModified":
        return BufferRecoveryData(buffer=buffer, source="database")

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
        source="database",
    )


def _read_filestore_recovery_data(location: str) -> BufferRecoveryData | None:
    """Try reading recovery data from the filestore (.buffer/ directory)."""
    try:
        filestore = SampleBufferFilestore(location, create=False)
    except Exception as ex:
        logger.debug(f"Could not open filestore for {location}: {ex}")
        return None

    manifest = filestore.read_manifest()
    if manifest is None:
        return None

    completed: list[EvalSampleSummary] = []
    in_progress: list[EvalSampleSummary] = []

    for sample_manifest in manifest.samples:
        summary = sample_manifest.summary
        if summary.completed_at is not None:
            completed.append(summary)
        else:
            in_progress.append(summary)

    return BufferRecoveryData(
        completed=completed,
        in_progress=in_progress,
        buffer=filestore,
        source="filestore",
    )


def _find_crashed_buffer_db(
    location: str, db_dir: str | Path | None = None
) -> Path | None:
    """Find the buffer DB for a crashed eval, filtering out live processes."""
    resolved_dir = resolve_db_dir(Path(db_dir) if db_dir is not None else None)
    uri = filesystem(location).path_as_uri(location)
    dir_hash, file = location_dir_and_file(uri)
    log_subdir = resolved_dir / dir_hash

    if not log_subdir.exists():
        return None

    candidates: list[Path] = []
    for db_file in log_subdir.glob(f"{file}.*.db"):
        parts = db_file.name.rsplit(".", 2)
        if len(parts) != 3:
            continue
        pid_str = parts[1]
        if not pid_str.isdigit():
            continue

        pid = int(pid_str)
        if psutil.pid_exists(pid):
            continue

        candidates.append(db_file)

    if not candidates:
        return None

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]
