"""Tests for the OpenRouter provider's Anthropic prompt-caching support."""

import json
from typing import Any

import pytest

from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.model._providers.openrouter import (
    OpenRouterAPI,
    _add_anthropic_cache_markers,
    _apply_cache_creation_usage,
)

EPHEMERAL: dict[str, str] = {"type": "ephemeral"}


def _has_cache_control(block: Any) -> bool:
    return isinstance(block, dict) and block.get("cache_control") == EPHEMERAL


def _make_api(model_name: str, **kwargs: Any) -> OpenRouterAPI:
    return OpenRouterAPI(model_name=model_name, api_key="test-key", **kwargs)


def _make_output(
    input_tokens: int = 500,
    output_tokens: int = 20,
    total_tokens: int = 520,
    input_tokens_cache_read: int | None = None,
) -> ModelOutput:
    return ModelOutput(
        model="claude-sonnet-4-5",
        choices=[],
        usage=ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            input_tokens_cache_read=input_tokens_cache_read,
        ),
    )


def test_add_cache_markers_system_tool_and_penultimate_block() -> None:
    """System + tools + multi-block last user message: 3 markers placed."""
    request: dict[str, Any] = {
        "messages": [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "system part 1"},
                    {"type": "text", "text": "system part 2"},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "user block 0"},
                    {"type": "text", "text": "user block 1"},
                    {"type": "text", "text": "user block 2"},
                ],
            },
        ],
        "tools": [
            {"type": "function", "function": {"name": "a"}},
            {"type": "function", "function": {"name": "b"}},
        ],
    }

    _add_anthropic_cache_markers(request)

    # last system block marked
    assert _has_cache_control(request["messages"][0]["content"][-1])
    assert "cache_control" not in request["messages"][0]["content"][0]
    # penultimate block of last (user) message marked
    user_blocks = request["messages"][1]["content"]
    assert _has_cache_control(user_blocks[-2])  # block 1 (penultimate)
    assert "cache_control" not in user_blocks[-1]  # auto-cache covers the last
    assert "cache_control" not in user_blocks[0]
    # last tool marked at top level (alongside "type": "function")
    assert request["tools"][1]["cache_control"] == EPHEMERAL
    assert "cache_control" not in request["tools"][0]


def test_add_cache_markers_fallback_to_previous_message() -> None:
    """Single-block last message → mark the last block of the previous message."""
    request: dict[str, Any] = {
        "messages": [
            {"role": "user", "content": "earlier context"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "reply part 1"},
                    {"type": "text", "text": "reply part 2"},
                ],
            },
            {"role": "user", "content": "follow-up"},
        ]
    }

    _add_anthropic_cache_markers(request)

    # last block of the previous (assistant) message marked
    assistant_blocks = request["messages"][1]["content"]
    assert _has_cache_control(assistant_blocks[-1])
    assert "cache_control" not in assistant_blocks[0]


def test_add_cache_markers_string_content_converted_to_list() -> None:
    """String-content system message gets converted to a single-block list with marker."""
    request: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": "you are helpful"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "block 0"},
                    {"type": "text", "text": "block 1"},
                ],
            },
        ]
    }

    _add_anthropic_cache_markers(request)

    sys_content = request["messages"][0]["content"]
    assert isinstance(sys_content, list)
    assert len(sys_content) == 1
    assert sys_content[0]["text"] == "you are helpful"
    assert sys_content[0]["cache_control"] == EPHEMERAL


def test_add_cache_markers_fallback_does_not_convert_string_content() -> None:
    """Fallback branch must NOT convert string content on the previous message.

    Mirrors `anthropic.py:1208-1211`: when the last message has fewer than 2
    blocks and we fall back to marking the previous message, the previous
    message's string content must stay a string (it may be a `role:"tool"`
    message whose content shape matters for upstream tool_result translation).
    """
    request: dict[str, Any] = {
        "messages": [
            {"role": "user", "content": "do the thing"},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "calling tool"}],
                "tool_calls": [{"id": "call_1"}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "tool result"},
            {"role": "user", "content": "thanks"},
        ]
    }

    _add_anthropic_cache_markers(request)

    # the previous (tool) message's string content must remain a string
    assert request["messages"][2]["content"] == "tool result"
    # and no marker is placed on it (fallback only marks list content)
    assert "cache_control" not in request["messages"][2]


