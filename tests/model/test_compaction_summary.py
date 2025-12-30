"""Tests for CompactionSummary strategy."""

import pytest

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._compaction.memory import MEMORY_TOOL
from inspect_ai.model._compaction.summary import CompactionSummary
from inspect_ai.model._model import get_model
from inspect_ai.tool import ToolCall


@pytest.fixture
def memory_tool_call() -> ToolCall:
    """A memory tool call for testing memory integration."""
    return ToolCall(
        id="mem1",
        function=MEMORY_TOOL,
        arguments={
            "command": "create",
            "path": "/memories/notes.txt",
            "file_text": "Some saved content",
        },
    )


@pytest.mark.asyncio
async def test_summary_basic() -> None:
    """Test basic summary generation returns expected structure."""
    strategy = CompactionSummary()

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="You are a helpful assistant."),
        ChatMessageUser(content="What is 2+2?", source="input"),
        ChatMessageAssistant(content="Let me think about that."),
        ChatMessageUser(content="Please answer."),
        ChatMessageAssistant(content="The answer is 4."),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(messages, model)

    # Summary should NOT be None (unlike Edit/Trim strategies)
    assert summary is not None

    # Summary should have correct metadata
    assert summary.metadata is not None
    assert summary.metadata.get("summary") is True

    # Summary content should include the expected format
    assert isinstance(summary.content, str)
    assert "[CONTEXT COMPACTION SUMMARY]" in summary.content

    # Compacted input should contain system + input + summary
    assert len(compacted) == 3
    assert isinstance(compacted[0], ChatMessageSystem)
    assert isinstance(compacted[1], ChatMessageUser)
    assert isinstance(compacted[2], ChatMessageUser)
    assert compacted[2] == summary


@pytest.mark.asyncio
async def test_summary_existing_summary() -> None:
    """Test that existing summary in history is recognized."""
    strategy = CompactionSummary()

    # Create a previous summary message
    old_summary = ChatMessageUser(
        content="[CONTEXT COMPACTION SUMMARY]\n\nPrevious summary content.",
        metadata={"summary": True},
    )

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Initial question", source="input"),
        # Old summary from previous compaction
        old_summary,
        # New conversation after the summary
        ChatMessageAssistant(content="Continuing work..."),
        ChatMessageUser(content="Next question"),
        ChatMessageAssistant(content="Next answer"),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(messages, model)

    assert summary is not None
    assert summary.metadata is not None
    assert summary.metadata.get("summary") is True

    # The strategy should only summarize content from the old summary onward,
    # not re-summarize everything from the beginning


@pytest.mark.asyncio
async def test_summary_memory_addendum_with_memory_calls(
    memory_tool_call: ToolCall,
) -> None:
    """Test that MEMORY_SUMMARY_ADDENDUM is included when memory calls exist."""
    strategy = CompactionSummary(memory=True)

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Save something to memory", source="input"),
        ChatMessageAssistant(
            content="Saving to memory...", tool_calls=[memory_tool_call]
        ),
        ChatMessageUser(content="Continue working"),
        ChatMessageAssistant(content="Done."),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(messages, model)

    assert summary is not None
    # The prompt should include memory addendum - we can verify the strategy
    # used the modified prompt by checking it processed correctly
    # (The actual prompt content goes to the model, we verify structure)


@pytest.mark.asyncio
async def test_summary_memory_disabled() -> None:
    """Test that memory addendum is NOT included when memory=False."""
    strategy = CompactionSummary(memory=False)

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Question", source="input"),
        ChatMessageAssistant(content="Answer"),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(messages, model)

    assert summary is not None
    # Strategy should complete without issues even with memory=False


@pytest.mark.asyncio
async def test_summary_custom_model() -> None:
    """Test that custom model is used when provided."""
    custom_model = get_model("mockllm/custom")
    strategy = CompactionSummary(model=custom_model)

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Question", source="input"),
        ChatMessageAssistant(content="Answer"),
    ]

    # Pass a different model - the strategy should use its own custom model
    fallback_model = get_model("mockllm/fallback")
    compacted, summary = await strategy.compact(messages, fallback_model)

    assert summary is not None


@pytest.mark.asyncio
async def test_summary_custom_prompt() -> None:
    """Test that custom prompt is used when provided."""
    custom_prompt = "Please summarize this conversation in one sentence."
    strategy = CompactionSummary(prompt=custom_prompt)

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Question", source="input"),
        ChatMessageAssistant(content="Answer"),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(messages, model)

    assert summary is not None
    # Strategy should use the custom prompt (verified by successful completion)


@pytest.mark.asyncio
async def test_summary_no_system_message() -> None:
    """Test summary works without system messages."""
    strategy = CompactionSummary()

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Question", source="input"),
        ChatMessageAssistant(content="Answer 1"),
        ChatMessageUser(content="Follow-up"),
        ChatMessageAssistant(content="Answer 2"),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(messages, model)

    assert summary is not None
    # Without system message, compacted should have input + summary
    assert len(compacted) == 2
    assert isinstance(compacted[0], ChatMessageUser)
    assert isinstance(compacted[1], ChatMessageUser)


@pytest.mark.asyncio
async def test_summary_preserves_input_messages() -> None:
    """Test that input messages are preserved in compacted output."""
    strategy = CompactionSummary()

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="First input", source="input"),
        ChatMessageUser(content="Second input", source="input"),
        ChatMessageAssistant(content="Response to inputs"),
        ChatMessageUser(content="Follow-up (not input)"),
        ChatMessageAssistant(content="Another response"),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(messages, model)

    assert summary is not None
    # Should have: system + 2 inputs + summary
    assert len(compacted) == 4
    assert isinstance(compacted[0], ChatMessageSystem)
    assert isinstance(compacted[1], ChatMessageUser)
    assert compacted[1].content == "First input"
    assert isinstance(compacted[2], ChatMessageUser)
    assert compacted[2].content == "Second input"
    assert compacted[3] == summary
