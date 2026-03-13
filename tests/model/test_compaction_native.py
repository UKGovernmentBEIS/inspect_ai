"""Tests for the CompactionNative strategy."""

import pytest
from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai._util.content import ContentData, ContentText
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
)
from inspect_ai.model._compaction.native import CompactionNative
from inspect_ai.model._model import get_model
from inspect_ai.model._providers.anthropic import (
    CONTEXT_MANAGEMENT,
    EDITS,
    EXTRA_BODY,
    _add_edit_compation,
    _compaction_from_content_data,
    _compaction_from_message,
)


def _sample_messages() -> list[ChatMessage]:
    """Create a simple message list for testing."""
    return [
        ChatMessageSystem(content="System prompt", id="sys1"),
        ChatMessageUser(content="Hello", id="msg1"),
        ChatMessageAssistant(content="Hi there", id="msg2"),
        ChatMessageUser(content="How are you?", id="msg3"),
        ChatMessageAssistant(content="I'm doing well.", id="msg4"),
    ]


def test_add_edit_compaction_sets_high_trigger_default() -> None:
    """_add_edit_compation sets high trigger for default context (200k)."""
    from typing import Any

    request: dict[str, Any] = {}
    betas: list[str] = []

    _add_edit_compation(request, betas)

    # Verify trigger is set to 190k (just above Anthropic's 150k default)
    edits = request.get(EXTRA_BODY, {}).get(CONTEXT_MANAGEMENT, {}).get(EDITS, [])
    assert len(edits) == 1
    assert edits[0]["trigger"]["type"] == "input_tokens"
    assert edits[0]["trigger"]["value"] == 190_000


def test_add_edit_compaction_sets_high_trigger_1m_context() -> None:
    """_add_edit_compation sets high trigger for 1M context."""
    from typing import Any

    request: dict[str, Any] = {}
    betas = ["context-1m-2025-08-07"]

    _add_edit_compation(request, betas)

    # Verify trigger is set to 990k (just below 1M context limit)
    edits = request.get(EXTRA_BODY, {}).get(CONTEXT_MANAGEMENT, {}).get(EDITS, [])
    assert len(edits) == 1
    assert edits[0]["trigger"]["type"] == "input_tokens"
    assert edits[0]["trigger"]["value"] == 990_000


async def test_native_raises_not_implemented() -> None:
    """CompactionNative raises NotImplementedError on unsupported providers."""
    strategy = CompactionNative()
    model = get_model("mockllm/model")
    messages = _sample_messages()

    with pytest.raises(NotImplementedError):
        await strategy.compact(model, messages, [])


async def test_native_not_implemented_error_includes_token_count() -> None:
    """NotImplementedError message includes token count."""
    strategy = CompactionNative()
    model = get_model("mockllm/model")
    messages = _sample_messages()

    with pytest.raises(NotImplementedError, match=r"tokens"):
        await strategy.compact(model, messages, [])


async def test_native_not_implemented_error_survives_count_tokens_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error message preserves base message even if count_tokens fails."""
    strategy = CompactionNative()
    model = get_model("mockllm/model")
    messages = _sample_messages()

    # Make count_tokens raise an error
    async def failing_count_tokens(input: object, config: object = None) -> int:
        raise RuntimeError("count_tokens failed")

    monkeypatch.setattr(model, "count_tokens", failing_count_tokens)

    with pytest.raises(NotImplementedError) as exc_info:
        await strategy.compact(model, messages, [])

    error_msg = str(exc_info.value)
    # Base error message should be preserved
    assert "not supported" in error_msg.lower() or len(error_msg) > 0
    # Should NOT have token count since counting failed
    assert "tokens" not in error_msg


@skip_if_no_openai
async def test_native_compaction_with_supported_model() -> None:
    """CompactionNative succeeds with a provider that supports native compaction."""
    strategy = CompactionNative()
    model = get_model("openai/gpt-5.1-codex")
    messages = _sample_messages()

    result, summary = await strategy.compact(model, messages, [])

    # Native compaction should return compacted messages
    assert len(result) > 0
    assert isinstance(result, list)

    # Native compaction returns None for the supplemental message
    assert summary is None


@skip_if_no_openai
async def test_native_compaction_dynamically_supported() -> None:
    strategy = CompactionNative()
    model = get_model("openai/gpt-5")
    messages = _sample_messages()

    result, summary = await strategy.compact(model, messages, [])

    # Native compaction should work dynamically via the API
    assert len(result) > 0
    assert isinstance(result, list)

    # Native compaction returns None for the supplemental message
    assert summary is None


# --- Anthropic-specific tests ---


@skip_if_no_anthropic
async def test_anthropic_unsupported_model_raises_not_implemented() -> None:
    """Anthropic models that don't support compaction raise NotImplementedError."""
    # Use an older model that doesn't support compaction
    # This test verifies the BadRequestError -> NotImplementedError conversion
    config = GenerateConfig(max_tokens=4096)
    model = get_model("anthropic/claude-3-haiku-20240307", config=config)
    messages = _long_messages()  # Need enough tokens to pass minimum threshold

    # Direct call to the provider's compact method should raise NotImplementedError
    with pytest.raises(NotImplementedError):
        await model.api.compact(messages, [], model.config)


