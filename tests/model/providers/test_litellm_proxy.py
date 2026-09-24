"""Tests for the LiteLLM proxy provider.

Most run against a local LiteLLM proxy in Docker. The proxy runs from a locally
available image with a mock-response config, so these tests need no network
access or provider keys (see `test_helpers.litellm_proxy.proxy`). The
reasoning conversion tests below need no proxy; round trips through a proxy
are in `test_litellm_proxy_reasoning.py`.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from test_helpers.litellm_proxy.proxy import (
    LiteLLMProxy,
    run_litellm_proxy,
    skip_if_no_litellm_proxy,
)
from test_helpers.utils import skip_if_no_openai_package

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    Model,
    get_model,
)
from inspect_ai.model._providers._litellm_proxy_reasoning import (
    ThinkingBlocksAccumulator,
)
from inspect_ai.model._providers.litellm_proxy import (
    LITELLM_PROXY_BASE_URL,
    LiteLLMProxyAPI,
)

MOCK_MODEL = "mock-model"
MOCK_RESPONSE = "Hello from the mock proxy"

PROXY_CONFIG: dict[str, Any] = {
    "model_list": [
        {
            "model_name": MOCK_MODEL,
            "litellm_params": {
                "model": f"openai/{MOCK_MODEL}",
                "api_key": "fake",
                "mock_response": MOCK_RESPONSE,
            },
            "model_info": {
                "max_input_tokens": 200000,
                "max_output_tokens": 8192,
                "supports_reasoning": True,
            },
        }
    ]
}


@pytest.fixture(scope="module")
def litellm_proxy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LiteLLMProxy]:
    with run_litellm_proxy(tmp_path_factory.mktemp("litellm"), PROXY_CONFIG) as proxy:
        yield proxy


def _proxy_model(proxy: LiteLLMProxy, **model_args: Any) -> Model:
    return get_model(
        f"litellm-proxy/{MOCK_MODEL}",
        base_url=proxy.base_url,
        api_key=proxy.api_key,
        config=GenerateConfig(max_retries=0),
        **model_args,
    )


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_litellm_proxy_generate(litellm_proxy: LiteLLMProxy) -> None:
    output = await _proxy_model(litellm_proxy).generate("Hello")
    assert output.completion == MOCK_RESPONSE


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_litellm_proxy_generate_responses_api(
    litellm_proxy: LiteLLMProxy,
) -> None:
    output = await _proxy_model(litellm_proxy, responses_api=True).generate("Hello")
    assert output.completion == MOCK_RESPONSE


@skip_if_no_litellm_proxy
def test_litellm_proxy_model_info(litellm_proxy: LiteLLMProxy) -> None:
    response = httpx.get(
        f"{litellm_proxy.base_url}/model/info",
        headers={"Authorization": f"Bearer {litellm_proxy.api_key}"},
    )
    response.raise_for_status()
    [model] = response.json()["data"]
    assert model["model_name"] == MOCK_MODEL
    assert model["model_info"]["max_input_tokens"] == 200000
    assert model["model_info"]["max_output_tokens"] == 8192
    assert model["model_info"]["supports_reasoning"] is True


@skip_if_no_openai_package
def test_litellm_proxy_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LITELLM_PROXY_BASE_URL, raising=False)
    with pytest.raises(PrerequisiteError, match=LITELLM_PROXY_BASE_URL):
        get_model(f"litellm-proxy/{MOCK_MODEL}", api_key="key")


# Reasoning conversion ---------------------------------------------------------

THINKING = {"type": "thinking", "thinking": "Let me think.", "signature": "sig-1"}
REDACTED = {"type": "redacted_thinking", "data": "opaque-1"}
TOOL_CALL = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "get_weather", "arguments": '{"city": "Oslo"}'},
}


def _provider() -> LiteLLMProxyAPI:
    api = get_model(
        "litellm-proxy/claude", base_url="http://localhost:4000/v1", api_key="key"
    ).api
    assert isinstance(api, LiteLLMProxyAPI)
    return api


def _completion(message: dict[str, Any]) -> Any:
    from openai.types.chat import ChatCompletion

    return ChatCompletion.model_validate(
        {
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "claude",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {"role": "assistant"} | message,
                }
            ],
        }
    )


def _assistant(message: dict[str, Any]) -> ChatMessageAssistant:
    [choice] = _provider().chat_choices_from_completion(_completion(message), [])
    return choice.message


@skip_if_no_openai_package
def test_litellm_proxy_reads_thinking_blocks() -> None:
    message = _assistant(
        {
            "content": "Checking.",
            # LiteLLM's reasoning_content is the text of the blocks
            "reasoning_content": "Let me think.",
            "thinking_blocks": [THINKING, REDACTED],
            "tool_calls": [TOOL_CALL],
        }
    )
    assert message.content == [
        ContentReasoning(
            reasoning="Let me think.", signature="sig-1", internal="thinking_blocks"
        ),
        ContentReasoning(
            reasoning="opaque-1", redacted=True, internal="thinking_blocks"
        ),
        ContentText(text="Checking."),
    ]


@skip_if_no_openai_package
def test_litellm_proxy_reads_redacted_only_thinking() -> None:
    message = _assistant({"content": "Done.", "thinking_blocks": [REDACTED]})
    assert message.content == [
        ContentReasoning(
            reasoning="opaque-1", redacted=True, internal="thinking_blocks"
        ),
        ContentText(text="Done."),
    ]


@skip_if_no_openai_package
def test_litellm_proxy_reads_thought_signatures() -> None:
    message = _assistant(
        {
            "content": "Answer.",
            "reasoning_content": "Thought summary.",
            "provider_specific_fields": {"thought_signatures": ["gsig-1"]},
        }
    )
    assert message.content == [
        ContentReasoning(
            reasoning="gsig-1", redacted=True, internal="thought_signatures"
        ),
        ContentReasoning(reasoning="Thought summary.", internal="reasoning_content"),
        ContentText(text="Answer."),
    ]


@skip_if_no_openai_package
async def test_litellm_proxy_replays_litellm_reasoning_fields() -> None:
    provider = _provider()
    returned = {
        "content": "Answer.",
        "reasoning_content": "Let me think.",
        "thinking_blocks": [THINKING, REDACTED],
        "provider_specific_fields": {"thought_signatures": ["gsig-1"]},
        "tool_calls": [TOOL_CALL],
    }
    message = _assistant(returned)
    [_, replayed] = await provider.messages_to_openai(
        [ChatMessageUser(content="Hi"), message]
    )
    assert replayed["role"] == "assistant"
    replayed_dict = dict(replayed)
    assert replayed_dict["thinking_blocks"] == returned["thinking_blocks"]
    assert replayed_dict["reasoning_content"] == "Let me think."
    assert replayed_dict["provider_specific_fields"] == {
        "thought_signatures": ["gsig-1"]
    }
    # reasoning is not also written into the text
    assert "<think>" not in str(replayed_dict["content"])
    assert "opaque-1" not in str(replayed_dict["content"])


@skip_if_no_openai_package
async def test_litellm_proxy_replays_reasoning_content_unchanged() -> None:
    # open models return reasoning_content only, which goes back as is
    message = _assistant({"content": "Answer.", "reasoning_content": "Because."})
    [replayed] = await _provider().messages_to_openai([message])
    replayed_dict = dict(replayed)
    assert replayed_dict["reasoning_content"] == "Because."
    assert "thinking_blocks" not in replayed_dict


def _accumulate(*entries: dict[str, Any]) -> list[dict[str, Any]]:
    accumulator = ThinkingBlocksAccumulator()
    for entry in entries:
        accumulator.add(entry)
    return accumulator.blocks()


def test_thinking_blocks_accumulator_signature_repeats_text() -> None:
    # current LiteLLM: the signature entry repeats the block's full text
    assert _accumulate(
        {"type": "thinking", "thinking": "Let me "},
        {"type": "thinking", "thinking": "think."},
        {"type": "thinking", "thinking": "Let me think.", "signature": "sig-1"},
    ) == [THINKING]


def test_thinking_blocks_accumulator_signature_without_text() -> None:
    assert _accumulate(
        {"type": "thinking", "thinking": "Let me "},
        {"type": "thinking", "thinking": "think."},
        {"type": "thinking", "signature": "sig-1"},
    ) == [THINKING]


def test_thinking_blocks_accumulator_signature_with_last_delta() -> None:
    assert _accumulate(
        {"type": "thinking", "thinking": "Let me "},
        {"type": "thinking", "thinking": "think.", "signature": "sig-1"},
    ) == [THINKING]


def test_thinking_blocks_accumulator_separates_blocks() -> None:
    assert _accumulate(
        REDACTED,
        {"type": "thinking", "thinking": "Let me think."},
        {"type": "thinking", "thinking": "Let me think.", "signature": "sig-1"},
        {"type": "redacted_thinking", "data": "opaque-2"},
        {"type": "thinking", "thinking": "Unsigned."},
    ) == [
        REDACTED,
        THINKING,
        {"type": "redacted_thinking", "data": "opaque-2"},
        {"type": "thinking", "thinking": "Unsigned."},
    ]


def _chunk(delta: dict[str, Any], finish_reason: str | None = None) -> Any:
    from openai.types.chat import ChatCompletionChunk

    return ChatCompletionChunk.model_validate(
        {
            "id": "c1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "claude",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
    )


@skip_if_no_openai_package
async def test_litellm_proxy_streams_thinking_blocks() -> None:
    def thinking(entry: dict[str, Any], reasoning_content: str) -> dict[str, Any]:
        # LiteLLM sends each entry both on the delta and in its
        # provider_specific_fields
        return {
            "reasoning_content": reasoning_content,
            "thinking_blocks": [entry],
            "provider_specific_fields": {"thinking_blocks": [entry]},
        }

    chunks = [
        _chunk({"role": "assistant"} | thinking(REDACTED, "")),
        _chunk(thinking({"type": "thinking", "thinking": "Let me "}, "Let me ")),
        _chunk(thinking({"type": "thinking", "thinking": "think."}, "think.")),
        _chunk(thinking(THINKING, "")),
        _chunk({"content": "Answer."}, finish_reason="stop"),
    ]

    async def stream() -> AsyncIterator[Any]:
        for chunk in chunks:
            yield chunk

    completion = await _provider().stream_completion(stream())
    message = completion.choices[0].message
    assert message.model_extra is not None
    assert message.model_extra["thinking_blocks"] == [REDACTED, THINKING]
    assert message.model_extra.get("provider_specific_fields") == {}
    assert getattr(message, "reasoning_content") == "Let me think."
    assert message.content == "Answer."
