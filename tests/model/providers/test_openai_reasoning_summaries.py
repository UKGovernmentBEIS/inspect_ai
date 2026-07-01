"""Unit tests for OpenAIAPI.reasoning_summaries() error handling.

These run without network access: the provider is constructed with a dummy key
and ``client.responses.create`` is monkeypatched to raise the exception shapes
the OpenAI SDK would produce.
"""

from __future__ import annotations

import httpx
import pytest
from openai import APITimeoutError, BadRequestError

from inspect_ai.model._providers.openai import OpenAIAPI


def _make_api() -> OpenAIAPI:
    # gpt-5 has reasoning options, and force the responses API so
    # reasoning_summaries() actually probes the account.
    return OpenAIAPI(model_name="gpt-5", api_key="test-key", responses_api=True)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/responses")


@pytest.mark.anyio
async def test_reasoning_summaries_transient_error_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _make_api()
    assert api.has_reasoning_options()
    try:
        calls = {"n": 0}

        async def flaky(**kwargs: object) -> object:
            calls["n"] += 1
            if calls["n"] == 1:
                raise APITimeoutError(request=_request())
            return object()

        monkeypatch.setattr(api.client.responses, "create", flaky)

        # The first probe hits a transient timeout: degrade gracefully for this
        # call, but don't cache the failure...
        assert await api.reasoning_summaries() is False
        # ...so once the blip clears the next probe still discovers support.
        assert await api.reasoning_summaries() is True
        assert calls["n"] == 2
    finally:
        await api.aclose()


@pytest.mark.anyio
async def test_reasoning_summaries_unsupported_error_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _make_api()
    try:
        calls = {"n": 0}
        response = httpx.Response(status_code=400, request=_request())

        async def unsupported(**kwargs: object) -> object:
            calls["n"] += 1
            raise BadRequestError(
                message="Your organization must be verified to generate reasoning summaries",
                response=response,
                body=None,
            )

        monkeypatch.setattr(api.client.responses, "create", unsupported)

        # A deterministic 400 means summaries really aren't available: cache it
        # and don't re-probe on every later sample.
        assert await api.reasoning_summaries() is False
        assert await api.reasoning_summaries() is False
        assert calls["n"] == 1
    finally:
        await api.aclose()
