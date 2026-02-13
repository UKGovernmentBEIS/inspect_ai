"""Tests for retry log enrichment helpers."""

from unittest.mock import MagicMock, patch

import pytest

from inspect_ai._util.constants import HTTP
from inspect_ai._util.retry import retry_error_summary, sample_context_prefix


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
