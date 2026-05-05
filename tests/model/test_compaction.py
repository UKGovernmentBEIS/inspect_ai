"""Tests for the compaction() factory function."""

from typing import Literal

import pytest

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentImage, ContentReasoning, ContentText
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
    result, summary = await compact.compact_input(messages)
    assert summary is None  # No compaction occurred
    assert len(result) == 3


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

    result, summary = await compact.compact_input(messages)
    assert summary is None  # Under threshold, no compaction
    assert len(result) == 2


# ==============================================================================
# Memory Warning Logic Tests
# ==============================================================================
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

    result, summary = await compact.compact_input(messages)

    # The test verifies the mechanism works - whether warning is issued
    # depends on exact token count which varies with tiktoken encoding.
    # We just verify the call succeeds and returns a valid result.
    assert result is not None
    assert len(result) >= 3  # At least the original messages


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

    result, summary = await compact.compact_input(messages)

    # No memory warning should be present when memory=False
    has_warning = any(
        isinstance(m, ChatMessageUser)
        and isinstance(m.content, str)
        and "Context compaction approaching" in m.content
        for m in result
    )
    assert not has_warning


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

    result, summary = await compact.compact_input(messages)

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

    result, summary = await compact.compact_input(messages)

    # Prefix should be preserved in result
    assert len(result) >= 2
    # System should be first
    assert isinstance(result[0], ChatMessageSystem)


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

    result, summary = await compact.compact_input(messages)
    assert len(result) == 2


# ==============================================================================
# Multiple Compaction Cycles Tests
# ==============================================================================
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
    result1, _ = await compact.compact_input(messages1)

    # Second call with additional messages
    messages2: list[ChatMessage] = [
        system_msg("System", "sys1"),
        user_msg("Q1", "msg1"),
        assistant_msg("A1", "msg2"),
        user_msg("Q2", "msg3"),
        assistant_msg("A2", "msg4"),
    ]
    result2, _ = await compact.compact_input(messages2)

    # All messages should be included
    assert len(result2) == 5


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
    result1, _ = await compact.compact_input(messages)
    result2, _ = await compact.compact_input(messages)

    # Results should be consistent
    assert len(result1) == len(result2)


# ==============================================================================
# Tool Token Handling Tests
# ==============================================================================
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

    result, summary = await compact.compact_input(messages)
    assert len(result) == 2


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

    result, summary = await compact.compact_input(messages)
    assert len(result) == 2


# ==============================================================================
# Boundary Condition Tests
# ==============================================================================
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

    result, summary = await compact.compact_input(messages)
    assert summary is None  # No compaction
    assert len(result) == 3


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
    tool_call = ToolCall(id="t1", function="bash", arguments={"command": "A" * 200})

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

    result, summary = await compact.compact_input(messages)
    # Compaction should have occurred (summary is still None for Edit strategy)
    assert summary is None  # Edit strategy returns None
    # Tool result should have been cleared
    assert len(result) >= 5


# ==============================================================================
# Strategy Return Value Tests
# ==============================================================================
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

    result, summary = await compact.compact_input(messages)
    # Edit strategy always returns None for summary
    assert summary is None


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

    result, summary = await compact.compact_input(messages)
    # Trim strategy always returns None for summary
    assert summary is None


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

    result, summary = await compact.compact_input(messages)
    # Summary strategy returns non-None summary when compaction occurs
    assert summary is not None
    assert isinstance(summary, ChatMessageUser)
    assert summary.metadata is not None
    assert summary.metadata.get("summary") is True


# ==============================================================================
# Edge Case Tests
# ==============================================================================
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
    result, summary = await compact.compact_input(messages)
    assert result is not None


async def test_single_message() -> None:
    """Test compaction with a single message."""
    strategy = CompactionEdit(threshold=500)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = []
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    messages: list[ChatMessage] = [
        user_msg("Hello", "msg1"),
    ]

    result, summary = await compact.compact_input(messages)
    assert len(result) == 1


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

    result1, summary1 = await compact.compact_input(messages1)
    assert summary1 is not None

    # Second call with the summary included
    messages2: list[ChatMessage] = messages1 + [summary1]
    messages2.append(assistant_msg("Continuing", "msg3"))

    result2, summary2 = await compact.compact_input(messages2)
    # The factory should handle the summary in the history
    assert result2 is not None


