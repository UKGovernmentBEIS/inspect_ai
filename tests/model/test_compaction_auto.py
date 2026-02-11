"""Tests for the CompactionAuto strategy."""

import pytest
from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
)
from inspect_ai.model._compaction.auto import CompactionAuto
from inspect_ai.model._model import get_model


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
async def test_auto_uses_fallback_on_unsupported_provider() -> None:
    """CompactionAuto falls back to summary on unsupported providers."""
    strategy = CompactionAuto()
    model = get_model("mockllm/model")
    messages = _sample_messages()

    # Should succeed via fallback (no exception)
    result, summary = await strategy.compact(model, messages, [])

    # Should return compacted messages
    assert len(result) > 0
    assert isinstance(result, list)

    # Fallback should have been triggered
    assert strategy._use_fallback is True


@pytest.mark.asyncio
async def test_auto_fallback_is_sticky() -> None:
    """After the first fallback, _use_fallback is True and subsequent calls use fallback directly."""
    strategy = CompactionAuto()
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
async def test_auto_parameter_forwarding() -> None:
    """CompactionAuto forwards parameters to internal strategies."""
    threshold = 0.8
    instructions = "Focus on code snippets"
    memory = False

    strategy = CompactionAuto(
        threshold=threshold,
        instructions=instructions,
        memory=memory,
    )

    # Verify parameters are forwarded to internal strategies
    assert strategy._native.threshold == threshold
    assert strategy._native._instructions == instructions
    assert strategy._native.memory == memory

    assert strategy._summary.threshold == threshold
    assert strategy._summary.instructions == instructions
    assert strategy._summary.memory == memory


@pytest.mark.asyncio
async def test_auto_memory_auto_default() -> None:
    """CompactionAuto defaults memory to 'auto' with dynamic behavior."""
    strategy = CompactionAuto()

    # Default memory setting should be "auto"
    assert strategy._memory_setting == "auto"
    # Native doesn't need memory
    assert strategy._native.memory is False
    # Summary benefits from memory warnings
    assert strategy._summary.memory is True
    # Before fallback, memory property returns False (optimistic - assume native works)
    assert strategy.memory is False


@pytest.mark.asyncio
async def test_auto_memory_auto_after_fallback() -> None:
    """CompactionAuto memory property returns True after falling back to summary."""
    strategy = CompactionAuto()
    model = get_model("mockllm/model")
    messages = _sample_messages()

    # Before compaction, memory is False
    assert strategy.memory is False

    # Trigger compaction (will fall back on mockllm)
    await strategy.compact(model, messages, [])

    # After fallback, memory property returns True
    assert strategy._use_fallback is True
    assert strategy.memory is True


@pytest.mark.asyncio
async def test_auto_memory_explicit_true() -> None:
    """CompactionAuto with memory=True enables memory for both strategies."""
    strategy = CompactionAuto(memory=True)

    assert strategy._memory_setting is True
    assert strategy._native.memory is True
    assert strategy._summary.memory is True
    assert strategy.memory is True


@pytest.mark.asyncio
async def test_auto_memory_explicit_false() -> None:
    """CompactionAuto with memory=False disables memory for both strategies."""
    strategy = CompactionAuto(memory=False)

    assert strategy._memory_setting is False
    assert strategy._native.memory is False
    assert strategy._summary.memory is False
    assert strategy.memory is False


@skip_if_no_openai
@pytest.mark.asyncio
async def test_auto_uses_native_when_supported() -> None:
    """CompactionAuto uses native compaction when the provider supports it."""
    strategy = CompactionAuto()
    model = get_model("openai/gpt-5.1-codex")
    messages = _sample_messages()

    result, summary = await strategy.compact(model, messages, [])

    # Native compaction should return compacted messages
    assert len(result) > 0
    assert isinstance(result, list)

    # Native compaction returns None for the supplemental message
    assert summary is None

    # Fallback should NOT have been triggered
    assert strategy._use_fallback is False


@skip_if_no_anthropic
@pytest.mark.asyncio
async def test_auto_fallback_on_unsupported_anthropic_model() -> None:
    """CompactionAuto falls back on unsupported Anthropic models."""
    strategy = CompactionAuto()
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
