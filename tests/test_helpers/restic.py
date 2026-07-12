"""Shared restic fixtures for tests."""

from __future__ import annotations

import json

# A restic-shaped snapshot id (64 hex chars), recognizable in assertions.
SUMMARY_SNAPSHOT_ID = "3a173af4" + "0" * 56


def restic_summary_json(**overrides: object) -> str:
    """A single-line ``restic backup --json`` ``summary`` message.

    Carries every field ``ResticBackupSummary`` requires (so ``from_stdout``
    parses it); keyword ``overrides`` replace individual fields. Returns the
    JSON text restic emits on its final stdout line, with or without
    ``--quiet`` (``--quiet`` drops only the preceding ``status`` lines, not
    the summary).
    """
    fields: dict[str, object] = {
        "message_type": "summary",
        "files_new": 8,
        "files_changed": 0,
        "files_unmodified": 0,
        "dirs_new": 2,
        "dirs_changed": 0,
        "dirs_unmodified": 0,
        "data_blobs": 40,
        "tree_blobs": 3,
        "data_added": 83893579,
        "data_added_packed": 83812345,
        "total_files_processed": 8,
        "total_bytes_processed": 83886080,
        "backup_start": "2026-06-30T12:00:00+00:00",
        "backup_end": "2026-06-30T12:00:03+00:00",
        "total_duration": 3.0,
        "snapshot_id": SUMMARY_SNAPSHOT_ID,
    }
    return json.dumps({**fields, **overrides})
