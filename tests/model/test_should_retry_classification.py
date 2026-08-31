"""Tests verifying each provider's should_retry classifies real SDK exceptions correctly.

These tests construct the actual exception types each provider's SDK raises and
assert that should_retry returns the correct RetryDecision (kind + retry_after).
This is the evidence that our classification works against real-world exception
shapes, not just our naive default that assumes `.status_code` is universal.
"""

from __future__ import annotations

import httpx
import httpx2
import pytest

from inspect_ai.model import RetryDecision, get_model


def _http_response(
    status: int, headers: dict[str, str] | None = None
) -> httpx.Response:
    """Build a stand-in httpx.Response for SDK exception constructors."""
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        request=request,
    )


def _httpx2_response(
    status: int, headers: dict[str, str] | None = None
) -> httpx2.Response:
    """Like _http_response, but httpx2-flavored (what openai >= 3 and anthropic >= 1 are built on)."""
    request = httpx2.Request("POST", "https://example.com/v1/chat/completions")
    return httpx2.Response(
        status_code=status,
        headers=headers or {},
        request=request,
    )


# ---------- Model-level generic classification ----------


def test_model_anyio_transport_close_race_classifies_as_retryable() -> None:
    """The anyio asyncio-backend transport-close race is retried for any provider.

    anyio's SocketStream.aclose() can call transport.abort() after
    connection_lost already ran (nulling transport._loop), raising
    AttributeError("'NoneType' object has no attribute 'call_soon'") out of
    httpx response close — after the request completed successfully.
    """
    model = get_model("mockllm/model")
    ex = AttributeError("'NoneType' object has no attribute 'call_soon'")
    assert model.should_retry(ex) is True


def test_model_transport_close_race_matches_structured_fields() -> None:
    """Reworded message still retries via AttributeError.name/.obj.

    Interpreter-raised AttributeError carries name/obj since 3.10; the
    classifier ORs (name == "call_soon" and obj is None) with the message
    match so a CPython message rewording doesn't silently drop the retry.
    """
    model = get_model("mockllm/model")
    ex = AttributeError("some future rewording", name="call_soon", obj=None)
    assert model.should_retry(ex) is True


def test_model_unrelated_attribute_error_does_not_retry() -> None:
    model = get_model("mockllm/model")
    ex = AttributeError("'NoneType' object has no attribute 'read'")
    assert model.should_retry(ex) is False


def test_model_empty_stream_classifies_as_retryable_for_any_provider() -> None:
    """A 200 stream that ended with zero chunks retries regardless of provider.

    Provider streaming loops raise NoStreamDataError when a misbehaving
    server delivers nothing; there is no payload to classify from, so the
    model layer retries it generically.
    """
    from inspect_ai.model._stream import NoStreamDataError

    model = get_model("mockllm/model")
    ex = NoStreamDataError("Streaming response ended without delivering any chunks.")
    assert model.should_retry(ex) is True

    # a plain RuntimeError with the same message must not retry
    assert model.should_retry(RuntimeError(str(ex))) is False


def test_model_call_soon_on_non_none_object_does_not_retry() -> None:
    """A deterministic bug mentioning call_soon (wrong-typed receiver) must not retry.

    The race always nulls transport._loop, so its message names NoneType;
    anything else is a real bug that should fail fast rather than retry forever.
    """
    model = get_model("mockllm/model")
    ex = AttributeError("'Foo' object has no attribute 'call_soon'")
    assert model.should_retry(ex) is False

    # structured fields on a non-None receiver must not match either
    ex2 = AttributeError(
        "'Foo' object has no attribute 'call_soon'", name="call_soon", obj=object()
    )
    assert model.should_retry(ex2) is False


# ---------- Default ModelAPI base ----------


def test_base_should_retry_returns_false() -> None:
    from inspect_ai.model._model import ModelAPI

    class _DummyAPI(ModelAPI):
        async def generate(self, *args, **kwargs):
            raise NotImplementedError

    api = _DummyAPI(
        model_name="x",
        base_url=None,
        api_key=None,
        api_key_vars=[],
    )
    assert api.should_retry(RuntimeError("any")) is False


# ---------- OpenAI shared classifier (covers openai, openai_compatible, openrouter) ----------


