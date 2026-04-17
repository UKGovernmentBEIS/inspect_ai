"""Tests for retry log enrichment helpers."""

import logging
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from inspect_ai._util.constants import HTTP
from inspect_ai._util.retry import retry_error_summary, sample_context_prefix


@pytest.fixture(autouse=True)
def _ensure_log_propagation() -> Iterator[None]:
    """Counter init_logger() setting propagate=False on inspect_ai logger."""
    lgr = logging.getLogger("inspect_ai")
    old_propagate = lgr.propagate
    lgr.propagate = True
    yield
    lgr.propagate = old_propagate


def _make_mock_sample(
    *,
    uuid: str = "Abc12xY",
    task: str = "mmlu",
    sample_id: int | str | None = 42,
    epoch: int = 1,
    model: str = "openai/gpt-4o",
) -> MagicMock:
    """Create a mock ActiveSample with the given fields."""
    active = MagicMock()
    active.id = uuid
    active.task = task
    active.sample.id = sample_id
    active.epoch = epoch
    active.model = model
    return active


class TestSampleContextPrefix:
    def test_returns_prefix_with_active_sample(self) -> None:
        mock = _make_mock_sample()
        with patch("inspect_ai.log._samples.sample_active", return_value=mock):
            result = sample_context_prefix()
        assert result == "[Abc12xY mmlu/42/1 openai/gpt-4o] "

    def test_returns_empty_string_when_no_active_sample(self) -> None:
        with patch("inspect_ai.log._samples.sample_active", return_value=None):
            result = sample_context_prefix()
        assert result == ""

    def test_handles_string_sample_id(self) -> None:
        mock = _make_mock_sample(sample_id="q_123")
        with patch("inspect_ai.log._samples.sample_active", return_value=mock):
            result = sample_context_prefix()
        assert result == "[Abc12xY mmlu/q_123/1 openai/gpt-4o] "

    def test_handles_none_sample_id(self) -> None:
        mock = _make_mock_sample(sample_id=None)
        with patch("inspect_ai.log._samples.sample_active", return_value=mock):
            result = sample_context_prefix()
        assert result == "[Abc12xY mmlu/None/1 openai/gpt-4o] "


def _make_retry_state(exception: BaseException | None = None) -> MagicMock:
    """Create a mock RetryCallState with the given exception."""
    state = MagicMock()
    if exception is not None:
        state.outcome.exception.return_value = exception
    else:
        state.outcome = None
    return state


class TestRetryErrorSummary:
    def test_with_status_code_and_error_code(self) -> None:
        ex = Exception("rate limited")
        ex.status_code = 429  # type: ignore[attr-defined]
        ex.code = "rate_limit_exceeded"  # type: ignore[attr-defined]
        state = _make_retry_state(ex)
        assert retry_error_summary(state) == " [Exception 429 rate_limit_exceeded]"

    def test_with_status_code_only(self) -> None:
        ex = Exception("server error")
        ex.status_code = 503  # type: ignore[attr-defined]
        state = _make_retry_state(ex)
        assert retry_error_summary(state) == " [Exception 503]"

    def test_with_error_code_only(self) -> None:
        ex = Exception("bad")
        ex.code = "server_error"  # type: ignore[attr-defined]
        state = _make_retry_state(ex)
        assert retry_error_summary(state) == " [Exception server_error]"

    def test_with_status_on_response_object(self) -> None:
        """Some SDKs put status_code on ex.response, not ex directly."""
        ex = Exception("error")
        response = MagicMock()
        response.status_code = 502
        ex.response = response  # type: ignore[attr-defined]
        state = _make_retry_state(ex)
        assert retry_error_summary(state) == " [Exception 502]"

    def test_plain_exception(self) -> None:
        ex = ConnectionError("refused")
        state = _make_retry_state(ex)
        assert retry_error_summary(state) == " [ConnectionError]"

    def test_no_outcome(self) -> None:
        state = _make_retry_state(exception=None)
        assert retry_error_summary(state) == ""

    def test_outcome_with_no_exception(self) -> None:
        state = MagicMock()
        state.outcome.exception.return_value = None
        assert retry_error_summary(state) == ""

    def test_uses_specific_exception_class_name(self) -> None:
        """Verify we get 'TimeoutError' not 'Exception'."""
        ex = TimeoutError("timed out")
        state = _make_retry_state(ex)
        assert retry_error_summary(state) == " [TimeoutError]"


