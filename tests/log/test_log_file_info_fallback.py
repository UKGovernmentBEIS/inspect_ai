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
from inspect_ai.log._file import (
    log_file_info,
    log_file_info_async,
    log_files_from_ls_async,
)


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
        info = _make_fileinfo("/logs/2026-03-15T11-51-45_g2a-simlex999_abc123.eval")
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
        info = _make_fileinfo("/logs/2026-03-15T11-51-45_mytask_mymodel_abc123.eval")
        result = log_file_info(info)
        assert result.task == "mytask"
        assert result.task_id == "abc123"

    def test_prefixed_timestamp_filename(self, monkeypatch):
        """Bracket-prefixed timestamps (e.g. copied logs) skip the header read."""
        import inspect_ai.log._file as file_mod

        called = {"n": 0}

        def boom(name):
            called["n"] += 1
            return None, None, None

        monkeypatch.setattr(file_mod, "_try_read_header", boom)
        info = _make_fileinfo(
            "/logs/[ext] 2026-03-15T11-51-45+00-00_mytask_abc123.eval"
        )
        result = log_file_info(info)
        assert called["n"] == 0  # parsed from name, no header read
        assert result.task == "mytask"
        assert result.task_id == "abc123"


class TestLogFileInfoHeaderFallback:
    """Custom filenames (no ISO timestamp prefix) trigger header reading."""

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

    def test_embedded_timestamp_in_custom_name_uses_header(self, tmp_path):
        """A timestamp embedded mid-name must NOT be parsed as a native name.

        `backup-2025-...T..._results_x.eval` has an ISO timestamp after a "-"
        boundary inside the first segment. It must fall back to the header
        (task from the file), not silently take `results` from the filename.
        """
        header = _make_full_header(task="real_task", task_id="real_id")
        eval_path = tmp_path / "backup-2025-01-01T00-00-00_results_x.eval"
        _make_eval_zip(str(eval_path), header)

        info = _make_fileinfo(str(eval_path), size=os.path.getsize(eval_path))
        result = log_file_info(info)
        assert result.task == "real_task"
        assert result.task_id == "real_id"

    def test_hour_only_timestamp_not_native(self, tmp_path):
        """Truncated ISO prefix (YYYY-MM-DDTHH only) must not take the fast path."""
        header = _make_full_header(task="from_header", task_id="hdr_id")
        eval_path = tmp_path / "2026-01-01T00_custom.eval"
        _make_eval_zip(str(eval_path), header)

        info = _make_fileinfo(str(eval_path), size=os.path.getsize(eval_path))
        result = log_file_info(info)
        assert result.task == "from_header"
        assert result.task_id == "hdr_id"

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

    def test_header_info_cached_across_calls(self, tmp_path, monkeypatch):
        """Repeated listings reuse the cached header info for unchanged files."""
        import inspect_ai.log._file as file_mod

        file_mod._header_info_cache.clear()

        header = _make_full_header(task="cached_task", task_id="cached_id")
        eval_path = tmp_path / "cache_test.eval"
        _make_eval_zip(str(eval_path), header)

        calls = {"n": 0}
        orig = file_mod._try_read_header

        def counting(name):
            calls["n"] += 1
            return orig(name)

        monkeypatch.setattr(file_mod, "_try_read_header", counting)

        info = _make_fileinfo(str(eval_path), size=os.path.getsize(eval_path))
        r1 = log_file_info(info)
        r2 = log_file_info(info)
        assert calls["n"] == 1
        assert r1.task == r2.task == "cached_task"

        # changed mtime invalidates the cache entry
        info2 = FileInfo(
            name=info.name, type="file", size=info.size, mtime=info.mtime + 1
        )
        log_file_info(info2)
        assert calls["n"] == 2

    def test_etag_distinguishes_same_mtime_size_overwrite(self, monkeypatch):
        """A same-mtime, same-size overwrite with a new etag must re-read.

        On S3 (LastModified is 1s-resolution), a fixed path like `latest.eval`
        can be overwritten within one second by a different eval of the same
        byte size. Without the etag in the key the stale task would be served
        for the process lifetime; the etag is a content validator.
        """
        import inspect_ai.log._file as file_mod

        file_mod._header_info_cache.clear()

        calls = {"n": 0}

        def fake_read(name):
            calls["n"] += 1
            return f"task{calls['n']}", f"id{calls['n']}", None

        monkeypatch.setattr(file_mod, "_try_read_header", fake_read)

        base = dict(
            name="s3://bucket/latest.eval",
            type="file",
            size=1000,
            mtime=1710000000.0,
        )
        r1 = log_file_info(FileInfo(**base, etag="etag-aaa"))
        assert r1.task == "task1"

        # new content (new etag), identical name/mtime/size -> must re-read
        r2 = log_file_info(FileInfo(**base, etag="etag-bbb"))
        assert calls["n"] == 2
        assert r2.task == "task2"

        # unchanged etag -> cache hit, no further read
        r3 = log_file_info(FileInfo(**base, etag="etag-bbb"))
        assert calls["n"] == 2
        assert r3.task == "task2"

    def test_cache_evicts_oldest_instead_of_full_wipe(self, monkeypatch):
        """Exceeding the cap evicts only the oldest entry, not the whole cache.

        A full wipe at the cap makes a directory larger than the cap re-read
        every header on every listing (thundering herd); FIFO eviction keeps
        the most-recent entries warm and still serving hits.
        """
        import inspect_ai.log._file as file_mod

        file_mod._header_info_cache.clear()
        monkeypatch.setattr(file_mod, "_HEADER_INFO_CACHE_MAX", 3)

        reads = {"n": 0}

        def counting(name):
            reads["n"] += 1
            return "t", "i", None

        monkeypatch.setattr(file_mod, "_try_read_header", counting)

        def info(i):
            return FileInfo(name=f"/x/f{i}.eval", type="file", size=1, mtime=float(i))

        for i in range(3):
            log_file_info(info(i))
        assert len(file_mod._header_info_cache) == 3
        assert reads["n"] == 3

        # one more past the cap: oldest (f0) evicted, cache stays bounded
        log_file_info(info(3))
        assert len(file_mod._header_info_cache) == 3
        assert reads["n"] == 4
        names = [key[0] for key in file_mod._header_info_cache]
        assert "/x/f0.eval" not in names
        assert "/x/f3.eval" in names

        # the surviving recent entry still serves a hit (no re-read) ...
        log_file_info(info(3))
        assert reads["n"] == 4
        # ... while the evicted entry must be re-read
        log_file_info(info(0))
        assert reads["n"] == 5

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
        native_header = _make_full_header(task="native_task", task_id="nativeid")
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


