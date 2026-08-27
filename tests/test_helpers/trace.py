"""Shared helpers for writing trace-log fixture files.

One home for the trace-record fixture format used by both the `inspect
trace` CLI tests and the `inspect ctl process anomalies` tests, so the
fixture shape can't drift between the two suites that exercise the shared
reconstruction.
"""

import json
from pathlib import Path
from typing import Any


def write_trace_log(file: Path, records: list[dict[str, Any]]) -> None:
    """Write records to `file` in the JSON-lines format `read_trace_file` reads."""
    with open(file, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def action_record(
    trace_id: str,
    action: str,
    event: str,
    *,
    detail: str = "",
    start_time: float | None = None,
    duration: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """One TRACE-level action record as it appears on disk (`ActionTraceRecord`)."""
    record: dict[str, Any] = {
        "timestamp": "2026-07-16T12:00:00+00:00",
        "level": "TRACE",
        "message": f"{action}: {detail} ({event})",
        "action": action,
        "detail": detail,
        "event": event,
        "trace_id": trace_id,
    }
    if start_time is not None:
        record["start_time"] = start_time
    if duration is not None:
        record["duration"] = duration
    if error is not None:
        record["error"] = error
    return record