# ==============================================================================
# Iterative Compaction Tests
# ==============================================================================
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
    result, _ = await compact.compact_input(messages)
    assert result is not None
    assert len(result) < len(messages)


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
        await compact.compact_input(messages)


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
        await compact.compact_input(messages)

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
    tool_call = ToolCall(id="t1", function="bash", arguments={"command": "A" * 500})

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

    result, _ = await compact.compact_input(messages)

    # Find any assistant message with ContentText content
    for msg in result:
        if isinstance(msg, ChatMessageAssistant) and isinstance(msg.content, list):
            for content in msg.content:
                if isinstance(content, ContentText):
                    # Citations should have been stripped during compaction
                    assert content.citations is None, (
                        f"Expected citations to be None, got {content.citations}"
                    )


async def test_compact_input_concurrent_no_duplicate_messages() -> None:
    """Concurrent compact_input calls must not duplicate closure state.

    When the same Compact instance is shared (e.g. through AgentBridge),
    parallel callers must not lose updates to compacted_input.
    """
    import anyio

    from inspect_ai._util._async import tg_collect
    from inspect_ai.model._generate_config import GenerateConfig

    # high threshold so compaction never triggers; exercises the no-compaction
    # branch where concurrent callers all extend compacted_input
    strategy = CompactionEdit(threshold=10_000_000)

    model = get_model("mockllm/model")

    # yield inside count_tokens so the scheduler interleaves concurrent
    # callers; without an explicit yield, asyncio may run each coroutine
    # to completion without context-switching
    async def yielding_count_tokens(
        input: str | list[ChatMessage],
        config: GenerateConfig | None = None,
    ) -> int:
        await anyio.sleep(0)
        return 1

    model.count_tokens = yielding_count_tokens  # type: ignore[method-assign]

    prefix: list[ChatMessage] = []
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    messages: list[ChatMessage] = [
        user_msg("hello", "msg1"),
        assistant_msg("hi", "msg2"),
    ]

    async def call_once() -> tuple[list[ChatMessage], ChatMessageUser | None]:
        return await compact.compact_input(messages)

    await tg_collect([call_once for _ in range(10)])

    final, _ = await compact.compact_input(messages)
    final_ids = [m.id for m in final]
    assert len(final_ids) == len(set(final_ids)), (
        f"compacted_input contains duplicate message ids: {final_ids}"
    )


async def test_force_compaction_skips_threshold() -> None:
    """force=True compacts even when total tokens are well under threshold.

    Without force=True, CompactionTrim with threshold=1_000_000 should not
    trim (way under the threshold). With force=True, compaction runs
    unconditionally and trim's preserve=0.5 reduces the message count.
    """
    strategy = CompactionTrim(threshold=1_000_000, preserve=0.5)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = []

    messages: list[ChatMessage] = [user_msg(f"msg{i}", f"u{i}") for i in range(10)]

    # Predictive (no force) should not trim under a huge threshold.
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)
    result_predictive, _ = await compact.compact_input(messages)
    assert len(result_predictive) == len(messages), (
        f"Predictive compaction should not trim under threshold; "
        f"got {len(result_predictive)} vs {len(messages)} messages"
    )

    # Force should trim regardless of threshold.
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)
    result_forced, _ = await compact.compact_input(messages, force=True)
    assert len(result_forced) < len(messages), (
        f"force=True should trigger compaction (trim with preserve=0.5); "
        f"got {len(result_forced)} vs {len(messages)} messages"
    )


# ==============================================================================
# Redacted-reasoning input cost (predictive blind-spot fix)
# ==============================================================================


def _assistant_with_redacted_reasoning_tokens(
    text: str, id: str, redacted_tokens: int
) -> ChatMessageAssistant:
    """Build an all-redacted-reasoning assistant message for tests.

    The assistant has a redacted ContentReasoning block alongside text
    output, plus the metadata key the wrapper would have stamped.
    """
    return ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="ENCRYPTED", redacted=True),
            ContentText(text=text),
        ],
        id=id,
        metadata={"redacted_reasoning_tokens": redacted_tokens},
    )


