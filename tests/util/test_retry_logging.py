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
    active = MagicMock()
    active.id = uuid
    active.task = task
    active.sample.id = sample_id
    active.epoch = epoch
    active.model = model
    return active


def _make_retry_state(exception: BaseException | None = None) -> MagicMock:
    state = MagicMock()
    if exception is not None:
        state.outcome.exception.return_value = exception
    else:
        state.outcome = None
    return state


class TestSampleContextPrefix:
    def test_with_active_sample(self) -> None:
        mock = _make_mock_sample()
        with patch("inspect_ai.log._samples.sample_active", return_value=mock):
            assert sample_context_prefix() == "[Abc12xY mmlu/42/1 openai/gpt-4o] "

    def test_no_active_sample(self) -> None:
        with patch("inspect_ai.log._samples.sample_active", return_value=None):
            assert sample_context_prefix() == ""


class TestRetryErrorSummary:
    def test_status_and_code(self) -> None:
        ex = Exception("rate limited")
        ex.status_code = 429  # type: ignore[attr-defined]
        ex.code = "rate_limit_exceeded"  # type: ignore[attr-defined]
        assert (
            retry_error_summary(_make_retry_state(ex))
            == " [Exception 429 rate_limit_exceeded]"
        )

    def test_status_on_response(self) -> None:
        ex = Exception("error")
        ex.response = MagicMock(status_code=502)  # type: ignore[attr-defined]
        assert retry_error_summary(_make_retry_state(ex)) == " [Exception 502]"

    def test_plain_exception(self) -> None:
        assert (
            retry_error_summary(_make_retry_state(ConnectionError("refused")))
            == " [ConnectionError]"
        )

    def test_no_outcome(self) -> None:
        assert retry_error_summary(_make_retry_state(None)) == ""


class TestLogModelRetry:
    def test_includes_context_and_error(self, caplog: pytest.LogCaptureFixture) -> None:
        from inspect_ai.model._model import log_model_retry

        mock_sample = _make_mock_sample()
        ex = Exception("rate limited")
        ex.status_code = 429  # type: ignore[attr-defined]
        state = _make_retry_state(ex)
        state.attempt_number = 2
        state.upcoming_sleep = 6.0

        with (
            caplog.at_level(HTTP),
            patch("inspect_ai.log._samples.sample_active", return_value=mock_sample),
        ):
            log_model_retry("openai/gpt-4o", state)

        msg = caplog.records[0].message
        assert "[Abc12xY mmlu/42/1 openai/gpt-4o]" in msg
        assert "retry 2" in msg
        assert "[Exception 429]" in msg
