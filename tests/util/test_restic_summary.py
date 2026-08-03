"""Tests for ``ResticBackupSummary.from_stdout`` (last-line summary parsing).

``restic backup --json`` emits one JSON object per line: periodic ``status``
messages then a final ``summary``. ``from_stdout`` parses only the last line,
so it must select the summary regardless of any preceding lines (the
non-quiet case) and fail loudly on empty output.
"""

from __future__ import annotations

import json

import pytest
from test_helpers.restic import SUMMARY_SNAPSHOT_ID, restic_summary_json

from inspect_ai.util._restic import ResticBackupSummary


def test_from_stdout_parses_summary_line() -> None:
    summary = ResticBackupSummary.from_stdout(restic_summary_json())
    assert summary.snapshot_id == SUMMARY_SNAPSHOT_ID
    assert summary.files_new == 8


def test_from_stdout_ignores_leading_status_lines() -> None:
    """Non-quiet output: ``status`` lines precede the summary; only the last counts."""
    status = json.dumps({"message_type": "status", "percent_done": 0.5})
    stdout = "\n".join([status, status, restic_summary_json()])
    assert ResticBackupSummary.from_stdout(stdout).snapshot_id == SUMMARY_SNAPSHOT_ID


def test_from_stdout_empty_raises() -> None:
    with pytest.raises(RuntimeError, match="no output"):
        ResticBackupSummary.from_stdout("   \n  ")
