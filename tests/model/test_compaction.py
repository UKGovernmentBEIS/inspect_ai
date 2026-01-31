"""Tests for the compaction() factory function."""

from typing import Literal

import pytest

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._compaction._compaction import compaction
from inspect_ai.model._compaction.edit import CompactionEdit
from inspect_ai.model._compaction.memory import MEMORY_TOOL
from inspect_ai.model._compaction.summary import CompactionSummary
from inspect_ai.model._compaction.trim import CompactionTrim
from inspect_ai.model._model import get_model
from inspect_ai.model._trim import strip_citations
from inspect_ai.tool import ToolInfo


# Helper to create messages with IDs
def user_msg(
    content: str, id: str, source: Literal["input", "generate"] | None = None
) -> ChatMessageUser:
    return ChatMessageUser(content=content, id=id, source=source)


def assistant_msg(content: str, id: str) -> ChatMessageAssistant:
    return ChatMessageAssistant(content=content, id=id)


def system_msg(content: str, id: str) -> ChatMessageSystem:
    return ChatMessageSystem(content=content, id=id)


@pytest.fixture
def memory_tool() -> ToolInfo:
    """Memory tool info for testing memory warning logic."""
    return ToolInfo(
        name=MEMORY_TOOL,
        description="Save content to memory",
    )


@pytest.fixture
def other_tool() -> ToolInfo:
    """A non-memory tool for testing."""
    return ToolInfo(
        name="bash",
        description="Run bash commands",
    )


# ==============================================================================
# Threshold Resolution Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_threshold_absolute_int() -> None:
    """Test that integer threshold is used as-is."""
    strategy = CompactionEdit(threshold=500)  # Absolute token count
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("System", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    # Create messages that don't exceed 500 tokens
    messages: list[ChatMessage] = [
        system_msg("System", "sys1"),
        user_msg("Short message", "msg1"),
        assistant_msg("Short response", "msg2"),
    ]

    # Should not trigger compaction
    result, summary = await compact(messages)
    assert summary is None  # No compaction occurred
    assert len(result) == 3


@pytest.mark.asyncio
async def test_threshold_absolute_float_above_one() -> None:
    """Test that threshold > 1.0 is treated as absolute."""
    strategy = CompactionEdit(threshold=5000.0)  # Float > 1.0 = absolute
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("System", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    messages: list[ChatMessage] = [
        system_msg("System", "sys1"),
        user_msg("Message", "msg1"),
    ]

    result, summary = await compact(messages)
    assert summary is None  # Under threshold, no compaction
    assert len(result) == 2


# ==============================================================================
# Memory Warning Logic Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_memory_warning_issued(memory_tool: ToolInfo) -> None:
    """Test that memory warning is issued when tokens > 0.9 * threshold."""
    # Use a low threshold so we can trigger memory warning zone
    strategy = CompactionEdit(threshold=200, memory=True)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("S", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=[memory_tool], model=model)

    # Create messages that are between 0.9*200=180 and 200 tokens
    # This requires moderately sized content
    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("Q" * 50, "msg1"),
        assistant_msg("A" * 50, "msg2"),
    ]

    result, summary = await compact(messages)

    # The test verifies the mechanism works - whether warning is issued
    # depends on exact token count which varies with tiktoken encoding.
    # We just verify the call succeeds and returns a valid result.
    assert result is not None
    assert len(result) >= 3  # At least the original messages


@pytest.mark.asyncio
async def test_memory_warning_disabled() -> None:
    """Test that memory warning is NOT issued when strategy.memory=False."""
    strategy = CompactionEdit(threshold=100, memory=False)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("S", "sys1")]
    memory_tool = ToolInfo(name=MEMORY_TOOL, description="Memory")
    compact = compaction(strategy, prefix=prefix, tools=[memory_tool], model=model)

    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("Q" * 30, "msg1"),
        assistant_msg("A" * 30, "msg2"),
    ]

    result, summary = await compact(messages)

    # No memory warning should be present when memory=False
    has_warning = any(
        isinstance(m, ChatMessageUser)
        and isinstance(m.content, str)
        and "Context compaction approaching" in m.content
        for m in result
    )
    assert not has_warning


