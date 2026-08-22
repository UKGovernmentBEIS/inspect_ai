"""Regression tests for Bedrock Converse prompt caching."""

from __future__ import annotations

import json
from typing import Any, Literal, cast

import pytest

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from inspect_ai.model import (  # noqa: E402
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig  # noqa: E402
from inspect_ai.model._providers.bedrock import (  # noqa: E402
    BedrockAPI,
    ConverseResponse,
    model_output_from_response,
)
from inspect_ai.tool import ToolInfo  # noqa: E402


class _FakeClient:
    def __init__(self) -> None:
        self.request: dict[str, Any] | None = None

    async def converse(self, **request: Any) -> dict[str, Any]:
        self.request = request
        return _response()


class _FakeClientContext:
    def __init__(self, client: _FakeClient) -> None:
        self.client = client

    async def __aenter__(self) -> _FakeClient:
        return self.client

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None


class _FakeSession:
    def __init__(self, client: _FakeClient) -> None:
        self.client_instance = client

    def client(self, **kwargs: Any) -> _FakeClientContext:
        return _FakeClientContext(self.client_instance)


class _FakeHooks:
    def start_request(self) -> str:
        return "request-id"

    def user_agent_extra(self, request_id: str) -> str:
        return f"test/{request_id}"

    def end_request(self, request_id: str) -> float:
        return 0.0


def _response(
    *, cache_read: int | None = None, cache_write: int | None = None
) -> dict[str, Any]:
    usage: dict[str, int] = {
        "inputTokens": 11,
        "outputTokens": 7,
        "totalTokens": 18 + (cache_read or 0) + (cache_write or 0),
    }
    if cache_read is not None:
        usage["cacheReadInputTokens"] = cache_read
    if cache_write is not None:
        usage["cacheWriteInputTokens"] = cache_write
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
        "stopReason": "end_turn",
        "usage": usage,
        "metrics": {"latencyMs": 1},
    }


def _make_api(model_name: str) -> tuple[BedrockAPI, _FakeClient]:
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = model_name
    api.base_url = None
    api.model_args = {}
    api.read_timeout = 60
    api.connect_timeout = 60
    client = _FakeClient()
    api.session = cast(Any, _FakeSession(client))
    api._http_hooks = cast(Any, _FakeHooks())
    return api, client


async def _request(
    *,
    model_name: str = "anthropic.claude-sonnet-4-6",
    input: list[ChatMessageSystem | ChatMessageUser | ChatMessageAssistant],
    config: GenerateConfig = GenerateConfig(),
    tools: list[ToolInfo] = [],
) -> dict[str, Any]:
    api, client = _make_api(model_name)
    await api.generate(cast(Any, input), tools, "auto", config)
    assert client.request is not None
    return client.request


@pytest.mark.parametrize(
    "model_name",
    [
        "anthropic.claude-3-5-haiku-20241022-v1:0",
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "anthropic.claude-3-7-sonnet-20250219-v1:0",
        "anthropic.claude-sonnet-4-6",
        "amazon.nova-pro-v1:0",
    ],
)
@pytest.mark.parametrize("cache_prompt", [None, "auto", True])
async def test_cache_prompt_marks_stable_message_prefix_by_default(
    model_name: str, cache_prompt: Literal["auto"] | bool | None
) -> None:
    request = await _request(
        model_name=model_name,
        input=[
            ChatMessageUser(content="stable context"),
            ChatMessageAssistant(content="stable answer"),
            ChatMessageUser(content="dynamic question"),
        ],
        config=GenerateConfig(cache_prompt=cache_prompt),
    )

    assert request["messages"][1]["content"][-1] == {"cachePoint": {"type": "default"}}
    assert "cachePoint" not in json.dumps(request["messages"][2])


async def test_cache_prompt_false_preserves_request_shape() -> None:
    request = await _request(
        input=[
            ChatMessageUser(content="stable context"),
            ChatMessageAssistant(content="stable answer"),
            ChatMessageUser(content="dynamic question"),
        ],
        config=GenerateConfig(cache_prompt=False),
    )

    assert "cachePoint" not in json.dumps(request)


@pytest.mark.parametrize(
    "model_name",
    [
        "meta.llama3-1-70b-instruct-v1:0",
        "anthropic.claude-3-sonnet-20240229-v1:0",
        "anthropic.claude-3-haiku-20240307-v1:0",
        "anthropic.claude-3-opus-20240229-v1:0",
        "anthropic.claude-3-5-sonnet-20240620-v1:0",
    ],
)
async def test_unsupported_models_preserve_request_shape(model_name: str) -> None:
    request = await _request(
        model_name=model_name,
        input=[
            ChatMessageUser(content="stable context"),
            ChatMessageAssistant(content="stable answer"),
            ChatMessageUser(content="dynamic question"),
        ],
    )

    assert "cachePoint" not in json.dumps(request)


async def test_single_dynamic_message_preserves_request_shape() -> None:
    request = await _request(input=[ChatMessageUser(content="dynamic question")])

    assert "cachePoint" not in json.dumps(request)


async def test_cache_prompt_falls_back_to_system_prefix() -> None:
    request = await _request(
        input=[
            ChatMessageSystem(content="stable instructions"),
            ChatMessageUser(content="dynamic question"),
        ]
    )

    assert request["system"][-1] == {"cachePoint": {"type": "default"}}
    assert "cachePoint" not in json.dumps(request["messages"])


async def test_cache_prompt_falls_back_to_tools_prefix() -> None:
    request = await _request(
        input=[ChatMessageUser(content="dynamic question")],
        tools=[ToolInfo(name="lookup", description="Look up a value")],
    )

    assert request["toolConfig"]["tools"][-1] == {"cachePoint": {"type": "default"}}
    assert "cachePoint" not in json.dumps(request["messages"])


async def test_nova_does_not_fall_back_to_unsupported_tools_prefix() -> None:
    request = await _request(
        model_name="amazon.nova-pro-v1:0",
        input=[ChatMessageUser(content="dynamic question")],
        tools=[ToolInfo(name="lookup", description="Look up a value")],
    )

    assert "cachePoint" not in json.dumps(request)


def test_cache_usage_is_preserved_and_counted_in_total() -> None:
    response = ConverseResponse.model_validate(_response(cache_read=13, cache_write=17))

    usage = model_output_from_response("model", response, []).usage

    assert usage is not None
    assert usage.input_tokens == 11
    assert usage.input_tokens_cache_read == 13
    assert usage.input_tokens_cache_write == 17
    assert usage.output_tokens == 7
    assert usage.total_tokens == 48


def test_missing_cache_usage_fields_remain_compatible() -> None:
    response = ConverseResponse.model_validate(_response())

    usage = model_output_from_response("model", response, []).usage

    assert usage is not None
    assert usage.input_tokens_cache_read is None
    assert usage.input_tokens_cache_write is None
    assert usage.total_tokens == 18


def test_zero_cache_usage_fields_are_preserved() -> None:
    response = ConverseResponse.model_validate(_response(cache_read=0, cache_write=0))

    usage = model_output_from_response("model", response, []).usage

    assert usage is not None
    assert usage.input_tokens_cache_read == 0
    assert usage.input_tokens_cache_write == 0
    assert usage.total_tokens == 18