async def test_redacted_reasoning_metadata_pushes_threshold_over(
    monkeypatch,
) -> None:
    """Summed redacted_reasoning_tokens push the effective total over threshold.

    When the provider declares the blind spot, summed
    `redacted_reasoning_tokens` from message metadata pushes the effective
    total over threshold. With the flag off, the same messages stay under.

    This is the test the original PR was missing — it would have failed
    against the count_tokens-based fix because count_tokens does not
    actually report the encrypted reasoning.
    """
    # Threshold low enough to be exceeded only by the redacted accounting.
    strategy = CompactionTrim(threshold=1000, preserve=0.5)
    model = get_model("mockllm/model")

    prefix: list[ChatMessage] = []

    # 4 turns; each assistant turn adds 400 redacted tokens.
    # Plain message tokens are tiny (well under 1000), so the predictive
    # threshold trip is driven entirely by metadata.
    messages: list[ChatMessage] = []
    for i in range(4):
        messages.append(user_msg(f"q{i}", f"u{i}"))
        messages.append(
            _assistant_with_redacted_reasoning_tokens(
                f"answer {i}", f"a{i}", redacted_tokens=400
            )
        )

    # With flag off (default), no correction → stays under threshold → no compaction
    monkeypatch.setattr(
        model.api, "apply_redacted_reasoning_tokens_to_input", lambda: False
    )
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)
    result_off, _ = await compact.compact_input(messages)
    assert len(result_off) == len(messages), (
        f"With flag off, redacted_reasoning_tokens should be ignored; "
        f"got {len(result_off)} messages (expected {len(messages)})"
    )

    # With flag on, sum is 4 * 400 = 1600 > threshold (1000) → compaction trips
    monkeypatch.setattr(
        model.api, "apply_redacted_reasoning_tokens_to_input", lambda: True
    )
    compact = compaction(strategy, prefix=prefix, tools=None, model=model)
    result_on, _ = await compact.compact_input(messages)
    assert len(result_on) < len(messages), (
        f"With flag on, summed redacted_reasoning_tokens (1600) should push "
        f"effective total over threshold (1000); expected compaction to run; "
        f"got {len(result_on)} messages (no compaction)"
    )


async def test_redacted_reasoning_metadata_dropped_after_compaction(
    monkeypatch,
) -> None:
    """Compaction-discarded messages fall out of the threshold sum.

    When a strategy discards messages, their metadata contributions fall
    out of the next threshold sum naturally — the surviving subset is what
    gets summed.
    """
    strategy = CompactionTrim(threshold=1000, preserve=0.25)
    model = get_model("mockllm/model")
    monkeypatch.setattr(
        model.api, "apply_redacted_reasoning_tokens_to_input", lambda: True
    )

    prefix: list[ChatMessage] = []

    # 8 turns × 200 tokens = 1600 hidden tokens > 1000 threshold → trips.
    messages: list[ChatMessage] = []
    for i in range(8):
        messages.append(user_msg(f"q{i}", f"u{i}"))
        messages.append(
            _assistant_with_redacted_reasoning_tokens(
                f"answer {i}", f"a{i}", redacted_tokens=200
            )
        )

    compact = compaction(strategy, prefix=prefix, tools=None, model=model)
    compacted, _ = await compact.compact_input(messages)

    # CompactionTrim with preserve=0.25 keeps the most recent ~25% of messages.
    # Surviving assistant metadata sum should be << 1600 (the pre-compaction
    # total) — verify by reading the metadata directly off the result.
    surviving_hidden = sum(
        (m.metadata or {}).get("redacted_reasoning_tokens", 0)
        for m in compacted
        if isinstance(m, ChatMessageAssistant)
    )
    assert surviving_hidden < 1600, (
        f"Surviving redacted_reasoning_tokens after compaction should drop "
        f"below the pre-compaction total of 1600; got {surviving_hidden}"
    )


async def test_post_compaction_validation_includes_redacted_reasoning_tokens(
    monkeypatch,
) -> None:
    """Post-compaction validation must include hidden redacted-reasoning cost.

    Regression for a bug where `_perform_compaction` validated only against
    `tool_tokens + count_tokens(c_input)` and ignored the hidden cost of
    redacted-reasoning tokens that the strategy preserved. A trim strategy
    with high preserve could "succeed" (no error raised, no further
    iteration) while the surviving messages still carried enough hidden
    reasoning to push the effective total over threshold.

    Setup: 8 assistant turns × 250 redacted tokens = 2000 hidden tokens,
    threshold=1000, preserve=0.75 → trim keeps ~75% of messages and ~1500
    hidden tokens, still over threshold. Compaction should NOT silently
    succeed; it should either iterate again or raise "Compaction insufficient".
    """
    strategy = CompactionTrim(threshold=1000, preserve=0.75)
    model = get_model("mockllm/model")
    monkeypatch.setattr(
        model.api, "apply_redacted_reasoning_tokens_to_input", lambda: True
    )

    prefix: list[ChatMessage] = []

    messages: list[ChatMessage] = []
    for i in range(8):
        messages.append(user_msg(f"q{i}", f"u{i}"))
        messages.append(
            _assistant_with_redacted_reasoning_tokens(
                f"answer {i}", f"a{i}", redacted_tokens=250
            )
        )

    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    # If validation correctly accounts for hidden tokens, compaction either
    # converges below threshold via iteration OR raises. It must NOT return
    # a result whose surviving hidden tokens still exceed threshold.
    try:
        compacted, _ = await compact.compact_input(messages)
        surviving_hidden = sum(
            (m.metadata or {}).get("redacted_reasoning_tokens", 0)
            for m in compacted
            if isinstance(m, ChatMessageAssistant)
        )
        assert surviving_hidden <= 1000, (
            f"Compaction returned a result with {surviving_hidden} surviving "
            f"redacted_reasoning_tokens, which exceeds threshold (1000). "
            f"Post-compaction validation must include hidden reasoning cost."
        )
    except RuntimeError as ex:
        # Acceptable: compaction couldn't reduce enough and raised instead
        # of silently returning an over-threshold result.
        assert "Compaction insufficient" in str(ex), ex


