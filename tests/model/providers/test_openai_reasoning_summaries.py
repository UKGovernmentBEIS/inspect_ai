"""Unit tests for OpenAIAPI.reasoning_summaries() error handling.

These run without network access: the provider is constructed with a dummy key
and ``client.responses.create`` is monkeypatched to raise the exception shapes
the OpenAI SDK would produce.
"""

from __future__ import annotations

from functools import partial

import httpx2
import pytest
from openai import APITimeoutError, BadRequestError
from test_helpers.sentinel_failure import (
    FailDuringRequest,
    is_refusal,
    outcome_while_failing,
)

from inspect_ai.model import get_model
from inspect_ai.model._providers.openai import OpenAIAPI


def _make_api() -> OpenAIAPI:
    # gpt-5 has reasoning options, and force the responses API so
    # reasoning_summaries() actually probes the account.
    return OpenAIAPI(model_name="gpt-5", api_key="test-key", responses_api=True)


def _request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.openai.com/v1/responses")


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
        response = httpx2.Response(status_code=400, request=_request())

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


class _Sent(Exception):
    """Raised by a stub endpoint to end a generate whose request was sent."""


@pytest.mark.parametrize("monitor", [False, True], ids=["sample", "monitor"])
@pytest.mark.anyio
async def test_no_generate_request_follows_the_probe_once_the_sample_has_failed(
    monkeypatch: pytest.MonkeyPatch, monitor: bool
) -> None:
    """A sample that fails during the reasoning-summary probe sends no generate request.

    A sentinel's monitor still does.
    """
    model = get_model(
        "openai/gpt-5",
        responses_api=True,
        streaming=False,
        api_key="test-key",
        memoize=False,
    )
    during_probe = FailDuringRequest()
    requests: list[str] = []

    async def create(**kwargs: object) -> object:
        if not requests:
            requests.append("probe")
            await during_probe.pending()
            return object()
        requests.append("generate")
        raise _Sent()

    assert isinstance(model.api, OpenAIAPI)
    monkeypatch.setattr(model.api.client.responses, "create", create)
    try:
        outcome = await outcome_while_failing(
            partial(model.generate, "hello"), during_probe, monitor=monitor
        )
    finally:
        await model.api.aclose()

    if monitor:
        assert requests == ["probe", "generate"]
        assert isinstance(outcome, _Sent)
    else:
        assert requests == ["probe"]
        assert is_refusal(outcome)