class TestLogModelRetry:
    def test_includes_sample_context_and_error_summary(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from inspect_ai.model._model import log_model_retry

        mock_sample = _make_mock_sample()
        ex = Exception("rate limited")
        ex.status_code = 429  # type: ignore[attr-defined]
        ex.code = "rate_limit_exceeded"  # type: ignore[attr-defined]
        state = _make_retry_state(ex)
        state.attempt_number = 2
        state.upcoming_sleep = 6.0

        with (
            caplog.at_level(HTTP),
            patch("inspect_ai.log._samples.sample_active", return_value=mock_sample),
        ):
            log_model_retry("openai/gpt-4o", state)

        assert len(caplog.records) == 1
        msg = caplog.records[0].message
        assert "[Abc12xY mmlu/42/1 openai/gpt-4o]" in msg
        assert "openai/gpt-4o retry 2" in msg
        assert "[Exception 429 rate_limit_exceeded]" in msg

    def test_no_sample_context_when_inactive(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from inspect_ai.model._model import log_model_retry

        state = _make_retry_state(ConnectionError("refused"))
        state.attempt_number = 1
        state.upcoming_sleep = 3.0

        with (
            caplog.at_level(HTTP),
            patch("inspect_ai.log._samples.sample_active", return_value=None),
        ):
            log_model_retry("openai/gpt-4o", state)

        assert len(caplog.records) == 1
        msg = caplog.records[0].message
        assert msg.startswith("-> openai/gpt-4o retry 1")
        assert "[ConnectionError]" in msg


class TestLogHttpxRetryAttempt:
    def test_includes_sample_context(self, caplog: pytest.LogCaptureFixture) -> None:
        from inspect_ai._util.httpx import log_httpx_retry_attempt

        mock_sample = _make_mock_sample()
        state = _make_retry_state(ConnectionError("refused"))
        state.attempt_number = 1
        state.upcoming_sleep = 3.0

        log_fn = log_httpx_retry_attempt("https://api.example.com/search")
        with (
            caplog.at_level(HTTP),
            patch("inspect_ai.log._samples.sample_active", return_value=mock_sample),
        ):
            log_fn(state)

        assert len(caplog.records) == 1
        msg = caplog.records[0].message
        assert "[Abc12xY mmlu/42/1 openai/gpt-4o]" in msg
        assert "https://api.example.com/search connection retry 1" in msg

    def test_no_prefix_when_no_sample(self, caplog: pytest.LogCaptureFixture) -> None:
        from inspect_ai._util.httpx import log_httpx_retry_attempt

        state = _make_retry_state(ConnectionError("refused"))
        state.attempt_number = 2
        state.upcoming_sleep = 6.0

        log_fn = log_httpx_retry_attempt("https://api.example.com/search")
        with (
            caplog.at_level(HTTP),
            patch("inspect_ai.log._samples.sample_active", return_value=None),
        ):
            log_fn(state)

        assert len(caplog.records) == 1
        msg = caplog.records[0].message
        assert msg.startswith("https://api.example.com/search connection retry 2")


class TestSampleContextFilter:
    def test_enriches_record_with_active_sample(self) -> None:
        from inspect_ai._util.retry import SampleContextFilter

        mock_sample = _make_mock_sample()
        filt = SampleContextFilter()
        record = logging.LogRecord(
            name="openai._base_client",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Retrying request to /responses in 0.4 seconds",
            args=None,
            exc_info=None,
        )
        with patch("inspect_ai.log._samples.sample_active", return_value=mock_sample):
            result = filt.filter(record)

        assert result is True
        assert record.getMessage().startswith("[Abc12xY mmlu/42/1 openai/gpt-4o]")
        assert "Retrying request to /responses" in record.getMessage()
        # Structured fields for JSON formatters
        assert record.sample_uuid == "Abc12xY"  # type: ignore[attr-defined]
        assert record.sample_task == "mmlu"  # type: ignore[attr-defined]
        assert record.sample_id == 42  # type: ignore[attr-defined]
        assert record.sample_epoch == 1  # type: ignore[attr-defined]
        assert record.sample_model == "openai/gpt-4o"  # type: ignore[attr-defined]

    def test_passes_through_when_no_active_sample(self) -> None:
        from inspect_ai._util.retry import SampleContextFilter

        filt = SampleContextFilter()
        record = logging.LogRecord(
            name="openai._base_client",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Retrying request to /responses in 0.4 seconds",
            args=None,
            exc_info=None,
        )
        with patch("inspect_ai.log._samples.sample_active", return_value=None):
            result = filt.filter(record)

        assert result is True
        assert record.getMessage() == "Retrying request to /responses in 0.4 seconds"
        assert not hasattr(record, "sample_uuid")

    def test_handles_format_args_in_msg(self) -> None:
        """The OpenAI SDK uses % formatting: log.info('Retrying request to %s in %f seconds', url, timeout)"""
        from inspect_ai._util.retry import SampleContextFilter

        mock_sample = _make_mock_sample()
        filt = SampleContextFilter()
        record = logging.LogRecord(
            name="openai._base_client",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Retrying request to %s in %f seconds",
            args=("/responses", 0.396765),
            exc_info=None,
        )
        with patch("inspect_ai.log._samples.sample_active", return_value=mock_sample):
            result = filt.filter(record)

        assert result is True
        full_msg = record.getMessage()
        assert "[Abc12xY mmlu/42/1 openai/gpt-4o]" in full_msg
        assert "/responses" in full_msg


class TestSampleContextFilterOnChildLogger:
    """Verify filter intercepts records from the actual SDK emitting logger.

    Python logging filters on a parent logger don't run for child logger
    records during propagation. The OpenAI SDK logs from 'openai._base_client',
    so the filter must be installed on the actual emitting logger, not 'openai'.
    """

    def test_filter_intercepts_child_logger_records(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import inspect_ai._util.retry as retry_module
        from inspect_ai._util.retry import (
            SampleContextFilter,
            install_sample_context_logging,
        )

        retry_module._sample_context_logging_installed = False
        for logger_name in ("openai", "openai._base_client"):
            lgr = logging.getLogger(logger_name)
            lgr.filters = [
                f for f in lgr.filters if not isinstance(f, SampleContextFilter)
            ]

        install_sample_context_logging()

        mock_sample = _make_mock_sample()
        child_logger = logging.getLogger("openai._base_client")

        with (
            caplog.at_level(logging.INFO),
            patch("inspect_ai.log._samples.sample_active", return_value=mock_sample),
        ):
            child_logger.info(
                "Retrying request to %s in %f seconds", "/responses", 0.396765
            )

        assert len(caplog.records) >= 1
        msg = caplog.records[-1].getMessage()
        assert "[Abc12xY mmlu/42/1 openai/gpt-4o]" in msg, (
            f"Filter did not intercept openai._base_client record. Got: {msg}"
        )

        for logger_name in ("openai", "openai._base_client"):
            lgr = logging.getLogger(logger_name)
            lgr.filters = [
                f for f in lgr.filters if not isinstance(f, SampleContextFilter)
            ]
        retry_module._sample_context_logging_installed = False


class TestRetryErrorSummaryEdgeCases:
    def test_integer_code_does_not_crash(self) -> None:
        ex = Exception("error")
        ex.code = 429  # type: ignore[attr-defined]
        state = _make_retry_state(ex)
        result = retry_error_summary(state)
        assert "429" in result

    def test_percent_in_task_name_does_not_break_formatting(self) -> None:
        mock = _make_mock_sample(task="100%_accuracy", sample_id="item%20foo")
        with patch("inspect_ai.log._samples.sample_active", return_value=mock):
            prefix = sample_context_prefix()
        assert "100%_accuracy" in prefix
        assert "item%20foo" in prefix


class TestInstallSampleContextLogging:
    def test_installs_filter_on_sdk_logger(self) -> None:
        import inspect_ai._util.retry as retry_module
        from inspect_ai._util.retry import (
            SampleContextFilter,
            install_sample_context_logging,
        )

        retry_module._sample_context_logging_installed = False

        sdk_logger = logging.getLogger("openai._base_client")
        sdk_logger.filters = [
            f for f in sdk_logger.filters if not isinstance(f, SampleContextFilter)
        ]
        original_count = len(sdk_logger.filters)

        install_sample_context_logging()

        assert len(sdk_logger.filters) == original_count + 1
        assert isinstance(sdk_logger.filters[-1], SampleContextFilter)

        sdk_logger.removeFilter(sdk_logger.filters[-1])
        retry_module._sample_context_logging_installed = False

    def test_is_idempotent(self) -> None:
        import inspect_ai._util.retry as retry_module
        from inspect_ai._util.retry import (
            SampleContextFilter,
            install_sample_context_logging,
        )

        retry_module._sample_context_logging_installed = False

        sdk_logger = logging.getLogger("openai._base_client")
        sdk_logger.filters = [
            f for f in sdk_logger.filters if not isinstance(f, SampleContextFilter)
        ]

        install_sample_context_logging()
        install_sample_context_logging()

        new_filters = [
            f for f in sdk_logger.filters if isinstance(f, SampleContextFilter)
        ]
        assert len(new_filters) == 1

        for f in new_filters:
            sdk_logger.removeFilter(f)
        retry_module._sample_context_logging_installed = False