class TestLogFileInfoAsync:
    """Async variants: same behavior, no event-loop blocking on header reads."""

    async def test_async_native_filename_skips_io(self):
        info = _make_fileinfo("/logs/2026-03-15T11-51-45_g2a-simlex999_abc123.eval")
        result = await log_file_info_async(info)
        assert result.task == "g2a-simlex999"
        assert result.task_id == "abc123"

    async def test_async_custom_filename_reads_header(self, tmp_path):
        header = _make_full_header(task="async_task", task_id="async_id")
        eval_path = tmp_path / "no_timestamp_here.eval"
        _make_eval_zip(str(eval_path), header)

        info = _make_fileinfo(str(eval_path), size=os.path.getsize(eval_path))
        result = await log_file_info_async(info)
        assert result.task == "async_task"
        assert result.task_id == "async_id"

    async def test_async_corrupt_degrades_gracefully(self, tmp_path):
        bad_path = tmp_path / "bad_async.eval"
        bad_path.write_bytes(b"this is not a zip file")

        info = _make_fileinfo(str(bad_path), size=22)
        result = await log_file_info_async(info)
        assert result.task == ""
        assert result.task_id == ""


class TestListEvalLogsAsyncIntegration:
    """list_eval_logs_async resolves custom filenames via async header fan-out."""

    async def test_mixed_filenames_async(self, tmp_path):
        from inspect_ai._util.file import filesystem

        native_header = _make_full_header(task="n_task", task_id="n_id")
        _make_eval_zip(
            str(tmp_path / "2026-01-01T00-00-00_nativetask_nativeid.eval"),
            native_header,
        )
        custom_header = _make_full_header(task="c_task", task_id="c_id")
        _make_eval_zip(str(tmp_path / "my_custom_async.eval"), custom_header)

        fs = filesystem(str(tmp_path))
        ls = fs.ls(str(tmp_path), recursive=False)
        logs = await log_files_from_ls_async(ls)
        assert len(logs) == 2

        by_name = {os.path.basename(log.name): log for log in logs}
        native = by_name["2026-01-01T00-00-00_nativetask_nativeid.eval"]
        assert native.task == "nativetask"
        assert native.task_id == "nativeid"
        custom = by_name["my_custom_async.eval"]
        assert custom.task == "c_task"
        assert custom.task_id == "c_id"

    async def test_list_eval_logs_async_local_custom_filename(self, tmp_path):
        """Local FS path (sync filesystem) still resolves custom filenames.

        Important under trio: the previous sync fallback hit read_eval_log which
        refuses to run under trio, so custom-named local files silently lost
        their task name. The new async path bypasses that.
        """
        from inspect_ai._view.common import list_eval_logs_async

        header = _make_full_header(task="local_task", task_id="local_id")
        _make_eval_zip(str(tmp_path / "no_timestamp.eval"), header)

        logs = await list_eval_logs_async(str(tmp_path), recursive=False)
        assert len(logs) == 1
        assert logs[0].task == "local_task"
        assert logs[0].task_id == "local_id"