def test_openai_classify_rate_limit_429() -> None:
    from openai import APIStatusError

    from inspect_ai.model._openai import openai_classify_retry

    response = _httpx2_response(429, {"retry-after": "30"})
    ex = APIStatusError(message="rate limited", response=response, body=None)
    decision = openai_classify_retry(ex)
    assert decision is not None
    assert decision.retry is True
    assert decision.kind == "rate_limit"
    assert decision.retry_after == 30.0


def test_openai_classify_transient_5xx() -> None:
    from openai import APIStatusError

    from inspect_ai.model._openai import openai_classify_retry

    ex = APIStatusError(
        message="internal error",
        response=_httpx2_response(503),
        body=None,
    )
    decision = openai_classify_retry(ex)
    assert decision is not None
    assert decision.kind == "transient"
    assert decision.retry_after is None


def test_openai_classify_non_retryable_4xx_returns_none() -> None:
    from openai import APIStatusError

    from inspect_ai.model._openai import openai_classify_retry

    ex = APIStatusError(
        message="bad request",
        response=_httpx2_response(400),
        body=None,
    )
    assert openai_classify_retry(ex) is None


def test_openai_classify_rate_limit_error_subclass() -> None:
    from openai import RateLimitError

    from inspect_ai.model._openai import openai_classify_retry

    response = _httpx2_response(429, {"retry-after": "5"})
    ex = RateLimitError(message="too many", response=response, body=None)
    decision = openai_classify_retry(ex)
    assert decision is not None
    assert decision.kind == "rate_limit"
    assert decision.retry_after == 5.0


def test_openai_classify_mid_stream_server_error_as_transient() -> None:
    """A transient failure delivered mid-stream (after HTTP 200) is a bare APIError.

    The chat-completions stream iterator raises openai.APIError (no status
    code) built from the SSE error body — it must classify from code/type
    like the equivalent non-streaming 5xx does.
    """
    from openai import APIError

    from inspect_ai.model._openai import openai_classify_retry

    ex = APIError(
        message="The server had an error while processing your request.",
        request=httpx2.Request("POST", "https://example.com/v1/chat/completions"),
        body={
            "message": "The server had an error while processing your request.",
            "type": "server_error",
            "code": None,
        },
    )
    decision = openai_classify_retry(ex)
    assert decision is not None
    assert decision.retry is True
    assert decision.kind == "transient"

    # some backends signal via `code` rather than `type`
    ex2 = APIError(
        message="server error",
        request=httpx2.Request("POST", "https://example.com/v1/chat/completions"),
        body={"message": "server error", "type": "error", "code": "server_error"},
    )
    decision2 = openai_classify_retry(ex2)
    assert decision2 is not None
    assert decision2.kind == "transient"


def test_openai_classify_mid_stream_rate_limit_as_rate_limit() -> None:
    from openai import APIError

    from inspect_ai.model._openai import openai_classify_retry

    ex = APIError(
        message="rate limited",
        request=httpx2.Request("POST", "https://example.com/v1/chat/completions"),
        body={
            "message": "rate limited",
            "type": "requests",
            "code": "rate_limit_exceeded",
        },
    )
    decision = openai_classify_retry(ex)
    assert decision is not None
    assert decision.kind == "rate_limit"


def test_openai_classify_mid_stream_vllm_numeric_code_as_transient() -> None:
    """vLLM/SGLang deliver mid-stream errors as {"type": "InternalServerError", "code": 500}.

    The numeric code (an int at runtime despite the SDK's Optional[str]
    annotation) classifies through the standard HTTP status rules, and the
    CamelCase type spelling is recognized on its own too.
    """
    from openai import APIError

    from inspect_ai.model._openai import openai_classify_retry

    request = httpx2.Request("POST", "https://example.com/v1/chat/completions")
    ex = APIError(
        message="internal error",
        request=request,
        body={"message": "internal error", "type": "InternalServerError", "code": 500},
    )
    decision = openai_classify_retry(ex)
    assert decision is not None
    assert decision.kind == "transient"

    # type-only spelling (no code at all)
    ex2 = APIError(
        message="internal error",
        request=request,
        body={"message": "internal error", "type": "InternalServerError"},
    )
    decision2 = openai_classify_retry(ex2)
    assert decision2 is not None
    assert decision2.kind == "transient"


