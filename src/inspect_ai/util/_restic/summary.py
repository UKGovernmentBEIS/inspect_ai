"""Restic backup-summary model + parser."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ResticBackupSummary(BaseModel):
    """Last JSON line emitted by ``restic backup --json``.

    Field semantics mirror restic's documented summary output. Forward-
    compatible: unknown fields are tolerated (``extra="allow"``) so a
    future restic version that adds keys won't break parsing.
    """

    model_config = ConfigDict(extra="allow")

    message_type: Literal["summary"]
    dry_run: bool = False
    files_new: int
    files_changed: int
    files_unmodified: int
    dirs_new: int
    dirs_changed: int
    dirs_unmodified: int
    data_blobs: int
    tree_blobs: int
    data_added: int
    """Bytes added to the repo, *before* compression — i.e. the sum of
    uncompressed blob payloads."""

    data_added_packed: int
    """Bytes actually written to pack files on disk (after restic's
    per-blob compression). The disk-truthful "incremental size" of the
    snapshot."""

    total_files_processed: int
    total_bytes_processed: int
    backup_start: datetime
    backup_end: datetime
    total_duration: float
    snapshot_id: str
    """Omitted by restic only when snapshot creation was skipped (e.g.
    dry-run); always present for our writes."""


def _parse_summary(stdout: str) -> ResticBackupSummary:
    """Parse the last line of ``restic backup --json`` output as the summary.

    Restic emits one JSON object per line — periodic `status` messages
    followed by a final `summary`. The ``message_type: Literal["summary"]``
    field on the model means a non-summary last line raises ValidationError.
    """
    lines = stdout.strip().splitlines()
    if not lines:
        raise RuntimeError("restic backup produced no output")
    return ResticBackupSummary.model_validate_json(lines[-1])