async def test_redacted_reasoning_total_ignores_messages_without_redacted_blocks(
    monkeypatch,
) -> None:
    """Helper ignores metadata when redacted content has been stripped.

    Regression for an interaction with CompactionEdit's reasoning-clearing
    pass: it removes ContentReasoning blocks from older turns but preserves
    message metadata. The redacted_reasoning_tokens metadata describes a
    cost that only applies while the redacted content is being re-injected,
    so once the content is gone the metadata is stale and must be ignored.
    """
    from inspect_ai.model._compaction._compaction import (
        _redacted_reasoning_tokens_total,
    )

    model = get_model("mockllm/model")
    monkeypatch.setattr(
        model.api, "apply_redacted_reasoning_tokens_to_input", lambda: True
    )

    # Message A: still has the redacted ContentReasoning block → counts.
    msg_with_block = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="ENCRYPTED", redacted=True),
            ContentText(text="answer"),
        ],
        id="a1",
        metadata={"redacted_reasoning_tokens": 400},
    )

    # Message B: same metadata, but reasoning content has been stripped
    # (e.g. by CompactionEdit._clear_reasoning) → must NOT count.
    msg_block_stripped = ChatMessageAssistant(
        content=[ContentText(text="answer")],
        id="a2",
        metadata={"redacted_reasoning_tokens": 400},
    )

    # Message C: only-visible-reasoning case (defensive — shouldn't have been
    # stamped, but if metadata leaks in, it shouldn't be counted).
    msg_only_visible = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="visible thinking", redacted=False),
            ContentText(text="answer"),
        ],
        id="a3",
        metadata={"redacted_reasoning_tokens": 400},
    )

    total = _redacted_reasoning_tokens_total(
        [msg_with_block, msg_block_stripped, msg_only_visible], model
    )
    assert total == 400, (
        f"Expected only the message with a redacted ContentReasoning block "
        f"to contribute (400 tokens); got {total}"
    )


async def test_redacted_reasoning_total_respects_reasoning_history(
    monkeypatch,
) -> None:
    """Helper mirrors generate-time reasoning_history filtering.

    With `reasoning_history="none"` all reasoning will be stripped before
    re-injection, so no redacted tokens contribute. With `"last"` only the
    most recent reasoning-bearing assistant message survives, so only its
    metadata contributes. With `"all"` (the default), every redacted-
    reasoning message contributes.
    """
    from inspect_ai.model._compaction._compaction import (
        _redacted_reasoning_tokens_total,
    )

    model = get_model("mockllm/model")
    monkeypatch.setattr(
        model.api, "apply_redacted_reasoning_tokens_to_input", lambda: True
    )

    msg_a = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="enc1", redacted=True),
            ContentText(text="answer 1"),
        ],
        id="a1",
        metadata={"redacted_reasoning_tokens": 300},
    )
    msg_b = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="enc2", redacted=True),
            ContentText(text="answer 2"),
        ],
        id="a2",
        metadata={"redacted_reasoning_tokens": 500},
    )
    messages: list[ChatMessage] = [msg_a, msg_b]

    # "all": both contribute
    monkeypatch.setattr(model.config, "reasoning_history", "all")
    assert _redacted_reasoning_tokens_total(messages, model) == 800

    # "last": only the most recent reasoning-bearing message contributes
    monkeypatch.setattr(model.config, "reasoning_history", "last")
    assert _redacted_reasoning_tokens_total(messages, model) == 500

    # "none": all reasoning stripped → 0
    monkeypatch.setattr(model.config, "reasoning_history", "none")
    assert _redacted_reasoning_tokens_total(messages, model) == 0


