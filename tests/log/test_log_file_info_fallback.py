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


class TestLogFileInfoHeaderFallback:
    """TDD Red Phase: tests for the fallback path.

    Custom filenames (no ISO timestamp prefix) should trigger header reading.
    These tests FAIL on current code and PASS after implementation.
    """

    def test_custom_filename_reads_header(self, tmp_path):
        """Non-standard filename triggers header.json read for task/task_id."""
        header = _make_full_header(
            task="g2a_simlex999",
            task_id="g2a_simlex999_2026-03-15T11:50:37",
            model="intfloat/e5-small-v2",
        )
        eval_path = tmp_path / "hf_e5_small_g2a.eval"
        _make_eval_zip(str(eval_path), header)

        info = _make_fileinfo(str(eval_path), size=os.path.getsize(eval_path))
        result = log_file_info(info)
        assert result.task == "g2a_simlex999"
        assert result.task_id == "g2a_simlex999_2026-03-15T11:50:37"

    def test_numeric_prefix_not_timestamp(self, tmp_path):
        """Filename starting with digits but not ISO timestamp triggers fallback."""
        header = _make_full_header(task="numeric_test", task_id="num_id")
        eval_path = tmp_path / "2026_custom_eval.eval"
        _make_eval_zip(str(eval_path), header)

        info = _make_fileinfo(str(eval_path), size=os.path.getsize(eval_path))
        result = log_file_info(info)
        assert result.task == "numeric_test"
        assert result.task_id == "num_id"

    def test_corrupt_file_degrades_gracefully(self, tmp_path):
        """Non-ZIP file with custom name returns empty task, no exception."""
        bad_path = tmp_path / "bad_name.eval"
        bad_path.write_bytes(b"this is not a zip file")

        info = _make_fileinfo(str(bad_path), size=22)
        result = log_file_info(info)
        assert result.task == ""
        assert result.task_id == ""

    def test_partial_header_missing_task_id(self, tmp_path):
        """Header with task but omitting task_id returns Pydantic default ("")."""
        # Build full header but remove task_id so Pydantic uses default
        header = _make_full_header(task="onlytask")
        del header["eval"]["task_id"]
        eval_path = tmp_path / "partial_header.eval"
        _make_eval_zip(str(eval_path), header)

        info = _make_fileinfo(str(eval_path), size=os.path.getsize(eval_path))
        result = log_file_info(info)
        assert result.task == "onlytask"
        # EvalSpec.task_id has Field(default_factory=str) -> defaults to ""
        assert result.task_id == ""

    def test_determinism(self, tmp_path):
        """Calling log_file_info twice on same file returns identical results."""
        header = _make_full_header(task="det_test", task_id="det_id")
        eval_path = tmp_path / "determinism_test.eval"
        _make_eval_zip(str(eval_path), header)

        info = _make_fileinfo(str(eval_path), size=os.path.getsize(eval_path))
        result1 = log_file_info(info)
        result2 = log_file_info(info)
        assert result1.task == result2.task
        assert result1.task_id == result2.task_id


class TestListEvalLogsIntegration:
    """Integration tests verifying log_file_info works through list_eval_logs."""

    def test_mixed_filenames_all_resolve(self, tmp_path):
        """list_eval_logs returns correct task for both native and custom names."""
        from inspect_ai.log import list_eval_logs

        # Create a native-named eval (timestamp prefix -> fast path)
        native_header = _make_full_header(
            task="native_task", task_id="nativeid"
        )
        _make_eval_zip(
            str(tmp_path / "2026-01-01T00-00-00_nativetask_nativeid.eval"),
            native_header,
        )

        # Create a custom-named eval (no timestamp -> header fallback)
        custom_header = _make_full_header(
            task="custom_task", task_id="custom_id", model="custom-model"
        )
        _make_eval_zip(
            str(tmp_path / "my_custom_eval.eval"),
            custom_header,
        )

        logs = list_eval_logs(str(tmp_path), recursive=False)
        assert len(logs) == 2

        by_name = {os.path.basename(log.name): log for log in logs}

        native = by_name["2026-01-01T00-00-00_nativetask_nativeid.eval"]
        assert native.task == "nativetask"
        assert native.task_id == "nativeid"

        custom = by_name["my_custom_eval.eval"]
        assert custom.task == "custom_task"
        assert custom.task_id == "custom_id"