# --- _compaction_from_message tests ---


def test_compaction_from_message_finds_compaction_after_non_compaction_data() -> None:
    """Compaction block is found even when preceded by non-compaction ContentData."""
    non_compaction = ContentData(data={"other": "stuff"})
    compaction = ContentData(
        data={
            "compaction_metadata": {
                "type": "anthropic_compact",
                "content": "compacted-content-here",
            }
        }
    )
    message = ChatMessageAssistant(content=[non_compaction, compaction], id="msg1")

    result = _compaction_from_message(message)
    assert result is not None
    assert result["type"] == "compaction"
    assert result["content"] == "compacted-content-here"


def test_compaction_from_message_returns_none_for_no_compaction() -> None:
    """Returns None when message has no compaction ContentData."""
    message = ChatMessageAssistant(
        content=[
            ContentText(text="hello"),
            ContentData(data={"other": "stuff"}),
        ],
        id="msg1",
    )

    assert _compaction_from_message(message) is None


def test_compaction_from_message_returns_none_for_string_content() -> None:
    """Returns None when message content is a plain string."""
    message = ChatMessageAssistant(content="just a string", id="msg1")

    assert _compaction_from_message(message) is None


def test_compaction_from_content_data_with_none_content() -> None:
    """Returns BetaCompactionBlockParam with content=None when content key is None."""
    content = ContentData(
        data={
            "compaction_metadata": {
                "type": "anthropic_compact",
                "content": None,
            }
        }
    )

    result = _compaction_from_content_data(content)
    assert result is not None
    assert result["type"] == "compaction"
    assert result["content"] is None


@pytest.mark.parametrize("bad_content", [{"key": "val"}, [1, 2, 3], 42])
def test_compaction_from_content_data_with_non_string_content(
    bad_content: object,
) -> None:
    """Non-string content is treated as None with a warning, not coerced to string."""
    content = ContentData(
        data={
            "compaction_metadata": {
                "type": "anthropic_compact",
                "content": bad_content,  # type: ignore[dict-item]
            }
        }
    )

    result = _compaction_from_content_data(content)
    assert result is not None
    assert result["type"] == "compaction"
    assert result["content"] is None


def _long_messages() -> list[ChatMessage]:
    """Create a message list with enough tokens to meet the minimum compaction threshold.

    Anthropic requires minimum 50k tokens for compaction trigger.
    With trigger at 90%, we need ~56k tokens total.
    """
    # Each repetition is ~20 tokens, so 100 reps = ~2000 tokens per message
    long_text = (
        "This is a detailed explanation of various topics including science, "
        "mathematics, history, and philosophy. " * 100
    ).strip()
    messages: list[ChatMessage] = [
        ChatMessageSystem(content="You are a helpful assistant.", id="sys1"),
    ]
    # 30 pairs * ~4000 tokens per pair = ~120k tokens (well above 56k minimum)
    for i in range(30):
        messages.append(ChatMessageUser(content=long_text, id=f"user_{i}"))
        messages.append(
            ChatMessageAssistant(content=f"Response {i}: {long_text}", id=f"asst_{i}")
        )
    # End with user message so API can respond
    messages.append(ChatMessageUser(content="Please continue.", id="final_user"))
    return messages
