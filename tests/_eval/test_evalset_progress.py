import logging

import pytest

from inspect_ai._eval.evalset import EvalSetScanProgress


class TestEvalSetScanProgress:
    def test_before_reading_logs_zero_files(self, caplog: pytest.LogCaptureFixture) -> None:
        """Zero files should produce no log output."""
        progress = EvalSetScanProgress("s3://bucket/logs")
        with caplog.at_level(logging.INFO):
            progress.before_reading_logs(0)
        assert len(caplog.records) == 0

    def test_before_reading_logs_many_files(self, caplog: pytest.LogCaptureFixture) -> None:
        """Many files should log initial count."""
        progress = EvalSetScanProgress("s3://bucket/logs")
        with caplog.at_level(logging.INFO):
            progress.before_reading_logs(500)
        assert "500 eval log files" in caplog.text
        assert "s3://bucket/logs" in caplog.text

    def test_progress_logging_interval(self, caplog: pytest.LogCaptureFixture) -> None:
        """Progress should log at intervals, not every file."""
        progress = EvalSetScanProgress("s3://bucket/logs")
        progress.before_reading_logs(1000)

        with caplog.at_level(logging.INFO):
            caplog.clear()
            for i in range(1000):
                progress.after_read_log(f"file_{i}.eval")

        progress_lines = [r for r in caplog.records if "Reading eval logs:" in r.message]
        assert len(progress_lines) == 10

    def test_progress_logging_small_set(self, caplog: pytest.LogCaptureFixture) -> None:
        """Small file sets should still log at reasonable intervals."""
        progress = EvalSetScanProgress("s3://bucket/logs")
        progress.before_reading_logs(50)

        with caplog.at_level(logging.INFO):
            caplog.clear()
            for i in range(50):
                progress.after_read_log(f"file_{i}.eval")

        progress_lines = [r for r in caplog.records if "Reading eval logs:" in r.message]
        assert len(progress_lines) == 1
        assert "50/50" in progress_lines[0].message

    def test_completion_summary(self, caplog: pytest.LogCaptureFixture) -> None:
        """Completion should log summary with timing."""
        progress = EvalSetScanProgress("s3://bucket/logs")
        progress.before_reading_logs(100)
        progress.completed = 100

        with caplog.at_level(logging.INFO):
            caplog.clear()
            progress.log_completion(completed_count=80, pending_count=20)

        assert "80 completed" in caplog.text
        assert "20 pending" in caplog.text
        assert "100 logs read" in caplog.text

    def test_completion_no_logs_when_zero_files(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Completion should not log if no files were scanned."""
        progress = EvalSetScanProgress("s3://bucket/logs")
        progress.before_reading_logs(0)

        with caplog.at_level(logging.INFO):
            caplog.clear()
            progress.log_completion(completed_count=0, pending_count=5)

        assert len(caplog.records) == 0

    def test_completion_no_logs_before_start(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Completion should not log if before_reading_logs was never called."""
        progress = EvalSetScanProgress("s3://bucket/logs")
        with caplog.at_level(logging.INFO):
            progress.log_completion(completed_count=80, pending_count=20)

        assert len(caplog.records) == 0
