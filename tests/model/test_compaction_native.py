"""Tests for the CompactionNative strategy."""

import pytest
from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
)
from inspect_ai.model._compaction.edit import CompactionEdit
from inspect_ai.model._compaction.native import CompactionNative
from inspect_ai.model._model import get_model
from inspect_ai.model._providers.anthropic import MIN_COMPACTION_TOKENS


def _sample_messages() -> list[ChatMessage]:
    """Create a simple message list for testing."""
    return [
        ChatMessageSystem(content="System prompt", id="sys1"),
        ChatMessageUser(content="Hello", id="msg1"),
        ChatMessageAssistant(content="Hi there", id="msg2"),
        ChatMessageUser(content="How are you?", id="msg3"),
        ChatMessageAssistant(content="I'm doing well.", id="msg4"),
    ]


@pytest.mark.asyncio
async def test_native_no_fallback_raises() -> None:
    """CompactionNative with no fallback raises NotImplementedError on mockllm."""
    strategy = CompactionNative()
    model = get_model("mockllm/model")
    messages = _sample_messages()

    with pytest.raises(NotImplementedError):
        await strategy.compact(model, messages, [])


@pytest.mark.asyncio
async def test_native_with_fallback_uses_fallback() -> None:
    """CompactionNative with fallback uses the fallback strategy on mockllm."""
    fallback = CompactionEdit()
    strategy = CompactionNative(fallback=fallback)
    model = get_model("mockllm/model")
    messages = _sample_messages()

    result, summary = await strategy.compact(model, messages, [])

    # Should succeed (no exception) and return compacted messages
    assert len(result) > 0
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_native_fallback_is_sticky() -> None:
    """After the first fallback, _use_fallback is True and subsequent calls use fallback directly."""
    fallback = CompactionEdit()
    strategy = CompactionNative(fallback=fallback)
    model = get_model("mockllm/model")
    messages = _sample_messages()

    # First call triggers fallback via NotImplementedError catch
    assert strategy._use_fallback is False
    await strategy.compact(model, messages, [])
    assert strategy._use_fallback is True

    # Second call goes through the sticky fallback path (no try/except)
    result, summary = await strategy.compact(model, messages, [])
    assert len(result) > 0
    assert strategy._use_fallback is True


@pytest.mark.asyncio
async def test_native_fallback_returns_fallback_result() -> None:
    """Verify the return value matches what the fallback strategy produces."""
    fallback = CompactionEdit()
    strategy = CompactionNative(fallback=fallback)
    model = get_model("mockllm/model")
    messages = _sample_messages()

    # Get result from CompactionNative with fallback
    native_result, native_summary = await strategy.compact(model, messages, [])

    # Get result directly from CompactionEdit for comparison
    edit_result, edit_summary = await fallback.compact(model, messages, [])

    # Results should match since the fallback delegates to CompactionEdit
    assert len(native_result) == len(edit_result)
    assert native_summary == edit_summary


@skip_if_no_openai
@pytest.mark.asyncio
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

    # The fallback should not have been triggered
    assert strategy._use_fallback is False


@skip_if_no_openai
@pytest.mark.asyncio
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

    # The fallback should not have been triggered
    assert strategy._use_fallback is False


# --- Anthropic-specific tests ---


@skip_if_no_anthropic
@pytest.mark.asyncio
async def test_anthropic_compaction_minimum_tokens_raises() -> None:
    """Anthropic native compaction raises RuntimeError when input is below minimum threshold."""
    model = get_model("anthropic/claude-opus-4-6")
    messages = _sample_messages()  # Small message list, well below 50k tokens

    # Direct call to the provider's compact method should raise RuntimeError
    # because the input is below the minimum threshold
    with pytest.raises(RuntimeError) as exc_info:
        await model.api.compact(messages, [], model.config)

    # Verify the error message contains useful information
    assert str(MIN_COMPACTION_TOKENS) in str(exc_info.value)
    assert "tokens" in str(exc_info.value)


@skip_if_no_anthropic
@pytest.mark.asyncio
async def test_anthropic_compaction_below_minimum_no_fallback() -> None:
    """CompactionNative does NOT fall back when Anthropic input is below minimum threshold.

    RuntimeError for minimum token threshold is a hard error - users should be
    explicitly aware of this limitation rather than silently falling back.
    """
    fallback = CompactionEdit()
    strategy = CompactionNative(fallback=fallback)
    model = get_model("anthropic/claude-opus-4-6")
    messages = _sample_messages()

    # Should raise RuntimeError even with fallback configured
    with pytest.raises(RuntimeError) as exc_info:
        await strategy.compact(model, messages, [])

    # Verify the error message contains useful information
    assert str(MIN_COMPACTION_TOKENS) in str(exc_info.value)

    # Fallback should NOT have been triggered
    assert strategy._use_fallback is False


@skip_if_no_anthropic
@pytest.mark.asyncio
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


@skip_if_no_anthropic
@pytest.mark.asyncio
async def test_anthropic_unsupported_model_triggers_fallback() -> None:
    """CompactionNative with fallback falls back on unsupported Anthropic models."""
    fallback = CompactionEdit()
    strategy = CompactionNative(fallback=fallback)
    # Use an older model that doesn't support compaction
    config = GenerateConfig(max_tokens=4096)
    model = get_model("anthropic/claude-3-haiku-20240307", config=config)
    messages = _long_messages()  # Need enough tokens to pass minimum threshold

    # Should succeed via fallback since model doesn't support compaction
    result, summary = await strategy.compact(model, messages, [])

    # Fallback should have been triggered
    assert strategy._use_fallback is True
    assert len(result) > 0


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