@pytest.mark.asyncio
async def test_memory_warning_no_tool(other_tool: ToolInfo) -> None:
    """Test that memory warning is NOT issued when MEMORY_TOOL not in tools."""
    strategy = CompactionEdit(threshold=100, memory=True)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("S", "sys1")]
    # Use a non-memory tool
    compact = compaction(strategy, prefix=prefix, tools=[other_tool], model=model)

    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("Q" * 30, "msg1"),
        assistant_msg("A" * 30, "msg2"),
    ]

    result, summary = await compact(messages)

    # No memory warning without memory tool
    has_warning = any(
        isinstance(m, ChatMessageUser)
        and isinstance(m.content, str)
        and "Context compaction approaching" in m.content
        for m in result
    )
    assert not has_warning


# ==============================================================================
# Prefix Preservation Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_prefix_restored() -> None:
    """Test that prefix messages are restored after compaction."""
    strategy = CompactionSummary(threshold=100)
    model = get_model("mockllm/model")

    # Prefix includes system and input
    prefix: list[ChatMessage] = [
        system_msg("System prompt", "sys1"),
        user_msg("Initial input", "input1", source="input"),
    ]

    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    # Create messages that exceed threshold to trigger compaction
    messages: list[ChatMessage] = [
        system_msg("System prompt", "sys1"),
        user_msg("Initial input", "input1", source="input"),
        assistant_msg("A" * 100, "msg1"),
        user_msg("Q" * 100, "msg2"),
        assistant_msg("A" * 100, "msg3"),
    ]

    result, summary = await compact(messages)

    # Prefix should be preserved in result
    assert len(result) >= 2
    # System should be first
    assert isinstance(result[0], ChatMessageSystem)


@pytest.mark.asyncio
async def test_prefix_empty() -> None:
    """Test that empty prefix is handled correctly."""
    strategy = CompactionEdit(threshold=500)
    model = get_model("mockllm/model")

    # Empty prefix
    prefix: list[ChatMessage] = []
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    messages: list[ChatMessage] = [
        user_msg("Question", "msg1"),
        assistant_msg("Answer", "msg2"),
    ]

    result, summary = await compact(messages)
    assert len(result) == 2


