"""Tests for chat_api_request retry reporting via tenacity before_sleep.

The fix moves `report_http_retry` from the tenacity *predicate* (which fires
on every attempt, including the final stopped one) to a `before_sleep`
callback (which fires only on retries that actually sleep). This eliminates
the chatapi-specific 3× inflation of `_http_retries_count` while still
surfacing inner-retry-success cases (which were invisible in main).
"""

import contextlib
from collections.abc import Iterator

import httpx
import pytest

from inspect_ai._util import retry as retry_module
from inspect_ai._util.retry import http_retries_count
from inspect_ai.model._providers.util.chatapi import chat_api_request


@contextlib.contextmanager
def _reset_retry_counter() -> Iterator[int]:
    """Snapshot + restore the global retry counter so tests are isolated."""
    before = retry_module._http_retries_count
    yield before
    retry_module._http_retries_count = before


def _client_with_responses(responses: list[httpx.Response]) -> httpx.AsyncClient:
    """Build an AsyncClient whose POSTs return the given responses in order."""
    iter_responses = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        try:
            return next(iter_responses)
        except StopIteration:
            raise AssertionError(
                "test made more requests than mocked responses"
            ) from None

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


@pytest.mark.anyio
async def test_chatapi_429_then_success_reports_one_retry() -> None:
    """One actual retry happened (between attempts 1 and 2). Counter += 1."""
    responses = [
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"ok": True}),
    ]
    client = _client_with_responses(responses)
    with _reset_retry_counter() as before:
        result = await chat_api_request(
            client,
            model_name="test-model",
            url="https://example.invalid/v1/chat",
            headers={},
            json={"input": "hello"},
        )
        assert result == {"ok": True}
        assert http_retries_count() == before + 1
    await client.aclose()


@pytest.mark.anyio
async def test_chatapi_429_then_429_stop_reports_one_inner_retry() -> None:
    """Two failed attempts; only one ACTUAL retry (between 1 and 2). Inner += 1.

    The outer Model.should_retry would add its own report when the wrapping
    RetryError bubbles up, but that's tested separately at the Model layer.
    Inside the chatapi unit, only the inner-attempt-1→2 retry is counted.
    """
    from tenacity import RetryError

    responses = [
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(429, headers={"Retry-After": "1"}),
    ]
    client = _client_with_responses(responses)
    with _reset_retry_counter() as before:
        with pytest.raises(RetryError):
            await chat_api_request(
                client,
                model_name="test-model",
                url="https://example.invalid/v1/chat",
                headers={},
                json={"input": "hello"},
            )
        # Exactly one inner report — for the sleep between attempts 1 and 2.
        # The final stopped attempt does NOT call before_sleep.
        assert http_retries_count() == before + 1
    await client.aclose()


@pytest.mark.anyio
async def test_chatapi_retry_attributes_qualified_model() -> None:
    """A chatapi-internal 429 lands in the right model's throughput bucket.

    The chatapi before_sleep is the sole reporter for chatapi-internal
    retries, so a forced 429 must reach the throughput registry (keyed by
    the qualified name, not the bare one) — and exactly once (no
    double-count through the sub-layer).
    """
    from inspect_ai.model._throughput import init_model_throughput, throughput_view

    init_model_throughput()
    try:
        responses = [
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(200, json={"ok": True}),
        ]
        client = _client_with_responses(responses)
        with _reset_retry_counter():
            await chat_api_request(
                client,
                model_name="test-model",
                url="https://example.invalid/v1/chat",
                headers={},
                json={"input": "hello"},
                qualified_model_name="together/test-model",
            )
        view = throughput_view("together/test-model")
        assert view is not None
        assert view.retries_rate_limit == 1
        assert view.retries_transient == 0
        # the inner loop's scheduled sleep feeds the model's backoff too
        # (it is invisible to the outer retry loop's on_before_sleep); the
        # autouse fast_retry_waits fixture zeroes the wait, so assert on the
        # appended interval rather than a nonzero duration
        from inspect_ai.model._throughput import _registry

        assert len(_registry["together/test-model"].backoff_intervals) == 1
        # keyed by the qualified name only — no bare-name row
        assert throughput_view("test-model") is None
        await client.aclose()
    finally:
        init_model_throughput()