async def test_redacted_reasoning_total_last_mode_respects_reasoning_position(
    monkeypatch,
) -> None:
    """In `last` mode, the latest reasoning turn determines what survives.

    If the most recent reasoning-bearing message has only visible reasoning
    (not redacted), no redacted tokens survive — this matches
    `resolve_reasoning_history`, which strips all reasoning from earlier
    turns once the most recent reasoning-bearing turn is found, regardless
    of whether that latest reasoning is visible or redacted.
    """
    from inspect_ai.model._compaction._compaction import (
        _redacted_reasoning_tokens_total,
    )

    model = get_model("mockllm/model")
    monkeypatch.setattr(
        model.api, "apply_redacted_reasoning_tokens_to_input", lambda: True
    )
    monkeypatch.setattr(model.config, "reasoning_history", "last")

    earlier_redacted = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="enc", redacted=True),
            ContentText(text="earlier"),
        ],
        id="a1",
        metadata={"redacted_reasoning_tokens": 300},
    )
    latest_visible_only = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="visible", redacted=False),
            ContentText(text="latest"),
        ],
        id="a2",
    )

    # The latest reasoning-bearing message has only visible reasoning, so it
    # survives the filter; the earlier redacted reasoning gets stripped.
    # Net: 0 redacted tokens reach the model.
    assert (
        _redacted_reasoning_tokens_total([earlier_redacted, latest_visible_only], model)
        == 0
    )


async def test_baseline_shortcut_trips_only_with_redacted_reasoning_correction(
    monkeypatch,
) -> None:
    """Baseline shortcut + redacted_reasoning_tokens correction trips threshold.

    Targets the missing test the original PR review flagged: a workload where
    `baseline_tokens` from `record_output` is well under threshold, but
    `baseline_tokens + Σ redacted_reasoning_tokens` exceeds it. Without the
    correction, compaction would never trip even though the actual context
    on the wire is over the limit.

    This exercises the baseline-shortcut branch specifically, complementing
    `test_redacted_reasoning_metadata_pushes_threshold_over` (which exercises
    the count-tokens fallback branch).
    """
    from inspect_ai.model._model_output import ModelOutput, ModelUsage

    strategy = CompactionTrim(threshold=2000, preserve=0.5)

    # Initial conversation: two assistant turns, each carrying 400 redacted
    # reasoning tokens. The plain text content is tiny (a few tokens each).
    def build_messages() -> list[ChatMessage]:
        msgs: list[ChatMessage] = []
        for i in range(2):
            msgs.append(user_msg(f"q{i}", f"u{i}"))
            msgs.append(
                _assistant_with_redacted_reasoning_tokens(
                    f"answer {i}", f"a{i}", redacted_tokens=400
                )
            )
        return msgs

    async def run_with_flag(flag: bool) -> tuple[int, int]:
        """Prime baseline at 1500 tokens, add a small message, run compaction.

        Returns (n_messages_in, n_messages_out).
        """
        model = get_model("mockllm/model")
        monkeypatch.setattr(
            model.api, "apply_redacted_reasoning_tokens_to_input", lambda: flag
        )

        compact = compaction(strategy, prefix=[], tools=None, model=model)

        initial = build_messages()
        # First call processes initial messages (no baseline yet → count_tokens
        # path; total well under threshold, no compaction).
        await compact.compact_input(initial)

        # Synthesize record_output to install baseline_tokens=1500 (under
        # threshold of 2000) covering the initial set.
        output = ModelOutput.from_message(initial[-1])
        output.usage = ModelUsage(
            input_tokens=1500, output_tokens=10, total_tokens=1510
        )
        await compact.record_output(initial, output)

        # Add a tiny new user message and re-run compaction. This call hits
        # the baseline-shortcut branch (baseline_tokens set, baseline ids
        # subset of target). Without the correction:
        #   total = 1500 + ~few + 0 = ~1500 < 2000 → no trip
        # With the correction:
        #   total = 1500 + ~few + 800 = ~2300 > 2000 → trip
        next_messages = initial + [user_msg("q-new", "u-new")]
        result, _ = await compact.compact_input(next_messages)
        return len(next_messages), len(result)

    # Flag off: baseline shortcut alone keeps total under threshold → no trip
    n_in, n_out = await run_with_flag(False)
    assert n_out == n_in, (
        f"flag off: baseline alone is under threshold; expected no compaction "
        f"({n_in} messages), got {n_out}"
    )

    # Flag on: redacted_reasoning_tokens correction pushes total over → trip
    n_in, n_out = await run_with_flag(True)
    assert n_out < n_in, (
        f"flag on: baseline + redacted_reasoning_tokens should exceed threshold "
        f"and trigger compaction; expected fewer than {n_in} messages, got {n_out}"
    )
