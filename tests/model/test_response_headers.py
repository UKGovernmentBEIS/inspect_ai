# --- response-header recording semantics ---

import httpx
import pytest

from inspect_ai._util.http_defaults import default_async_client
from inspect_ai._util.registry import _registry
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    current_response_headers,
    get_model,
    record_response_headers,
)
from inspect_ai.model._model import ModelGenerateError
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._registry import modelapi
from inspect_ai.model._response_headers import (
    begin_attempt_response_headers,
    finish_attempt_response_headers,
)
from inspect_ai.tool import ToolChoice, ToolInfo


class Retryable(Exception):
    """A provider error the fake API classifies as retryable."""


def test_record_ignored_outside_attempt_scope() -> None:
    # recordings with no open attempt scope are dropped, so unrelated
    # HTTP traffic never surfaces as model-call headers
    record_response_headers({"x-sentinel": "blocked"})
    assert current_response_headers() is None


async def test_factory_hook_records_within_attempt_scope() -> None:
    # own-stack SDKs keep wire casing while httpx lowercases: recording
    # normalizes so ModelCall.response_headers is uniform either way
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"X-Gateway": "edge-7"})
    )
    async with default_async_client(transport=transport) as client:
        begin_attempt_response_headers()
        await client.get("https://model.example/v1/chat")
        # recording still open: the attempt value is live until finish, then
        # snapshot as the last attempt's headers
        finish_attempt_response_headers()
        assert current_response_headers() == {"x-gateway": "edge-7"}


async def test_factory_hook_ignored_without_attempt_scope() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"x-gateway": "edge-7"})
    )
    async with default_async_client(transport=transport) as client:
        await client.get("https://model.example/v1/chat")
        assert current_response_headers() is None


async def test_scope_closes_after_attempt_so_later_traffic_is_ignored() -> None:
    # a completed call must not keep recording: unrelated HTTP afterwards
    # (dataset fetches, token lookups) never overwrites the last attempt
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"x-other": "download"})
    )
    try:
        model = fake_model(GenerateConfig())
        await model.generate("hello")
        assert current_response_headers() == {"x-sentinel": "allowed", "x-attempt": "2"}
        async with default_async_client(transport=transport) as client:
            await client.get("https://cdn.example/dataset.json")
        assert current_response_headers() == {"x-sentinel": "allowed", "x-attempt": "2"}
    finally:
        cleanup()
        del _registry[f"modelapi:{API_NAME}"]


# --- model-call integration ---

API_NAME = "headersfake"


class HeadersAPI(ModelAPI):
    """Records headers per attempt like an own-stack provider would."""

    attempts: int = 0
    last_call: ModelCall | None = None
    fail_first_with: Exception | None = None
    error_tuple: bool = False

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: object,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key="headers-api-key",
            api_key_vars=[],
            config=config,
        )

    def should_retry(self, ex: Exception) -> bool:
        return isinstance(ex, Retryable) and self.fail_first_with is not None

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        HeadersAPI.attempts += 1
        call = ModelCall.create(request={"messages": len(input)}, response={"ok": True})
        HeadersAPI.last_call = call
        if HeadersAPI.attempts == 1 and HeadersAPI.fail_first_with is not None:
            record_response_headers({"x-sentinel": "blocked", "x-attempt": "1"})
            if HeadersAPI.error_tuple:
                return HeadersAPI.fail_first_with, call
            raise HeadersAPI.fail_first_with
        record_response_headers({"x-sentinel": "allowed", "x-attempt": "2"})
        return ModelOutput.from_content(model=self.model_name, content="ok"), call


def fake_model(config: GenerateConfig) -> object:
    @modelapi(name=API_NAME)
    def headersfake() -> type[ModelAPI]:
        return HeadersAPI

    return get_model(f"{API_NAME}/test", config=config)


def cleanup() -> None:
    HeadersAPI.attempts = 0
    HeadersAPI.last_call = None
    HeadersAPI.fail_first_with = None
    HeadersAPI.error_tuple = False


async def test_success_call_carries_headers() -> None:
    try:
        model = fake_model(GenerateConfig())
        await model.generate("hello")
        assert HeadersAPI.last_call is not None
        assert HeadersAPI.last_call.response_headers == {
            "x-sentinel": "allowed",
            "x-attempt": "2",
        }
        assert current_response_headers() == {"x-sentinel": "allowed", "x-attempt": "2"}
    finally:
        cleanup()
        del _registry[f"modelapi:{API_NAME}"]


async def test_retry_keeps_only_last_attempt_headers() -> None:
    try:
        HeadersAPI.fail_first_with = Retryable("transient")
        model = fake_model(GenerateConfig(max_retries=1))
        await model.generate("hello")
        assert HeadersAPI.attempts == 2
        assert HeadersAPI.last_call is not None
        # the failed attempt's headers must not leak into the successful one
        assert HeadersAPI.last_call.response_headers == {
            "x-sentinel": "allowed",
            "x-attempt": "2",
        }
    finally:
        cleanup()
        del _registry[f"modelapi:{API_NAME}"]


async def test_error_tuple_raises_with_headers() -> None:
    try:
        HeadersAPI.fail_first_with = Retryable("gateway refused")
        HeadersAPI.error_tuple = True
        model = fake_model(GenerateConfig(max_retries=0))
        with pytest.raises(ModelGenerateError) as exc_info:
            await model.generate("hello")
        error = exc_info.value
        assert error.response_headers == {"x-sentinel": "blocked", "x-attempt": "1"}
        # the provider's call for the failed attempt also carries them
        assert HeadersAPI.last_call is not None
        assert HeadersAPI.last_call.response_headers == {
            "x-sentinel": "blocked",
            "x-attempt": "1",
        }
    finally:
        cleanup()
        del _registry[f"modelapi:{API_NAME}"]


async def test_raise_without_call_leaves_headers_readable() -> None:
    try:
        HeadersAPI.fail_first_with = RuntimeError("socket vanished")
        model = fake_model(GenerateConfig(max_retries=0))
        with pytest.raises(RuntimeError, match="socket vanished"):
            await model.generate("hello")
        # no call was produced, but the last recorded headers remain readable
        assert current_response_headers() == {"x-sentinel": "blocked", "x-attempt": "1"}
    finally:
        cleanup()
        del _registry[f"modelapi:{API_NAME}"]
