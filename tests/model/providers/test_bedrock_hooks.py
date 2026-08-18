"""Tests for Bedrock ConverseHooks per-attempt retry classification.

Verifies that the hook chain works end-to-end against a *real* AWSRequest /
context dict — the previous implementation silently no-op'd because
AWSPreparedRequest has no `.context` attribute, and `getattr` returned None
without surfacing any error. These tests catch that class of regression.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from botocore.awsrequest import AWSRequest  # noqa: E402

from inspect_ai.model._providers.util.hooks import ConverseHooks  # noqa: E402


def _make_hooks() -> ConverseHooks:
    """Build a ConverseHooks instance without registering with a real session."""
    # The constructor expects a session-like object with `_session.register`,
    # but we bypass it for unit testing.
    hooks = ConverseHooks.__new__(ConverseHooks)
    # call HttpHooks.__init__ to set up self._requests
    hooks._requests = {}
    return hooks


def _make_aws_request(user_agent: str) -> AWSRequest:
    """Build an AWSRequest with a User-Agent header and an empty per-call context."""
    return AWSRequest(
        method="POST",
        url="https://bedrock.example.com/model/x/converse",
        headers={"User-Agent": user_agent},
        data=b"",
    )


def test_request_created_stashes_request_id_on_context() -> None:
    """request-created handler must put the Inspect request_id on AWSRequest.context.

    AWSRequest.context IS the same dict botocore threads through to
    response-received as the `context` parameter, so this is the only
    durable channel between the two events.
    """
    hooks = _make_hooks()
    request_id = hooks.start_request()
    request = _make_aws_request(f"botocore/x.y ins/rid#{request_id}")
    hooks.converse_request_created(request=request)
    # the per-call context dict now carries our request_id
    assert request.context.get(ConverseHooks._CTX_REQUEST_ID) == request_id


def test_request_created_increments_attempts() -> None:
    hooks = _make_hooks()
    request_id = hooks.start_request()
    request = _make_aws_request(f"ins/rid#{request_id}")
    # Patch report_http_retry: the second converse_request_created call would
    # otherwise call the real one and pollute the _request_had_retry ContextVar
    # for any subsequent tests in the same process.
    with patch("inspect_ai.model._providers.util.hooks.report_http_retry"):
        hooks.converse_request_created(request=request)
        assert hooks._requests[request_id].attempts == 1
        hooks.converse_request_created(request=request)
        assert hooks._requests[request_id].attempts == 2


def test_response_received_records_status_via_context() -> None:
    """The full chain: request-created stashes id → response-received reads id from context."""
    hooks = _make_hooks()
    request_id = hooks.start_request()
    request = _make_aws_request(f"ins/rid#{request_id}")
    with patch("inspect_ai.model._providers.util.hooks.report_http_retry"):
        hooks.converse_request_created(request=request)
        # response arrives — context is the SAME dict as request.context
        hooks.converse_response_received(
            response_dict={"status_code": 429, "headers": {}, "url": ""},
            context=request.context,
        )
        info = hooks._requests[request_id]
        assert info.last_status == 429


def test_throttle_then_retry_classifies_as_rate_limit() -> None:
    """End-to-end: 429 response → next request-created reports rate_limit retry.

    This is the scenario the reviewer flagged: SDK-internal retries on
    ThrottlingException must reach the adaptive controller, not be silently
    classified as transient (or dropped entirely because request_id was None).
    """
    hooks = _make_hooks()
    request_id = hooks.start_request()
    request = _make_aws_request(f"ins/rid#{request_id}")

    # Attempt 1 — fires request-created, then response-received with 429
    hooks.converse_request_created(request=request)
    hooks.converse_response_received(
        response_dict={"status_code": 429, "headers": {}, "url": ""},
        context=request.context,
    )

    # Attempt 2 — request-created fires again (botocore creates a new request
    # per retry, but the context dict is the same identity)
    new_request = _make_aws_request(f"ins/rid#{request_id}")
    new_request.context = request.context  # botocore reuses the same context
    with patch(
        "inspect_ai.model._providers.util.hooks.report_http_retry"
    ) as mock_report:
        hooks.converse_request_created(request=new_request)
    # report_http_retry must have been called with kind="rate_limit"
    assert mock_report.called
    call_kwargs = mock_report.call_args.kwargs
    assert call_kwargs.get("kind") == "rate_limit"


def test_throttling_exception_classified_via_parsed_response() -> None:
    """ThrottlingException detected via parsed_response.Error.Code, not status.

    ThrottlingException doesn't always come back as HTTP 429 from Bedrock.
    """
    hooks = _make_hooks()
    request_id = hooks.start_request()
    request = _make_aws_request(f"ins/rid#{request_id}")

    # Attempt 1 — request-created stashes id; response-received sees a non-429
    # status but a ThrottlingException error code in parsed_response
    with patch("inspect_ai.model._providers.util.hooks.report_http_retry"):
        hooks.converse_request_created(request=request)
    hooks.converse_response_received(
        response_dict={"status_code": 400, "headers": {}, "url": ""},
        parsed_response={"Error": {"Code": "ThrottlingException", "Message": "x"}},
        context=request.context,
    )

    # Attempt 2 — fires retry. Should be classified as rate_limit because the
    # parsed_response.Error.Code was ThrottlingException, even though HTTP
    # status was 400 (not 429).
    new_request = _make_aws_request(f"ins/rid#{request_id}")
    new_request.context = request.context
    with patch(
        "inspect_ai.model._providers.util.hooks.report_http_retry"
    ) as mock_report:
        hooks.converse_request_created(request=new_request)
    assert mock_report.called
    assert mock_report.call_args.kwargs.get("kind") == "rate_limit"


def test_validation_exception_classified_as_transient() -> None:
    """An explicit non-throttle AWS error code wins over status-based inference.

    Without this, a 429 body with a non-throttle Code (e.g. ValidationException)
    would be misclassified as rate_limit by the status-based fallback.
    """
    hooks = _make_hooks()
    request_id = hooks.start_request()
    request = _make_aws_request(f"ins/rid#{request_id}")

    with patch("inspect_ai.model._providers.util.hooks.report_http_retry"):
        hooks.converse_request_created(request=request)
    hooks.converse_response_received(
        response_dict={"status_code": 429, "headers": {}, "url": ""},
        parsed_response={"Error": {"Code": "ValidationException", "Message": "x"}},
        context=request.context,
    )

    new_request = _make_aws_request(f"ins/rid#{request_id}")
    new_request.context = request.context
    with patch(
        "inspect_ai.model._providers.util.hooks.report_http_retry"
    ) as mock_report:
        hooks.converse_request_created(request=new_request)
    # Even though HTTP was 429, the explicit "ValidationException" code
    # routes us to transient.
    assert mock_report.called
    assert mock_report.call_args.kwargs.get("kind") != "rate_limit"


def test_5xx_then_retry_classifies_as_transient() -> None:
    """5xx response should NOT scale the controller down on the next retry."""
    hooks = _make_hooks()
    request_id = hooks.start_request()
    request = _make_aws_request(f"ins/rid#{request_id}")

    hooks.converse_request_created(request=request)
    hooks.converse_response_received(
        response_dict={"status_code": 503, "headers": {}, "url": ""},
        context=request.context,
    )

    new_request = _make_aws_request(f"ins/rid#{request_id}")
    new_request.context = request.context
    with patch(
        "inspect_ai.model._providers.util.hooks.report_http_retry"
    ) as mock_report:
        hooks.converse_request_created(request=new_request)
    # transient: report_http_retry called with no kwargs (defaults to transient)
    assert mock_report.called
    assert mock_report.call_args.kwargs.get("kind") != "rate_limit"


def test_response_without_stashed_id_is_noop() -> None:
    """If the User-Agent didn't carry our marker, response-received does nothing."""
    hooks = _make_hooks()
    # response-received with an empty context — no _inspect_request_id
    hooks.converse_response_received(
        response_dict={"status_code": 429, "headers": {}, "url": ""},
        context={},
    )
    # nothing recorded
    assert hooks._requests == {}