def test_add_cache_markers_single_message_no_marker() -> None:
    """Single message with single block (no previous message) → no marker placed."""
    request: dict[str, Any] = {
        "messages": [{"role": "user", "content": "lone message"}]
    }

    _add_anthropic_cache_markers(request)

    # content stays as a string (no list conversion since nothing to mark)
    assert request["messages"][0]["content"] == "lone message"


def test_add_cache_markers_no_tools_no_messages() -> None:
    """Empty/missing fields handled without error."""
    request: dict[str, Any] = {}
    _add_anthropic_cache_markers(request)
    assert request == {}


def test_cache_prompt_enabled_for_anthropic_model_by_default() -> None:
    api = _make_api("openrouter/anthropic/claude-sonnet-4-5")
    assert api._cache_prompt_enabled(GenerateConfig()) is True


def test_cache_prompt_enabled_handles_openrouter_suffix() -> None:
    """`:thinking` and similar suffixes don't break the gating."""
    api = _make_api("openrouter/anthropic/claude-opus-4.1:thinking")
    assert api._cache_prompt_enabled(GenerateConfig()) is True


def test_cache_prompt_disabled_for_non_anthropic_model() -> None:
    api = _make_api("openrouter/openai/gpt-4o-mini")
    assert api._cache_prompt_enabled(GenerateConfig()) is False


def test_cache_prompt_disabled_when_config_false() -> None:
    api = _make_api("openrouter/anthropic/claude-sonnet-4-5")
    assert api._cache_prompt_enabled(GenerateConfig(cache_prompt=False)) is False


def test_cache_prompt_enabled_when_config_auto() -> None:
    """`cache_prompt="auto"` enables caching (matches direct anthropic provider)."""
    api = _make_api("openrouter/anthropic/claude-sonnet-4-5")
    assert api._cache_prompt_enabled(GenerateConfig(cache_prompt="auto")) is True


@pytest.mark.parametrize(
    "model",
    [
        "openrouter/anthropic/claude-3-sonnet-20240229",
        "openrouter/anthropic/claude-2.1",
        "openrouter/anthropic/claude-instant-1.2",
    ],
)
def test_cache_prompt_disabled_for_legacy_claude(model: str) -> None:
    api = _make_api(model)
    assert api._cache_prompt_enabled(GenerateConfig()) is False


def test_apply_cache_creation_usage_sets_write_and_adjusts_input() -> None:
    output = _make_output(input_tokens_cache_read=100)
    call = ModelCall(
        request={}, response={"usage": {"cache_creation_input_tokens": 80}}
    )

    _apply_cache_creation_usage(output, call)

    assert output.usage is not None
    assert output.usage.input_tokens_cache_write == 80
    # 500 - 80 = 420 (the base already subtracted cache_read from input_tokens)
    assert output.usage.input_tokens == 420


def test_apply_cache_creation_usage_reads_openrouter_shape() -> None:
    """OpenRouter surfaces cache writes under prompt_tokens_details.cache_write_tokens.

    Live runs against `openrouter/anthropic/*` returned the cache-write count in
    OpenAI-extension shape rather than Anthropic's native `cache_creation_input_tokens`
    key, so the helper must read both.
    """
    output = _make_output(input_tokens_cache_read=100)
    call = ModelCall(
        request={},
        response={"usage": {"prompt_tokens_details": {"cache_write_tokens": 80}}},
    )

    _apply_cache_creation_usage(output, call)

    assert output.usage is not None
    assert output.usage.input_tokens_cache_write == 80
    assert output.usage.input_tokens == 420


def test_apply_cache_creation_usage_prefers_anthropic_native_key() -> None:
    """When both shapes are present, the Anthropic-native key wins (future-proofing)."""
    output = _make_output()
    call = ModelCall(
        request={},
        response={
            "usage": {
                "cache_creation_input_tokens": 80,
                "prompt_tokens_details": {"cache_write_tokens": 999},
            }
        },
    )

    _apply_cache_creation_usage(output, call)

    assert output.usage is not None
    assert output.usage.input_tokens_cache_write == 80


def test_apply_cache_creation_usage_noop_when_field_missing() -> None:
    output = _make_output()
    call = ModelCall(request={}, response={"usage": {"prompt_tokens": 500}})

    _apply_cache_creation_usage(output, call)

    assert output.usage is not None
    assert output.usage.input_tokens_cache_write is None
    assert output.usage.input_tokens == 500


def test_apply_cache_creation_usage_noop_when_no_call() -> None:
    output = _make_output()

    _apply_cache_creation_usage(output, None)

    assert output.usage is not None
    assert output.usage.input_tokens_cache_write is None
    assert output.usage.input_tokens == 500


