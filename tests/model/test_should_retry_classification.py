"""Tests verifying each provider's should_retry classifies real SDK exceptions correctly.

These tests construct the actual exception types each provider's SDK raises and
assert that should_retry returns the correct RetryDecision (kind + retry_after).
This is the evidence that our classification works against real-world exception
shapes, not just our naive default that assumes `.status_code` is universal.
"""

from __future__ import annotations

import httpx
import pytest

from inspect_ai.model import RetryDecision


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

    response = _http_response(429, {"retry-after": "30"})
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
        response=_http_response(503),
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
        response=_http_response(400),
        body=None,
    )
    assert openai_classify_retry(ex) is None


def test_openai_classify_rate_limit_error_subclass() -> None:
    from openai import RateLimitError

    from inspect_ai.model._openai import openai_classify_retry

    response = _http_response(429, {"retry-after": "5"})
    ex = RateLimitError(message="too many", response=response, body=None)
    decision = openai_classify_retry(ex)
    assert decision is not None
    assert decision.kind == "rate_limit"
    assert decision.retry_after == 5.0


def test_openai_provider_quota_exceeded_does_not_retry() -> None:
    """OpenAI's monthly-quota error (RateLimitError with specific message) shouldn't retry."""
    from openai import RateLimitError

    from inspect_ai.model._providers.openai import OpenAIAPI

    api = OpenAIAPI.__new__(OpenAIAPI)  # avoid full init
    ex = RateLimitError(
        message="You exceeded your current quota, please check your plan.",
        response=_http_response(429),
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
        response=_http_response(429, {"retry-after": "10"}),
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
        response=_http_response(429, {"retry-after": "20"}),
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
        response=_http_response(503),
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
        response=_http_response(200),
        body={"error": {"message": "overloaded"}},
    )
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
        response=_http_response(429, {"retry-after": "15"}),
        body=None,
    )
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.kind == "rate_limit"
    assert decision.retry_after == 15.0
