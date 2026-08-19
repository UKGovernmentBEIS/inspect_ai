"""Tests for retry log enrichment helpers."""

import logging
from typing import Any, Iterator, cast
from unittest.mock import MagicMock, patch

import anyio
import httpx
import pytest
from tenacity import RetryError

from inspect_ai._util.constants import HTTP
from inspect_ai._util.retry import (
    retry_error_summary,
    retry_error_type_status,
    sample_context_prefix,
)


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


class _GoogleAPIError(Exception):
    """Shaped like google-genai APIError: HTTP status in an int `code`."""

    def __init__(self, code: int) -> None:
        super().__init__("google error")
        self.code = code


class _OpenAIError(Exception):
    """Shaped like an OpenAI/Anthropic APIStatusError: `code` is a string slug."""

    def __init__(self, code: str) -> None:
        super().__init__("openai error")
        self.code = code


def _bedrock_error(status: int) -> Exception:
    """Bedrock ClientError: status only under ResponseMetadata.HTTPStatusCode."""
    from botocore.exceptions import ClientError

    return ClientError(
        error_response=cast(
            Any,
            {
                "Error": {"Code": "ThrottlingException", "Message": "x"},
                "ResponseMetadata": {"HTTPStatusCode": status},
            },
        ),
        operation_name="Converse",
    )


def _sagemaker_error(original_status: int) -> Exception:
    """SageMaker ClientError: classified on the top-level OriginalStatusCode.

    A ModelError is delivered as HTTP 424 regardless, so the envelope status is
    also present and must lose to OriginalStatusCode.
    """
    from botocore.exceptions import ClientError

    return ClientError(
        error_response=cast(
            Any,
            {
                "Error": {"Code": "ModelError", "Message": "x"},
                "OriginalStatusCode": original_status,
                "ResponseMetadata": {"HTTPStatusCode": 424},
            },
        ),
        operation_name="InvokeEndpoint",
    )


def _make_retry_error(cause: BaseException) -> RetryError:
    """A tenacity RetryError wrapping `cause` in __cause__, as chatapi produces."""
    err = RetryError(MagicMock())
    err.__cause__ = cause
    return err


def _httpx_status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


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

    def test_google_int_code_not_duplicated(self) -> None:
        # int `code` surfaces once as the status, not again as a code part
        assert (
            retry_error_summary(_make_retry_state(_GoogleAPIError(429)))
            == " [_GoogleAPIError 429]"
        )

    def test_retry_error_unwraps_cause(self) -> None:
        state = _make_retry_state(_make_retry_error(_httpx_status_error(503)))
        assert retry_error_summary(state) == " [HTTPStatusError 503]"

    def test_bedrock_client_error(self) -> None:
        state = _make_retry_state(_bedrock_error(429))
        assert retry_error_summary(state) == " [ClientError 429]"

    def test_sagemaker_container_timeout_omits_status(self) -> None:
        # 0 is not an HTTP status, so the summary carries the type alone
        state = _make_retry_state(_sagemaker_error(0))
        assert retry_error_summary(state) == " [ClientError]"

    def test_no_outcome(self) -> None:
        assert retry_error_summary(_make_retry_state(None)) == ""


class TestRetryErrorTypeStatus:
    def test_status_from_attr(self) -> None:
        ex = Exception("rate limited")
        ex.status_code = 429  # type: ignore[attr-defined]
        assert retry_error_type_status(_make_retry_state(ex)) == ("Exception", 429)

    def test_status_from_response(self) -> None:
        ex = Exception("error")
        ex.response = MagicMock(status_code=502)  # type: ignore[attr-defined]
        assert retry_error_type_status(_make_retry_state(ex)) == ("Exception", 502)

    def test_no_status(self) -> None:
        assert retry_error_type_status(
            _make_retry_state(ConnectionError("refused"))
        ) == ("ConnectionError", None)

    def test_google_int_code(self) -> None:
        # google-genai carries the HTTP status in an int `code`, no `status_code`
        assert retry_error_type_status(_make_retry_state(_GoogleAPIError(429))) == (
            "_GoogleAPIError",
            429,
        )

    def test_openai_string_code_not_status(self) -> None:
        # OpenAI/Anthropic `code` is a string slug and must not become the status
        assert retry_error_type_status(
            _make_retry_state(_OpenAIError("rate_limit_exceeded"))
        ) == ("_OpenAIError", None)

    def test_retry_error_unwraps_cause(self) -> None:
        # tenacity RetryError reports the cause's type and status, not the wrapper
        state = _make_retry_state(_make_retry_error(_httpx_status_error(503)))
        assert retry_error_type_status(state) == ("HTTPStatusError", 503)

    def test_bedrock_response_metadata_status(self) -> None:
        # botocore `response` is a mapping, so the attribute probe alone misses it
        assert retry_error_type_status(_make_retry_state(_bedrock_error(429))) == (
            "ClientError",
            429,
        )

    def test_sagemaker_original_status_code_wins(self) -> None:
        # OriginalStatusCode is what should_retry classifies on, so it beats the
        # generic 424 envelope status in ResponseMetadata
        assert retry_error_type_status(_make_retry_state(_sagemaker_error(503))) == (
            "ClientError",
            503,
        )

    def test_sagemaker_container_timeout_is_unknown(self) -> None:
        # OriginalStatusCode 0 means container timeout, not an HTTP status — it
        # must not be reported as one, nor fall back to the 424 envelope status
        assert retry_error_type_status(_make_retry_state(_sagemaker_error(0))) == (
            "ClientError",
            None,
        )

    def test_no_outcome(self) -> None:
        assert retry_error_type_status(_make_retry_state(None)) == (None, None)


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
            anyio.run(log_model_retry, "openai/gpt-4o", state)

        msg = caplog.records[0].message
        assert "[Abc12xY mmlu/42/1 openai/gpt-4o]" in msg
        assert "retry 2" in msg
        assert "[Exception 429]" in msg