@pytest.mark.anyio
async def test_chatapi_no_retry_on_400() -> None:
    """A non-retryable status doesn't retry and doesn't report."""
    responses = [httpx.Response(400, json={"error": "bad request"})]
    client = _client_with_responses(responses)
    with _reset_retry_counter() as before:
        with pytest.raises(httpx.HTTPStatusError):
            await chat_api_request(
                client,
                model_name="test-model",
                url="https://example.invalid/v1/chat",
                headers={},
                json={"input": "hello"},
            )
        assert http_retries_count() == before
    await client.aclose()


@pytest.mark.anyio
async def test_chatapi_429_signals_active_controller_with_rate_limit_kind() -> None:
    """End-to-end: before_sleep → report_http_retry → controller.notify_retry.

    Verifies the chatapi inner retry actually reaches the adaptive controller
    with kind="rate_limit" and the parsed retry_after — not just that the
    counter increments. This is the integration the fix was designed to
    preserve when moving the report from the predicate to before_sleep.
    """
    from inspect_ai.util._concurrency import (
        AdaptiveConcurrency,
        AdaptiveConcurrencyController,
        _active_controller,
        _request_had_retry,
        init_concurrency,
    )

    init_concurrency()
    cfg = AdaptiveConcurrency(min=1, max=200, start=40, cooldown_seconds=15.0)
    controller = AdaptiveConcurrencyController("t-int", cfg, visible=True)

    # Sequence: 429 with Retry-After: 10 → 200. before_sleep should fire
    # between the two attempts and report rate_limit.
    responses = [
        httpx.Response(429, headers={"Retry-After": "10"}),
        httpx.Response(200, json={"ok": True}),
    ]
    client = _client_with_responses(responses)

    token_c = _active_controller.set(controller)
    token_r = _request_had_retry.set(False)
    try:
        with _reset_retry_counter():
            await chat_api_request(
                client,
                model_name="test-model",
                url="https://example.invalid/v1/chat",
                headers={},
                json={"input": "hello"},
            )
        # Controller scaled down on rate_limit signal: 40 * 0.8 = 32, floor → 30
        assert controller.concurrency == 30
        assert controller.history[-1][4] == "rate_limit"
        # Retry-After: 10 is below configured cooldown floor (15); cooldown
        # uses the floor. (Confirms retry_after was passed through — if it
        # had been larger, cooldown would extend; we check via the longer
        # retry-after below.)
        assert _request_had_retry.get() is True
    finally:
        _active_controller.reset(token_c)
        _request_had_retry.reset(token_r)
    await client.aclose()


@pytest.mark.anyio
async def test_chatapi_retry_after_extends_cooldown() -> None:
    """A long Retry-After from the response header propagates to controller cooldown."""
    import time

    from inspect_ai.util._concurrency import (
        AdaptiveConcurrency,
        AdaptiveConcurrencyController,
        _active_controller,
        _request_had_retry,
        init_concurrency,
    )

    init_concurrency()
    cfg = AdaptiveConcurrency(min=1, max=200, start=40, cooldown_seconds=5.0)
    controller = AdaptiveConcurrencyController("t-rtafter", cfg, visible=True)

    # Retry-After: 60 is well above the 5s cooldown floor
    responses = [
        httpx.Response(429, headers={"Retry-After": "60"}),
        httpx.Response(200, json={"ok": True}),
    ]
    client = _client_with_responses(responses)

    token_c = _active_controller.set(controller)
    token_r = _request_had_retry.set(False)
    try:
        before = time.monotonic()
        with _reset_retry_counter():
            await chat_api_request(
                client,
                model_name="test-model",
                url="https://example.invalid/v1/chat",
                headers={},
                json={"input": "hello"},
            )
        # cooldown extended to honor the 60s server hint (allow scheduling slack)
        assert controller._cooldown_until >= before + 50
    finally:
        _active_controller.reset(token_c)
        _request_had_retry.reset(token_r)
    await client.aclose()