def test_openai_classify_mid_stream_openrouter_numeric_code() -> None:
    """OpenRouter delivers mid-stream errors as {"error": {"code": 502, "message": ...}}."""
    from openai import APIError

    from inspect_ai.model._openai import openai_classify_retry

    request = httpx2.Request("POST", "https://example.com/v1/chat/completions")
    ex = APIError(
        message="Provider returned error",
        request=request,
        body={"message": "Provider returned error", "code": 502},
    )
    decision = openai_classify_retry(ex)
    assert decision is not None
    assert decision.kind == "transient"

    # numeric 429 (as int or digit string) classifies as rate limit
    for code in (429, "429"):
        ex2 = APIError(
            message="rate limited",
            request=request,
            body={"message": "rate limited", "code": code},
        )
        decision2 = openai_classify_retry(ex2)
        assert decision2 is not None
        assert decision2.kind == "rate_limit"


def test_openai_classify_mid_stream_permanent_error_does_not_retry() -> None:
    """A permanent bare APIError (non-transient code/type) must re-raise, not retry."""
    from openai import APIError

    from inspect_ai.model._openai import openai_classify_retry

    request = httpx2.Request("POST", "https://example.com/v1/chat/completions")
    ex = APIError(
        message="invalid request",
        request=request,
        body={
            "message": "invalid request",
            "type": "invalid_request_error",
            "code": "invalid_api_key",
        },
    )
    assert openai_classify_retry(ex) is None

    # a numeric non-retryable status must not retry either
    ex_400 = APIError(
        message="bad request",
        request=request,
        body={"message": "bad request", "code": 400},
    )
    assert openai_classify_retry(ex_400) is None

    # non-dict body leaves code/type as None — also not retryable
    ex_no_body = APIError(
        message="opaque failure",
        request=request,
        body=None,
    )
    assert openai_classify_retry(ex_no_body) is None


