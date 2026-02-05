"""Tests for the CompactionNative strategy."""

import pytest
from test_helpers.utils import skip_if_no_openai

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._compaction.edit import CompactionEdit
from inspect_ai.model._compaction.native import CompactionNative
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
async def test_native_no_fallback_raises() -> None:
    """CompactionNative with no fallback raises NotImplementedError on mockllm."""
    strategy = CompactionNative()
    model = get_model("mockllm/model")
    messages = _sample_messages()

    with pytest.raises(NotImplementedError):
        await strategy.compact(messages, model)


@pytest.mark.asyncio
async def test_native_with_fallback_uses_fallback() -> None:
    """CompactionNative with fallback uses the fallback strategy on mockllm."""
    fallback = CompactionEdit()
    strategy = CompactionNative(fallback=fallback)
    model = get_model("mockllm/model")
    messages = _sample_messages()

    result, summary = await strategy.compact(messages, model)

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
    await strategy.compact(messages, model)
    assert strategy._use_fallback is True

    # Second call goes through the sticky fallback path (no try/except)
    result, summary = await strategy.compact(messages, model)
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
    native_result, native_summary = await strategy.compact(messages, model)

    # Get result directly from CompactionEdit for comparison
    edit_result, edit_summary = await fallback.compact(messages, model)

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

    result, summary = await strategy.compact(messages, model)

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
    model = get_model("openai/gpt-4o")
    messages = _sample_messages()

    result, summary = await strategy.compact(messages, model)

    # Native compaction should work dynamically via the API
    assert len(result) > 0
    assert isinstance(result, list)

    # Native compaction returns None for the supplemental message
    assert summary is None

    # The fallback should not have been triggered
    assert strategy._use_fallback is False
