"""Unit tests for OpenAIAPI.reasoning_summaries() error handling and usage.

These run without network access: the provider is constructed with a dummy key
and ``client.responses.create`` is monkeypatched to raise the exception shapes
the OpenAI SDK would produce, or to return a canned response.
"""

from __future__ import annotations

from typing import Any

import httpx2
import pytest
from openai import APITimeoutError, BadRequestError
from openai.types.responses import Response, ResponseUsage
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
)

from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelOutput, ModelUsage
from inspect_ai.model._providers import openai as openai_provider
from inspect_ai.model._providers.openai import OpenAIAPI


def _make_api() -> OpenAIAPI:
    # gpt-5 has reasoning options, and force the responses API so
    # reasoning_summaries() actually probes the account.
    return OpenAIAPI(model_name="gpt-5", api_key="test-key", responses_api=True)


def _request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.openai.com/v1/responses")


def _probe_response() -> Response:
    return Response.model_construct(
        usage=ResponseUsage(
            input_tokens=12,
            input_tokens_details=InputTokensDetails(
                cached_tokens=2, cache_write_tokens=0
            ),
            output_tokens=30,
            output_tokens_details=OutputTokensDetails(reasoning_tokens=20),
            total_tokens=42,
        )
    )


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
            return _probe_response()

        monkeypatch.setattr(api.client.responses, "create", flaky)

        # The first probe hits a transient timeout: degrade gracefully for this
        # call, but don't cache the failure...
        assert (await api.reasoning_summaries()).supported is False
        # ...so once the blip clears the next probe still discovers support.
        assert (await api.reasoning_summaries()).supported is True
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
        assert (await api.reasoning_summaries()).supported is False
        assert (await api.reasoning_summaries()).supported is False
        assert calls["n"] == 1
    finally:
        await api.aclose()


@pytest.mark.anyio
async def test_reasoning_summaries_probe_usage_reported_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The billed probe's usage is added to the generate call that sent it."""
    api = _make_api()
    try:
        probes = {"n": 0}

        async def probe(**kwargs: object) -> Response:
            probes["n"] += 1
            return _probe_response()

        async def generate_responses(**kwargs: Any) -> ModelOutput:
            output = ModelOutput.from_content(model="gpt-5", content="hello")
            output.usage = ModelUsage(
                input_tokens=100, output_tokens=10, total_tokens=110
            )
            return output

        monkeypatch.setattr(api.client.responses, "create", probe)
        monkeypatch.setattr(openai_provider, "generate_responses", generate_responses)

        async def generate() -> ModelOutput:
            output = await api.generate(
                input=[ChatMessageUser(content="hi")],
                tools=[],
                tool_choice="none",
                config=GenerateConfig(),
            )
            assert isinstance(output, ModelOutput)
            return output

        first = await generate()
        assert first.usage == ModelUsage(
            input_tokens=110,
            output_tokens=40,
            total_tokens=152,
            input_tokens_cache_read=2,
            reasoning_tokens=20,
        )
        # the probe's prompt was never part of the input
        assert first.input_context_tokens == 100

        # the probe runs once per provider instance, so later calls report
        # only their own usage
        second = await generate()
        assert probes["n"] == 1
        assert second.usage == ModelUsage(
            input_tokens=100, output_tokens=10, total_tokens=110
        )
    finally:
        await api.aclose()


@pytest.mark.parametrize(
    ("code", "stop_reason"),
    [
        ("context_length_exceeded", "model_length"),
        ("content_policy_violation", "content_filter"),
    ],
)
@pytest.mark.anyio
async def test_reasoning_summaries_probe_then_rejected_request(
    monkeypatch: pytest.MonkeyPatch, code: str, stop_reason: str
) -> None:
    """A rejected request after the probe still reports the billed probe."""
    from inspect_ai.model import get_model

    model = get_model(
        "openai/gpt-5",
        memoize=False,
        api_key="test-key",
        responses_api=True,
        config=GenerateConfig(max_retries=0),
    )
    api = model.api
    assert isinstance(api, OpenAIAPI)
    try:

        async def create(**kwargs: object) -> Response:
            if kwargs.get("input") == "Please say 'hello, world'":
                return _probe_response()
            raise BadRequestError(
                message="rejected",
                response=httpx2.Response(status_code=400, request=_request()),
                body={"message": "rejected", "code": code},
            )

        monkeypatch.setattr(api.client.responses, "create", create)

        output = await model.generate("hi")

        assert output.stop_reason == stop_reason
        assert output.usage == ModelUsage(
            input_tokens=10,
            output_tokens=30,
            total_tokens=42,
            input_tokens_cache_read=2,
            reasoning_tokens=20,
        )
    finally:
        await api.aclose()


@pytest.mark.anyio
async def test_reasoning_summaries_probe_reasoning_not_stamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe's billed reasoning does not count as the message's redacted reasoning."""
    from inspect_ai._util.content import ContentReasoning, ContentText
    from inspect_ai.model import ChatMessageAssistant, get_model
    from inspect_ai.model._compaction._compaction import (
        _redacted_reasoning_tokens_total,
    )
    from inspect_ai.model._model import REDACTED_REASONING_TOKENS_METADATA_KEY

    model = get_model(
        "openai/gpt-5",
        memoize=False,
        api_key="test-key",
        responses_api=True,
        config=GenerateConfig(max_retries=0),
    )
    api = model.api
    assert isinstance(api, OpenAIAPI)
    try:

        async def probe(**kwargs: object) -> Response:
            return _probe_response()

        async def generate_responses(**kwargs: Any) -> ModelOutput:
            output = ModelOutput.from_message(
                ChatMessageAssistant(
                    content=[
                        ContentReasoning(reasoning="enc", redacted=True),
                        ContentText(text="hello"),
                    ],
                    model="gpt-5",
                )
            )
            output.usage = ModelUsage(
                input_tokens=100, output_tokens=10, total_tokens=110, reasoning_tokens=5
            )
            return output

        monkeypatch.setattr(api.client.responses, "create", probe)
        monkeypatch.setattr(openai_provider, "generate_responses", generate_responses)

        output = await model.generate("hi")

        # billed: the primary's 5 reasoning tokens plus the probe's 20
        assert output.usage is not None
        assert output.usage.reasoning_tokens == 25
        # replayed: only the primary's reasoning is in the message
        metadata = output.message.metadata or {}
        assert metadata[REDACTED_REASONING_TOKENS_METADATA_KEY] == 5
        assert api.apply_redacted_reasoning_tokens_to_input()
        assert _redacted_reasoning_tokens_total([output.message], model) == 5
    finally:
        await api.aclose()