def test_openai_provider_quota_exceeded_does_not_retry() -> None:
    """OpenAI's monthly-quota error (RateLimitError with specific message) shouldn't retry."""
    from openai import RateLimitError

    from inspect_ai.model._providers.openai import OpenAIAPI

    api = OpenAIAPI.__new__(OpenAIAPI)  # avoid full init
    ex = RateLimitError(
        message="You exceeded your current quota, please check your plan.",
        response=_httpx2_response(429),
        body=None,
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is False


def test_openai_provider_429_classifies_as_rate_limit() -> None:
    from openai import RateLimitError

    from inspect_ai.model._providers.openai import OpenAIAPI

    api = OpenAIAPI.__new__(OpenAIAPI)
    ex = RateLimitError(
        message="rate limited",
        response=_httpx2_response(429, {"retry-after": "10"}),
        body=None,
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True
    assert decision.kind == "rate_limit"
    assert decision.retry_after == 10.0


def test_openrouter_json_decode_classifies_as_transient() -> None:
    """OpenRouter occasionally returns malformed JSON — classify as transient."""
    import json

    from inspect_ai.model._providers.openrouter import OpenRouterAPI

    api = OpenRouterAPI.__new__(OpenRouterAPI)
    ex = json.JSONDecodeError("bad json", "doc", 0)
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True
    assert decision.kind == "transient"


# ---------- Anthropic ----------


def test_anthropic_429_classifies_as_rate_limit() -> None:
    from anthropic import APIStatusError

    from inspect_ai.model._providers.anthropic import AnthropicAPI

    api = AnthropicAPI.__new__(AnthropicAPI)
    ex = APIStatusError(
        message="rate limited",
        response=_httpx2_response(429, {"retry-after": "20"}),
        body=None,
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"
    assert decision.retry_after == 20.0


def test_anthropic_503_classifies_as_transient() -> None:
    from anthropic import APIStatusError

    from inspect_ai.model._providers.anthropic import AnthropicAPI

    api = AnthropicAPI.__new__(AnthropicAPI)
    ex = APIStatusError(
        message="overloaded",
        response=_httpx2_response(503),
        body=None,
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "transient"


def test_anthropic_streaming_overloaded_body_classifies_as_transient() -> None:
    """Anthropic streaming sets a non-rate-limit status with overloaded body — should be transient."""
    from anthropic import APIStatusError

    from inspect_ai.model._providers.anthropic import AnthropicAPI

    api = AnthropicAPI.__new__(AnthropicAPI)
    ex = APIStatusError(
        message="overloaded",
        response=_httpx2_response(200),
        body={"error": {"message": "overloaded"}},
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True
    assert decision.kind == "transient"


def test_anthropic_mid_stream_rate_limit_classifies_as_rate_limit() -> None:
    """A mid-stream SSE error event surfaces as APIStatusError with status 200.

    The SDK builds it from the error body (the HTTP response was 200), so
    classification must come from the body's error type — a mid-stream
    rate_limit_error is the same condition as a 429 on the non-streaming path.
    """
    from anthropic import APIStatusError

    from inspect_ai.model._providers.anthropic import AnthropicAPI

    api = AnthropicAPI.__new__(AnthropicAPI)
    ex = APIStatusError(
        message="rate limited",
        response=_httpx2_response(200),
        body={
            "type": "error",
            "error": {"type": "rate_limit_error", "message": "rate limited"},
        },
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"


@pytest.mark.parametrize(
    "error_type", ["overloaded_error", "api_error", "timeout_error"]
)
def test_anthropic_mid_stream_transient_types_classify_as_transient(
    error_type: str,
) -> None:
    from anthropic import APIStatusError

    from inspect_ai.model._providers.anthropic import AnthropicAPI

    api = AnthropicAPI.__new__(AnthropicAPI)
    ex = APIStatusError(
        message=error_type,
        response=_httpx2_response(200),
        body={"type": "error", "error": {"type": error_type, "message": "boom"}},
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True
    assert decision.kind == "transient"


def test_anthropic_mid_stream_permanent_error_does_not_retry() -> None:
    from anthropic import APIStatusError

    from inspect_ai.model._providers.anthropic import AnthropicAPI

    api = AnthropicAPI.__new__(AnthropicAPI)
    ex = APIStatusError(
        message="invalid request",
        response=_httpx2_response(200),
        body={
            "type": "error",
            "error": {"type": "invalid_request_error", "message": "bad input"},
        },
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is False


def test_anthropic_transient_body_type_on_permanent_status_does_not_retry() -> None:
    """Type-based classification is scoped to status 200 (the mid-stream case).

    A real HTTP error status — e.g. a proxy's 4xx wrapping an
    anthropic-format body with a transient inner type — must keep failing
    fast via the status rules rather than retrying forever.
    """
    from anthropic import APIStatusError

    from inspect_ai.model._providers.anthropic import AnthropicAPI

    api = AnthropicAPI.__new__(AnthropicAPI)
    ex = APIStatusError(
        message="not found",
        response=_httpx2_response(404),
        body={"type": "error", "error": {"type": "api_error", "message": "no route"}},
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is False


def test_anthropic_mid_stream_unparseable_string_body_falls_back_to_substring() -> None:
    """An SSE error event whose data fails JSON parsing attaches the raw string body."""
    from anthropic import APIStatusError

    from inspect_ai.model._providers.anthropic import AnthropicAPI

    api = AnthropicAPI.__new__(AnthropicAPI)
    ex = APIStatusError(
        message="overloaded",
        response=_httpx2_response(200),
        body='{"type": "error", "error": {"type": "overloaded_er',
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True
    assert decision.kind == "transient"


def test_anthropic_httpx2_transport_error_classifies_as_transient() -> None:
    """Anthropic >= 1 is built on httpx2 — raw httpx2 transport errors that escape the SDK unwrapped must still retry."""
    from inspect_ai.model._providers.anthropic import AnthropicAPI

    api = AnthropicAPI.__new__(AnthropicAPI)
    ex = httpx2.ConnectError("connection reset")
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True
    assert decision.kind == "transient"


# ---------- Groq ----------


def test_groq_429_classifies_as_rate_limit() -> None:
    from groq import APIStatusError

    from inspect_ai.model._providers.groq import GroqAPI

    api = GroqAPI.__new__(GroqAPI)
    ex = APIStatusError(
        message="rate limited",
        response=_http_response(429, {"retry-after": "1m30s"}),
        body=None,
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"
    assert decision.retry_after == 90.0


def test_groq_500_classifies_as_transient() -> None:
    from groq import APIStatusError

    from inspect_ai.model._providers.groq import GroqAPI

    api = GroqAPI.__new__(GroqAPI)
    ex = APIStatusError(message="srv err", response=_http_response(500), body=None)
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "transient"


# ---------- Mistral ----------


def test_mistral_429_classifies_as_rate_limit() -> None:
    pytest.importorskip("mistralai")
    from mistralai.client.errors import SDKError

    from inspect_ai.model._providers.mistral import MistralAPI

    api = MistralAPI.__new__(MistralAPI)
    ex = SDKError.__new__(SDKError)
    ex.status_code = 429
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"


def test_mistral_500_classifies_as_transient() -> None:
    pytest.importorskip("mistralai")
    from mistralai.client.errors import SDKError

    from inspect_ai.model._providers.mistral import MistralAPI

    api = MistralAPI.__new__(MistralAPI)
    ex = SDKError.__new__(SDKError)
    ex.status_code = 500
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "transient"


# ---------- Azure OpenAI ----------


def test_azure_429_classifies_as_rate_limit() -> None:
    pytest.importorskip("azure.core")
    from azure.core.exceptions import HttpResponseError

    from inspect_ai.model._providers.azureai import AzureAIAPI

    api = AzureAIAPI.__new__(AzureAIAPI)
    ex = HttpResponseError.__new__(HttpResponseError)
    ex.status_code = 429
    ex.response = None  # no headers available — retry_after is None
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"


def test_azure_503_classifies_as_transient() -> None:
    pytest.importorskip("azure.core")
    from azure.core.exceptions import HttpResponseError

    from inspect_ai.model._providers.azureai import AzureAIAPI

    api = AzureAIAPI.__new__(AzureAIAPI)
    ex = HttpResponseError.__new__(HttpResponseError)
    ex.status_code = 503
    ex.response = None
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "transient"


# ---------- Bedrock ----------


def test_bedrock_throttling_classifies_as_rate_limit() -> None:
    from botocore.exceptions import ClientError

    from inspect_ai.model._providers.bedrock import BedrockAPI

    api = BedrockAPI.__new__(BedrockAPI)
    ex = ClientError(
        error_response={"Error": {"Code": "ThrottlingException", "Message": "x"}},
        operation_name="Converse",
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"


def test_bedrock_internal_failure_classifies_as_transient() -> None:
    from botocore.exceptions import ClientError

    from inspect_ai.model._providers.bedrock import BedrockAPI

    api = BedrockAPI.__new__(BedrockAPI)
    ex = ClientError(
        error_response={"Error": {"Code": "ServiceUnavailable", "Message": "x"}},
        operation_name="Converse",
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "transient"


def test_bedrock_unknown_code_does_not_retry() -> None:
    from botocore.exceptions import ClientError

    from inspect_ai.model._providers.bedrock import BedrockAPI

    api = BedrockAPI.__new__(BedrockAPI)
    ex = ClientError(
        error_response={"Error": {"Code": "ValidationException", "Message": "x"}},
        operation_name="Converse",
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is False


# ---------- Google ----------


def test_google_429_resource_exhausted_classifies_as_rate_limit() -> None:
    from google.genai.errors import APIError

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    api = GoogleGenAIAPI.__new__(GoogleGenAIAPI)
    ex = APIError.__new__(APIError)
    ex.code = 429
    ex.status = "RESOURCE_EXHAUSTED"
    ex.message = ""
    ex.details = None
    ex.response = None
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"


def test_google_503_resource_exhausted_classifies_as_rate_limit() -> None:
    from google.genai.errors import APIError

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    api = GoogleGenAIAPI.__new__(GoogleGenAIAPI)
    ex = APIError.__new__(APIError)
    ex.code = 503
    ex.status = "RESOURCE_EXHAUSTED"
    ex.message = ""
    ex.details = None
    ex.response = None
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"


def test_google_429_without_status_text_still_classifies_as_rate_limit() -> None:
    """Plain HTTP 429 from Google is unconditionally a rate-limit signal.

    The RESOURCE_EXHAUSTED guard is only needed to disambiguate 503.
    """
    from google.genai.errors import APIError

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    api = GoogleGenAIAPI.__new__(GoogleGenAIAPI)
    ex = APIError.__new__(APIError)
    ex.code = 429
    ex.status = None  # SDK didn't populate status — still rate_limit
    ex.message = ""
    ex.details = None
    ex.response = None
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"

    # And with arbitrary status text — still rate_limit
    ex2 = APIError.__new__(APIError)
    ex2.code = 429
    ex2.status = "QUOTA_EXCEEDED"  # not "RESOURCE_EXHAUSTED"
    ex2.message = ""
    ex2.details = None
    ex2.response = None
    decision = api.should_retry(ex2)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"


def test_google_503_unavailable_classifies_as_transient() -> None:
    from google.genai.errors import APIError

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    api = GoogleGenAIAPI.__new__(GoogleGenAIAPI)
    ex = APIError.__new__(APIError)
    ex.code = 503
    ex.status = "UNAVAILABLE"
    ex.message = ""
    ex.details = None
    ex.response = None
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "transient"


def test_google_client_payload_transfer_encoding_classifies_as_transient() -> None:
    """A chunked response truncated mid-body (connection reset) is transient."""
    import aiohttp

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    api = GoogleGenAIAPI.__new__(GoogleGenAIAPI)
    ex = aiohttp.ClientPayloadError("Response payload is not completed")
    ex.__cause__ = aiohttp.http_exceptions.TransferEncodingError(
        message="Not enough data to satisfy transfer length header."
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True
    assert decision.kind == "transient"


def test_google_client_payload_content_length_classifies_as_transient() -> None:
    """A Content-Length response truncated the same way is equally transient."""
    import aiohttp

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    api = GoogleGenAIAPI.__new__(GoogleGenAIAPI)
    ex = aiohttp.ClientPayloadError("Response payload is not completed")
    ex.__cause__ = aiohttp.http_exceptions.ContentLengthError(
        message="Not enough data to satisfy content length header."
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True
    assert decision.kind == "transient"


def test_google_client_payload_non_encoding_cause_does_not_retry() -> None:
    """A non-truncation cause (e.g. corrupt compression) is not retryable."""
    import aiohttp

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    api = GoogleGenAIAPI.__new__(GoogleGenAIAPI)
    ex = aiohttp.ClientPayloadError("Response payload is not completed")
    ex.__cause__ = ValueError(
        "Error -3 while decompressing data: incorrect header check"
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is False


def test_google_client_payload_without_cause_does_not_retry() -> None:
    import aiohttp

    from inspect_ai.model._providers.google import GoogleGenAIAPI

    api = GoogleGenAIAPI.__new__(GoogleGenAIAPI)
    ex = aiohttp.ClientPayloadError("Response payload is not completed")
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is False


# ---------- Grok (gRPC) ----------


def test_grok_resource_exhausted_classifies_as_rate_limit() -> None:
    pytest.importorskip("grpc")
    import grpc

    from inspect_ai.model._providers.grok import GrokAPI

    api = GrokAPI.__new__(GrokAPI)

    class _RpcError(grpc.RpcError):
        def __init__(self, code: grpc.StatusCode):
            self._code = code

        def code(self):
            return self._code

    decision = api.should_retry(_RpcError(grpc.StatusCode.RESOURCE_EXHAUSTED))
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"


def test_grok_unavailable_classifies_as_transient() -> None:
    pytest.importorskip("grpc")
    import grpc

    from inspect_ai.model._providers.grok import GrokAPI

    api = GrokAPI.__new__(GrokAPI)

    class _RpcError(grpc.RpcError):
        def __init__(self, code: grpc.StatusCode):
            self._code = code

        def code(self):
            return self._code

    decision = api.should_retry(_RpcError(grpc.StatusCode.UNAVAILABLE))
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "transient"


# ---------- Sagemaker ----------


def test_sagemaker_503_classifies_as_transient() -> None:
    from botocore.exceptions import ClientError

    from inspect_ai.model._providers.sagemaker import SagemakerAPI

    api = SagemakerAPI.__new__(SagemakerAPI)
    ex = ClientError(
        error_response={
            "Error": {"Code": "ModelError", "Message": "x"},
            "OriginalStatusCode": 503,  # type: ignore[typeddict-unknown-key]
        },
        operation_name="InvokeEndpoint",
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "transient"


def test_sagemaker_other_error_does_not_retry() -> None:
    from botocore.exceptions import ClientError

    from inspect_ai.model._providers.sagemaker import SagemakerAPI

    api = SagemakerAPI.__new__(SagemakerAPI)
    ex = ClientError(
        error_response={
            "Error": {"Code": "ValidationException", "Message": "x"},
            "OriginalStatusCode": 400,  # type: ignore[typeddict-unknown-key]
        },
        operation_name="InvokeEndpoint",
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is False


@pytest.mark.parametrize("code", ["ModelStreamError", "InternalStreamFailure"])
def test_sagemaker_mid_stream_event_stream_error_classifies_as_transient(
    code: str,
) -> None:
    """In-band stream errors (after HTTP 200) surface as EventStreamError.

    Both event shapes are marked `exception` in the AWS service model, so
    botocore raises them from the stream iterator as EventStreamError (a
    ClientError) with the exception type as the code — and both are
    infrastructure transients (AWS documents InternalStreamFailure as "Try
    your request again"; ModelStreamError's documented ErrorCodes are a
    model timeout and a TCP reset).
    """
    from botocore.exceptions import EventStreamError

    from inspect_ai.model._providers.sagemaker import SagemakerAPI

    api = SagemakerAPI.__new__(SagemakerAPI)
    ex = EventStreamError(
        {"Error": {"Code": code, "Message": "stream failed"}},
        "InvokeEndpointWithResponseStream",
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True
    assert decision.kind == "transient"


def test_sagemaker_in_band_stream_error_backstop_classifies_as_transient() -> None:
    """The typed backstop for in-band error events also classifies as transient."""
    from inspect_ai.model._providers.sagemaker import (
        SagemakerAPI,
        SageMakerStreamError,
    )

    api = SagemakerAPI.__new__(SagemakerAPI)
    ex = SageMakerStreamError("ModelStreamError [StreamBroken]: tcp reset")
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True
    assert decision.kind == "transient"


# ---------- Together (RetryError unwrapping) ----------


def test_together_rest_unwraps_retry_error_and_classifies_429() -> None:
    """TogetherRESTAPI uses the chatapi shared helper which wraps causes in tenacity.RetryError."""
    from tenacity import RetryError

    from inspect_ai.model._providers.together import TogetherRESTAPI

    api = TogetherRESTAPI.__new__(TogetherRESTAPI)
    cause = httpx.HTTPStatusError(
        "rate limited",
        request=httpx.Request("POST", "https://api.together.ai/v1/chat"),
        response=_http_response(429, {"retry-after": "30"}),
    )
    wrapped = RetryError(last_attempt=None)  # type: ignore[arg-type]
    wrapped.__cause__ = cause
    decision = api.should_retry(wrapped)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"
    assert decision.retry_after == 30.0


def test_together_rest_unwraps_retry_error_and_classifies_5xx() -> None:
    from tenacity import RetryError

    from inspect_ai.model._providers.together import TogetherRESTAPI

    api = TogetherRESTAPI.__new__(TogetherRESTAPI)
    cause = httpx.HTTPStatusError(
        "srv err",
        request=httpx.Request("POST", "https://api.together.ai/v1/chat"),
        response=_http_response(500),
    )
    wrapped = RetryError(last_attempt=None)  # type: ignore[arg-type]
    wrapped.__cause__ = cause
    decision = api.should_retry(wrapped)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "transient"


def test_together_openai_compatible_429_classifies_as_rate_limit() -> None:
    """TogetherAIAPI inherits OpenAI-compatible classification (no RetryError unwrap)."""
    from openai import APIStatusError

    from inspect_ai.model._providers.together import TogetherAIAPI

    api = TogetherAIAPI.__new__(TogetherAIAPI)
    ex = APIStatusError(
        message="rate limited",
        response=_httpx2_response(429, {"retry-after": "15"}),
        body=None,
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"
    assert decision.retry_after == 15.0