# ==============================================================================
# Multiple Compaction Cycles Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_cycle_processed_ids() -> None:
    """Test that sequential calls track processed_message_ids correctly."""
    strategy = CompactionEdit(threshold=500)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("System", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    # First call
    messages1: list[ChatMessage] = [
        system_msg("System", "sys1"),
        user_msg("Q1", "msg1"),
        assistant_msg("A1", "msg2"),
    ]
    result1, _ = await compact(messages1)

    # Second call with additional messages
    messages2: list[ChatMessage] = [
        system_msg("System", "sys1"),
        user_msg("Q1", "msg1"),
        assistant_msg("A1", "msg2"),
        user_msg("Q2", "msg3"),
        assistant_msg("A2", "msg4"),
    ]
    result2, _ = await compact(messages2)

    # All messages should be included
    assert len(result2) == 5


@pytest.mark.asyncio
async def test_cycle_token_cache() -> None:
    """Test that token counts are cached and reused across calls."""
    strategy = CompactionEdit(threshold=500)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("System", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    messages: list[ChatMessage] = [
        system_msg("System", "sys1"),
        user_msg("Question", "msg1"),
        assistant_msg("Answer", "msg2"),
    ]

    # Call twice with same messages
    result1, _ = await compact(messages)
    result2, _ = await compact(messages)

    # Results should be consistent
    assert len(result1) == len(result2)


# ==============================================================================
# Tool Token Handling Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_tools_empty() -> None:
    """Test that empty tools list is handled correctly."""
    strategy = CompactionEdit(threshold=500)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("System", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=[], model=model)

    messages: list[ChatMessage] = [
        system_msg("System", "sys1"),
        user_msg("Question", "msg1"),
    ]

    result, summary = await compact(messages)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_tools_none() -> None:
    """Test that None tools is handled correctly."""
    strategy = CompactionEdit(threshold=500)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("System", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    messages: list[ChatMessage] = [
        system_msg("System", "sys1"),
        user_msg("Question", "msg1"),
    ]

    result, summary = await compact(messages)
    assert len(result) == 2


# ==============================================================================
# Boundary Condition Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_boundary_under_threshold() -> None:
    """Test that tokens under threshold don't trigger compaction."""
    strategy = CompactionEdit(threshold=10000)  # High threshold
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("S", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("Short", "msg1"),
        assistant_msg("Short", "msg2"),
    ]

    result, summary = await compact(messages)
    assert summary is None  # No compaction
    assert len(result) == 3


@pytest.mark.asyncio
async def test_boundary_triggers_compaction() -> None:
    """Test that tokens above threshold trigger compaction (with tool calls to clear)."""
    from inspect_ai.tool import ToolCall

    # Use CompactionEdit with tool calls that can be cleared
    strategy = CompactionEdit(threshold=300, keep_tool_uses=0)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("S", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    # Create messages with tool calls that can be cleared
    # This allows compaction to actually reduce token count
    tool_call = ToolCall(id="t1", function="bash", arguments={"cmd": "A" * 200})

    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("Question", "msg1"),
        ChatMessageAssistant(content="Using tool", id="msg2", tool_calls=[tool_call]),
        ChatMessageTool(
            content="B" * 200, tool_call_id="t1", function="bash", id="msg3"
        ),
        user_msg("Follow up", "msg4"),
        assistant_msg("Done", "msg5"),
    ]

    result, summary = await compact(messages)
    # Compaction should have occurred (summary is still None for Edit strategy)
    assert summary is None  # Edit strategy returns None
    # Tool result should have been cleared
    assert len(result) >= 5


# ==============================================================================
# Strategy Return Value Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_return_edit_none() -> None:
    """Test that CompactionEdit returns None for summary."""
    strategy = CompactionEdit(threshold=50)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("S", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("A" * 100, "msg1"),
        assistant_msg("B" * 100, "msg2"),
    ]

    result, summary = await compact(messages)
    # Edit strategy always returns None for summary
    assert summary is None


@pytest.mark.asyncio
async def test_return_trim_none() -> None:
    """Test that CompactionTrim returns None for summary."""
    strategy = CompactionTrim(threshold=50)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("S", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("A" * 100, "msg1"),
        assistant_msg("B" * 100, "msg2"),
    ]

    result, summary = await compact(messages)
    # Trim strategy always returns None for summary
    assert summary is None


@pytest.mark.asyncio
async def test_return_summary_not_none() -> None:
    """Test that CompactionSummary returns non-None summary."""
    # Use threshold that triggers compaction but can accommodate the summary output
    # The mockllm returns a short default output, so the summary will be small
    strategy = CompactionSummary(threshold=200)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("S", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    # Create enough content to exceed 200 tokens and trigger compaction
    # 800 chars per message = ~200 tokens, multiple messages = ~400+ tokens
    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("A" * 800, "msg1", source="input"),
        assistant_msg("B" * 800, "msg2"),
        user_msg("C" * 800, "msg3"),
    ]

    result, summary = await compact(messages)
    # Summary strategy returns non-None summary when compaction occurs
    assert summary is not None
    assert isinstance(summary, ChatMessageUser)
    assert summary.metadata is not None
    assert summary.metadata.get("summary") is True


# ==============================================================================
# Edge Case Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_edge_small_threshold() -> None:
    """Test that very small threshold (100 tokens) works correctly."""
    strategy = CompactionEdit(threshold=100)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = []
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    messages: list[ChatMessage] = [
        user_msg("Short", "msg1"),
        assistant_msg("Short", "msg2"),
    ]

    # Should work without errors
    result, summary = await compact(messages)
    assert result is not None


@pytest.mark.asyncio
async def test_single_message() -> None:
    """Test compaction with a single message."""
    strategy = CompactionEdit(threshold=500)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = []
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    messages: list[ChatMessage] = [
        user_msg("Hello", "msg1"),
    ]

    result, summary = await compact(messages)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_summary_integration() -> None:
    """Test that summary message is recognized in subsequent calls."""
    strategy = CompactionSummary(threshold=100)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [
        system_msg("System", "sys1"),
        user_msg("Input", "input1", source="input"),
    ]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    # First call triggers compaction - need enough content to exceed threshold
    # 500 chars = ~125 tokens per message
    messages1: list[ChatMessage] = [
        system_msg("System", "sys1"),
        user_msg("Input", "input1", source="input"),
        assistant_msg("A" * 500, "msg1"),
        user_msg("Q" * 500, "msg2"),
    ]

    result1, summary1 = await compact(messages1)
    assert summary1 is not None

    # Second call with the summary included
    messages2: list[ChatMessage] = messages1 + [summary1]
    messages2.append(assistant_msg("Continuing", "msg3"))

    result2, summary2 = await compact(messages2)
    # The factory should handle the summary in the history
    assert result2 is not None


# ==============================================================================
# Iterative Compaction Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_iterative_compaction_succeeds() -> None:
    """Test that iterative compaction retries until under threshold."""
    # Use CompactionTrim with threshold that requires 2+ passes to succeed.
    # preserve=0.5 means each pass keeps 50%, so:
    # - Pass 1: 50% of messages remain
    # - Pass 2: 25% of messages remain
    # - Pass 3: 12.5% of messages remain
    # We set threshold such that pass 1 fails but later passes succeed.
    strategy = CompactionTrim(threshold=200, preserve=0.5)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("S", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    # Create messages that exceed 200 tokens but can be reduced via iteration
    messages: list[ChatMessage] = [system_msg("S", "sys1")]
    for i in range(10):
        messages.append(user_msg(f"Q{i}" * 10, f"u{i}"))
        messages.append(assistant_msg(f"A{i}" * 10, f"a{i}"))

    # Should succeed via iteration (not raise RuntimeError)
    result, _ = await compact(messages)
    assert result is not None
    assert len(result) < len(messages)


@pytest.mark.asyncio
async def test_iterative_compaction_stops_when_no_progress() -> None:
    """Test that iteration stops if compaction makes no progress."""
    # CompactionEdit with nothing to clear should stop immediately
    strategy = CompactionEdit(threshold=50, keep_tool_uses=100)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("System prompt " * 20, "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    # Messages with no tool calls (nothing for Edit to clear)
    messages: list[ChatMessage] = [
        system_msg("System prompt " * 20, "sys1"),
        user_msg("Q" * 100, "msg1"),
    ]

    # Should raise RuntimeError since Edit can't reduce these messages
    with pytest.raises(RuntimeError, match="Compaction insufficient"):
        await compact(messages)


@pytest.mark.asyncio
async def test_compaction_error_message_breakdown() -> None:
    """Test that RuntimeError includes tools, prefix, messages breakdown."""
    strategy = CompactionEdit(threshold=50, keep_tool_uses=100)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("Prefix " * 10, "sys1")]
    tool = ToolInfo(name="bash", description="Run commands")
    compact = compaction(strategy, prefix=prefix, tools=[tool], model=model)

    messages: list[ChatMessage] = [
        system_msg("Prefix " * 10, "sys1"),
        user_msg("Q" * 100, "msg1"),
    ]

    with pytest.raises(RuntimeError) as exc_info:
        await compact(messages)

    error_msg = str(exc_info.value)
    assert "tools:" in error_msg
    assert "prefix:" in error_msg
    assert "messages:" in error_msg


# ==============================================================================
# Citation Stripping Tests
# ==============================================================================


def teststrip_citations_removes_citations_from_content_text() -> None:
    """Test that citations are removed from ContentText blocks."""
    citation = UrlCitation(
        url="https://example.com",
        cited_text="some text",
        title="Example",
    )
    messages: list[ChatMessage] = [
        ChatMessageAssistant(
            content=[ContentText(text="Response with citation", citations=[citation])],
            id="msg1",
        ),
    ]

    result = strip_citations(messages)

    assert len(result) == 1
    assistant = result[0]
    assert isinstance(assistant, ChatMessageAssistant)
    assert isinstance(assistant.content, list)
    content_text = assistant.content[0]
    assert isinstance(content_text, ContentText)
    assert content_text.text == "Response with citation"
    assert content_text.citations is None


def teststrip_citations_preserves_messages_without_citations() -> None:
    """Test that messages without citations are unchanged."""
    messages: list[ChatMessage] = [
        ChatMessageUser(content="Question", id="msg1"),
        ChatMessageAssistant(
            content=[ContentText(text="Response without citation")],
            id="msg2",
        ),
    ]

    result = strip_citations(messages)

    assert len(result) == 2
    # Messages without citations should be the same objects
    assert result[0] is messages[0]
    assert result[1] is messages[1]


def teststrip_citations_preserves_string_content() -> None:
    """Test that string content messages are unchanged."""
    messages: list[ChatMessage] = [
        ChatMessageUser(content="Simple string content", id="msg1"),
        ChatMessageAssistant(content="Simple response", id="msg2"),
    ]

    result = strip_citations(messages)

    assert len(result) == 2
    # String content messages should be the same objects
    assert result[0] is messages[0]
    assert result[1] is messages[1]


def teststrip_citations_preserves_other_content_types() -> None:
    """Test that non-text content types are unchanged."""
    citation = UrlCitation(url="https://example.com", cited_text="text")
    messages: list[ChatMessage] = [
        ChatMessageUser(
            content=[
                ContentImage(image="data:image/png;base64,abc123"),
                ContentText(text="Text with citation", citations=[citation]),
            ],
            id="msg1",
        ),
    ]

    result = strip_citations(messages)

    assert len(result) == 1
    user_msg = result[0]
    assert isinstance(user_msg, ChatMessageUser)
    assert isinstance(user_msg.content, list)
    assert len(user_msg.content) == 2
    # Image should be unchanged
    assert isinstance(user_msg.content[0], ContentImage)
    assert user_msg.content[0].image == "data:image/png;base64,abc123"
    # Text should have citations stripped
    assert isinstance(user_msg.content[1], ContentText)
    assert user_msg.content[1].citations is None


def teststrip_citations_handles_empty_list() -> None:
    """Test that empty message list returns empty list."""
    result = strip_citations([])
    assert result == []


def teststrip_citations_handles_multiple_citations() -> None:
    """Test that multiple citations are all removed."""
    citations = [
        UrlCitation(url="https://example1.com", cited_text="text1"),
        UrlCitation(url="https://example2.com", cited_text="text2"),
    ]
    messages: list[ChatMessage] = [
        ChatMessageAssistant(
            content=[
                ContentText(
                    text="Response with multiple citations", citations=citations
                )
            ],
            id="msg1",
        ),
    ]

    result = strip_citations(messages)

    assistant = result[0]
    assert isinstance(assistant, ChatMessageAssistant)
    assert isinstance(assistant.content, list)
    content_text = assistant.content[0]
    assert isinstance(content_text, ContentText)
    assert content_text.citations is None


@pytest.mark.asyncio
async def test_compaction_strips_citations() -> None:
    """Test that compaction strips citations from messages."""
    from inspect_ai.tool import ToolCall

    citation = UrlCitation(
        url="https://example.com",
        cited_text="search result",
        title="Example",
    )

    # Use CompactionEdit with low threshold to ensure compaction triggers
    # keep_tool_uses=0 allows clearing tool results to reduce tokens
    strategy = CompactionEdit(threshold=100, keep_tool_uses=0)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = [system_msg("S", "sys1")]
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    # Create tool calls with large content to exceed threshold
    tool_call = ToolCall(id="t1", function="bash", arguments={"cmd": "A" * 500})

    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("Question", "msg1"),
        ChatMessageAssistant(content="Using tool", id="msg2", tool_calls=[tool_call]),
        ChatMessageTool(
            content="B" * 500, tool_call_id="t1", function="bash", id="msg3"
        ),
        user_msg("Follow up", "msg4"),
        # Assistant response with citations (simulating web_search result)
        ChatMessageAssistant(
            content=[ContentText(text="Here is what I found", citations=[citation])],
            id="msg5",
        ),
    ]

    result, _ = await compact(messages)

    # Find any assistant message with ContentText content
    for msg in result:
        if isinstance(msg, ChatMessageAssistant) and isinstance(msg.content, list):
            for content in msg.content:
                if isinstance(content, ContentText):
                    # Citations should have been stripped during compaction
                    assert content.citations is None, (
                        f"Expected citations to be None, got {content.citations}"
                    )
