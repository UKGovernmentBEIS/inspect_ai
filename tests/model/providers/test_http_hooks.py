"""Request tracking in the providers' HTTP hooks.

Each provider that keeps one `HttpHooks` for its lifetime must stop tracking
a request on every exit path, including an error it re-raises and
cancellation; otherwise entries accumulate over a long evaluation.
"""

from typing import Any, Awaitable, Callable, Coroutine, NamedTuple

import anyio
import httpx
import httpx2
import pytest
from botocore.exceptions import EndpointConnectionError

from inspect_ai._util._async import current_async_backend
from inspect_ai.model import ChatMessageUser, GenerateConfig
from inspect_ai.model._providers.util.hooks import HttpHooks

SdkCall = Callable[..., Awaitable[Any]]
Generate = Callable[[], Coroutine[Any, Any, Any]]


class _Case(NamedTuple):
    # build the provider with `sdk_call` in place of its SDK request method
    make: Callable[[pytest.MonkeyPatch, SdkCall], tuple[Generate, HttpHooks]]
    # an error the provider lets propagate from the SDK call
    error: Callable[[], BaseException]


def _generate(api: Any, config: GenerateConfig | None = None) -> Generate:
    return lambda: api.generate(
        input=[ChatMessageUser(content="Hello")],
        tools=[],
        tool_choice="auto",
        config=config or GenerateConfig(),
    )


def _openai_500() -> BaseException:
    from openai import InternalServerError

    request = httpx2.Request("POST", "https://example.com")
    return InternalServerError(
        "server error", response=httpx2.Response(500, request=request), body=None
    )


def _openai_compatible(
    monkeypatch: pytest.MonkeyPatch, sdk_call: SdkCall
) -> tuple[Generate, HttpHooks]:
    from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI

    api = OpenAICompatibleAPI(
        model_name="openai-api/together/test-model",
        api_key="test",
        base_url="https://example.com",
    )
    monkeypatch.setattr(api.client.chat.completions, "create", sdk_call)
    return _generate(api), api._http_hooks


def _openai_compatible_completions(
    monkeypatch: pytest.MonkeyPatch, sdk_call: SdkCall
) -> tuple[Generate, HttpHooks]:
    from inspect_ai.model._providers.openai_compatible_completions import (
        OpenAICompatibleCompletionsAPI,
    )

    api = OpenAICompatibleCompletionsAPI(
        model_name="openai-api-completions/together/test-model",
        api_key="test",
        base_url="https://example.com",
    )
    monkeypatch.setattr(api.client.completions, "create", sdk_call)
    return _generate(api), api._http_hooks


def _openai_responses(
    monkeypatch: pytest.MonkeyPatch, sdk_call: SdkCall
) -> tuple[Generate, HttpHooks]:
    from inspect_ai.model._providers.openai import OpenAIAPI

    api = OpenAIAPI(
        model_name="gpt-5", api_key="test", responses_api=True, streaming=False
    )
    monkeypatch.setattr(api.client.responses, "create", sdk_call)
    # a set reasoning_summary skips the probe request for summary support
    return _generate(api, GenerateConfig(reasoning_summary="auto")), api._http_hooks


def _openai_completions(
    monkeypatch: pytest.MonkeyPatch, sdk_call: SdkCall
) -> tuple[Generate, HttpHooks]:
    from inspect_ai.model._providers.openai import OpenAIAPI

    api = OpenAIAPI(
        model_name="gpt-4o", api_key="test", responses_api=False, streaming=False
    )
    monkeypatch.setattr(api.client.chat.completions, "create", sdk_call)
    return _generate(api), api._http_hooks


def _anthropic(
    monkeypatch: pytest.MonkeyPatch, sdk_call: SdkCall
) -> tuple[Generate, HttpHooks]:
    from inspect_ai.model._providers.anthropic import AnthropicAPI

    api = AnthropicAPI(model_name="claude-sonnet-4-6", api_key="test", streaming=False)
    monkeypatch.setattr(api.client.messages, "create", sdk_call)
    return _generate(api), api._http_hooks


def _anthropic_connection_error() -> BaseException:
    from anthropic import APIConnectionError

    return APIConnectionError(request=httpx2.Request("POST", "https://example.com"))


def _groq(
    monkeypatch: pytest.MonkeyPatch, sdk_call: SdkCall
) -> tuple[Generate, HttpHooks]:
    from inspect_ai.model._providers.groq import GroqAPI

    api = GroqAPI(model_name="llama-3.3-70b", api_key="test", streaming=False)
    monkeypatch.setattr(api.client.chat.completions, "create", sdk_call)
    return _generate(api), api._http_hooks


def _groq_connection_error() -> BaseException:
    from groq import APIConnectionError

    return APIConnectionError(request=httpx.Request("POST", "https://example.com"))


def _bedrock(
    monkeypatch: pytest.MonkeyPatch, sdk_call: SdkCall
) -> tuple[Generate, HttpHooks]:
    from inspect_ai.model._providers.bedrock import BedrockAPI

    if current_async_backend() == "trio":
        pytest.skip("The bedrock provider does not support trio.")

    class _Client:
        converse = staticmethod(sdk_call)

    class _ClientContext:
        async def __aenter__(self) -> _Client:
            return _Client()

        async def __aexit__(self, *exc: Any) -> None:
            return None

    class _Session:
        def create_client(self, **kwargs: Any) -> _ClientContext:
            return _ClientContext()

    api = BedrockAPI(model_name="anthropic.claude-sonnet-4-6", base_url=None)
    monkeypatch.setattr(api, "session", _Session())
    monkeypatch.setattr(api, "streaming", False)
    return _generate(api), api._http_hooks


CASES = {
    "openai-compatible": _Case(_openai_compatible, _openai_500),
    "openai-compatible-completions": _Case(_openai_compatible_completions, _openai_500),
    "openai-responses": _Case(_openai_responses, _openai_500),
    "openai-completions": _Case(_openai_completions, _openai_500),
    "anthropic": _Case(_anthropic, _anthropic_connection_error),
    "groq": _Case(_groq, _groq_connection_error),
    "bedrock": _Case(
        _bedrock, lambda: EndpointConnectionError(endpoint_url="https://example.com")
    ),
}


@pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
async def test_request_untracked_after_raised_error(
    case: _Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = case.error()
    tracked: list[int] = []

    async def sdk_call(*args: Any, **kwargs: Any) -> Any:
        tracked.append(len(hooks._requests))
        raise error

    generate, hooks = case.make(monkeypatch, sdk_call)
    with pytest.raises(type(error)):
        await generate()

    assert tracked == [1]
    assert hooks._requests == {}


@pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
async def test_request_untracked_after_cancellation(
    case: _Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = anyio.Event()
    tracked: list[int] = []

    async def sdk_call(*args: Any, **kwargs: Any) -> Any:
        tracked.append(len(hooks._requests))
        started.set()
        await anyio.sleep_forever()

    generate, hooks = case.make(monkeypatch, sdk_call)
    async with anyio.create_task_group() as tg:
        tg.start_soon(generate)
        await started.wait()
        tg.cancel_scope.cancel()

    assert tracked == [1]
    assert hooks._requests == {}