@pytest.mark.anyio
async def test_messages_to_openai_gemini_replays_encrypted_structurally() -> None:
    """Gemini text+encrypted reasoning replays as structural reasoning_details.

    The unsigned readable text is dropped (it is unverifiable on replay) and
    the encrypted continuity blob is kept. Nothing is serialized into the
    assistant text channel — no <think> tag, no HTML-escaped signature blob,
    no encrypted payload as text.
    """
    from inspect_ai._util.content import ContentReasoning
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.model._providers.openrouter import (
        OPENROUTER_REASONING_DETAILS_SIGNATURE,
    )

    readable_text = (
        "I've determined the most direct path forward involves the run_bash tool."
    )
    encrypted_blob = "CjcBjz1rXxKfW2fJuqbBlfGrk8wxR..."
    signature = OPENROUTER_REASONING_DETAILS_SIGNATURE + json.dumps(
        [
            {
                "type": "reasoning.text",
                "text": readable_text,
                "format": "google-gemini-v1",
                "index": 0,
            },
            {
                "type": "reasoning.encrypted",
                "data": encrypted_blob,
                "format": "google-gemini-v1",
                "id": "tool_X",
                "index": 1,
            },
        ]
    )
    msg = ChatMessageAssistant(
        content=[
            ContentReasoning(
                reasoning=encrypted_blob,
                summary=readable_text,
                redacted=True,
                signature=signature,
            )
        ],
    )

    api = _make_api("google/gemini-2.5-flash")
    converted = await api.messages_to_openai([msg])

    payload = converted[0]
    # structural replay: only the encrypted entry survives
    assert "reasoning_details" in payload
    details = payload["reasoning_details"]  # type: ignore[typeddict-item]
    assert [d["type"] for d in details] == ["reasoning.encrypted"]
    assert details[0]["data"] == encrypted_blob
    # nothing leaks into the text channel
    serialized = json.dumps(payload)
    assert "<think" not in serialized
    assert "&quot;" not in serialized
    assert "reasoning-details://" not in serialized
    # readable text was dropped (unsigned, unverifiable)
    assert readable_text not in serialized


@pytest.mark.anyio
async def test_messages_to_openai_gemini_unsigned_text_only_dropped() -> None:
    """Unsigned text-only Gemini reasoning is dropped, leaving empty details.

    Matching OpenRouter's SDK, an unsigned reasoning.text (default format
    anthropic-claude-v1, a signed format) with no encrypted companion is
    filtered out; the empty array is preserved rather than replayed as text.
    In real traffic Gemini signs a terminal-turn thought, so this synthetic
    edge case is what keeps an unverifiable thought out of the channel.
    """
    from inspect_ai._util.content import ContentReasoning
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.model._providers.openrouter import (
        OPENROUTER_REASONING_DETAILS_SIGNATURE,
    )

    signature = OPENROUTER_REASONING_DETAILS_SIGNATURE + (
        '[{"type": "reasoning.text", "text": "Step by step reasoning here.", "id": "r1"}]'
    )
    msg = ChatMessageAssistant(
        content=[
            ContentReasoning(
                reasoning="Step by step reasoning here.",
                redacted=False,
                signature=signature,
            )
        ],
    )

    api = _make_api("google/gemini-2.5-pro")
    converted = await api.messages_to_openai([msg])

    payload = converted[0]
    assert "reasoning_details" in payload
    assert payload["reasoning_details"] == []  # type: ignore[typeddict-item]
    serialized = json.dumps(payload)
    assert "<think" not in serialized
    assert "Step by step reasoning here." not in serialized


@pytest.mark.anyio
async def test_messages_to_openai_replays_encrypted_details_for_gemini() -> None:
    """Gemini-family models replay the encrypted reasoning detail structurally.

    The encrypted entry carries the thought signature Gemini needs for
    multi-turn tool continuity, so it is sent as reasoning_details rather than
    dropped or serialized into the assistant text channel.
    """
    from inspect_ai._util.content import ContentReasoning
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.model._providers.openrouter import (
        OPENROUTER_REASONING_DETAILS_SIGNATURE,
    )

    signature = OPENROUTER_REASONING_DETAILS_SIGNATURE + json.dumps(
        [
            {
                "type": "reasoning.encrypted",
                "data": "ENCRYPTED",
                "format": "google-gemini-v1",
                "id": "tool_X",
            }
        ]
    )
    msg = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="ENCRYPTED", redacted=True, signature=signature)
        ],
    )

    api = _make_api("google/gemini-3-pro-preview")
    converted = await api.messages_to_openai([msg])

    payload = converted[0]
    assert "reasoning_details" in payload
    details = payload["reasoning_details"]  # type: ignore[typeddict-item]
    assert [d["type"] for d in details] == ["reasoning.encrypted"]
    assert "<think" not in json.dumps(payload)