def test_user_agent_without_marker_is_noop() -> None:
    """A request without our User-Agent marker shouldn't crash or create state."""
    hooks = _make_hooks()
    request = _make_aws_request("botocore/1.40.61 Python/3.13")
    hooks.converse_request_created(request=request)
    # no request_id was extracted, nothing tracked
    assert hooks._requests == {}
    assert ConverseHooks._CTX_REQUEST_ID not in request.context


def test_ignores_calls_without_request_kwarg() -> None:
    hooks = _make_hooks()
    # botocore may emit other events with different kwargs — handler must
    # tolerate absence of `request`
    hooks.converse_request_created()  # no kwargs at all
    hooks.converse_request_created(operation_name="Converse")  # no request
    assert hooks._requests == {}


def test_retry_after_deadline_decays_across_sdk_backoff() -> None:
    """Retry-After is reported as *remaining* time, not the original duration.

    If the response says Retry-After: 30, then 30s of SDK-internal backoff
    elapses, the next retry should report ~0 remaining (not 30 again — that
    would double-count, the controller would extend its cooldown by another
    30s for a total of 60s wait). Reproduce by manually advancing the
    recorded deadline backwards.
    """
    import time

    from inspect_ai.model._providers.util.hooks import (
        ConverseHooks,
        RequestInfo,
    )

    hooks = _make_hooks()
    request_id = hooks.start_request()
    request = _make_aws_request(f"ins/rid#{request_id}")

    # Attempt 1 — record a response with Retry-After: 30
    with patch("inspect_ai.model._providers.util.hooks.report_http_retry"):
        hooks.converse_request_created(request=request)
    hooks.converse_response_received(
        response_dict={
            "status_code": 429,
            "headers": {"retry-after": "30"},
            "url": "",
        },
        context=request.context,
    )

    # The deadline stored in RequestInfo should be ~30s in the future
    info = hooks._requests[request_id]
    assert info.last_retry_after_deadline is not None
    assert (info.last_retry_after_deadline - time.monotonic()) > 25

    # Simulate SDK-internal backoff: pretend 30s have elapsed by rewinding
    # the deadline (any time past it should report 0 remaining).
    hooks._requests[request_id] = RequestInfo(
        info.attempts,
        info.last_request,
        info.last_status,
        time.monotonic() - 1,  # deadline is in the past
        info.last_kind,
    )

    new_request = _make_aws_request(f"ins/rid#{request_id}")
    new_request.context = request.context
    with patch(
        "inspect_ai.model._providers.util.hooks.report_http_retry"
    ) as mock_report:
        hooks.converse_request_created(request=new_request)
    # report_http_retry should fire with retry_after=None (deadline already
    # past — no remaining wait to suggest). NOT 30s.
    assert mock_report.called
    kwargs = mock_report.call_args.kwargs
    assert kwargs.get("retry_after") is None

    # And specifically, kind should still be rate_limit (status=429)
    assert kwargs.get("kind") == "rate_limit"
    # Silence unused import warning if test infrastructure trimmed it
    _ = ConverseHooks
