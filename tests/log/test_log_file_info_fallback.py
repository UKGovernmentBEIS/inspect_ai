"""Tests for log_file_info header fallback behavior.

Verifies that:
1. Native filenames (with ISO timestamp prefix) parse via fast path
2. Custom filenames fall back to reading header.json from the .eval ZIP
3. Corrupt/missing headers degrade gracefully
4. Results are deterministic
"""

import io
import json
import os
import zipfile

from inspect_ai._util.file import FileInfo
from inspect_ai.log._file import log_file_info


def _make_fileinfo(path: str, size: int = 1000) -> FileInfo:
    """Create a FileInfo object for a local file path."""
    return FileInfo(
        name=path,
        type="file",
        size=size,
        mtime=1710000000.0,
    )


def _make_eval_zip(path: str, header: dict) -> str:
    """Create a .eval ZIP file with a header.json entry.

    The header dict must contain the full schema that read_eval_log expects
    (version, status, eval, plan, results, stats sections). Use
    _make_full_header() to generate a valid template.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("header.json", json.dumps(header))
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return path


def _make_full_header(
    task: str = "test_task",
    task_id: str = "test_id",
    model: str = "test-model",
    **eval_overrides: object,
) -> dict:
    """Create a full header dict matching the schema read_eval_log expects.

    Based on the structure in tests/log/test_list_logs/custom.eval.
    """
    eval_section = {
        "run_id": "testrun123",
        "created": "2026-01-01T00:00:00+00:00",
        "task": task,
        "task_id": task_id,
        "task_version": 0,
        "task_file": "test.py",
        "task_attribs": {},
        "task_args": {},
        "dataset": {"samples": 1, "sample_ids": [1], "shuffled": False},
        "model": model,
        "model_args": {},
        "config": {"log_images": True},
        "packages": {"inspect_ai": "0.3.195"},
    }
    eval_section.update(eval_overrides)
    return {
        "version": 2,
        "status": "success",
        "eval": eval_section,
        "plan": {"name": "plan", "steps": [], "config": {}},
        "results": {
            "total_samples": 1,
            "completed_samples": 1,
            "scores": [],
        },
        "stats": {
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:00:01+00:00",
            "model_usage": {},
        },
    }


class TestLogFileInfoNativeParse:
    """Baseline regression tests: native Inspect filenames with timestamp prefix.

    These should PASS on both the current and modified code.
    """

    def test_standard_three_part_filename(self):
        """Native filename {timestamp}_{task}_{id}.eval parses correctly."""
        info = _make_fileinfo(
            "/logs/2026-03-15T11-51-45_g2a-simlex999_abc123.eval"
        )
        result = log_file_info(info)
        assert result.task == "g2a-simlex999"
        assert result.task_id == "abc123"

    def test_two_part_filename(self):
        """Native filename {timestamp}_{task}.eval parses with empty task_id."""
        info = _make_fileinfo("/logs/2026-03-15T11-51-45_mytask.eval")
        result = log_file_info(info)
        assert result.task == "mytask"
        assert result.task_id == ""

    def test_four_part_filename_with_model(self):
        """Legacy filename {timestamp}_{task}_{model}_{id}.eval parses correctly."""
        info = _make_fileinfo(
            "/logs/2026-03-15T11-51-45_mytask_mymodel_abc123.eval"
        )
        result = log_file_info(info)
        assert result.task == "mytask"
        assert result.task_id == "abc123"