@pytest.mark.anyio
async def test_messages_to_openai_preserves_reasoning_details_for_non_gemini() -> None:
    """Anthropic/Grok/OpenAI signed reasoning replay must be left intact."""
    from inspect_ai._util.content import ContentReasoning
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.model._providers.openrouter import (
        OPENROUTER_REASONING_DETAILS_SIGNATURE,
    )

    original = [
        {
            "type": "reasoning.text",
            "text": "considered options",
            "format": "anthropic-claude-v1",
            "signature": "sig-abc",
            "id": "r1",
        }
    ]
    signature = OPENROUTER_REASONING_DETAILS_SIGNATURE + json.dumps(original)
    msg = ChatMessageAssistant(
        content=[ContentReasoning(reasoning="considered options", signature=signature)],
    )

    api = _make_api("anthropic/claude-sonnet-4-5")
    converted = await api.messages_to_openai([msg])

    payload = converted[0]
    assert "reasoning_details" in payload
    # signed text survives the filter unchanged
    assert payload["reasoning_details"] == original  # type: ignore[typeddict-item]


@pytest.mark.anyio
async def test_messages_to_openai_replays_reasoning_content_for_deepseek_v4() -> None:
    """DeepSeek v4 requires reasoning_content, and keeps surviving details.

    Its reasoning uses a non-signed format (`deepseek-v1`), so the sanitizer
    leaves the text entry intact; both `reasoning_content` and the structural
    `reasoning_details` must reach the wire.
    """
    from inspect_ai._util.content import ContentReasoning
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.model._providers.openrouter import (
        OPENROUTER_REASONING_DETAILS_SIGNATURE,
    )

    original = [
        {
            "type": "reasoning.text",
            "text": "considered options",
            "format": "deepseek-v1",
            "id": "r1",
        }
    ]
    signature = OPENROUTER_REASONING_DETAILS_SIGNATURE + json.dumps(original)
    msg = ChatMessageAssistant(
        content=[ContentReasoning(reasoning="considered options", signature=signature)],
    )

    api = _make_api("deepseek/deepseek-v4-pro")
    converted = await api.messages_to_openai([msg])

    payload = converted[0]
    assert payload["reasoning_content"] == "considered options"  # type: ignore[typeddict-item]
    assert payload["reasoning_details"] == original  # type: ignore[typeddict-item]


@pytest.mark.anyio
async def test_messages_to_openai_reasoning_content_without_details_for_deepseek() -> (
    None
):
    """DeepSeek reasoning that has no OpenRouter details still sends content."""
    from inspect_ai._util.content import ContentReasoning
    from inspect_ai.model._chat_message import ChatMessageAssistant

    msg = ChatMessageAssistant(
        content=[ContentReasoning(reasoning="plain cot", signature="rs_x")],
    )

    api = _make_api("deepseek/deepseek-v4-pro")
    converted = await api.messages_to_openai([msg])

    payload = converted[0]
    assert payload["reasoning_content"] == "plain cot"  # type: ignore[typeddict-item]
    assert "reasoning_details" not in payload


@pytest.mark.anyio
async def test_messages_to_openai_think_tag_fallback_for_non_gemini() -> None:
    """Reasoning without OpenRouter details replays as a <think> tag.

    For a non-Gemini, non-DeepSeek model, reasoning that was not captured as
    OpenRouter reasoning_details (e.g. parsed from a `<think>` tag) is still
    serialized back into a `<think>` tag carrying the readable text.
    """
    from inspect_ai._util.content import ContentReasoning
    from inspect_ai.model._chat_message import ChatMessageAssistant

    msg = ChatMessageAssistant(
        content=[ContentReasoning(reasoning="visible chain of thought")],
    )

    api = _make_api("x-ai/grok-4")
    converted = await api.messages_to_openai([msg])

    payload = converted[0]
    content = payload.get("content")
    text = content if isinstance(content, str) else ""
    assert "<think" in text
    assert "visible chain of thought" in text
    assert "</think>" in text
    assert "reasoning_details" not in payload
