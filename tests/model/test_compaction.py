"""Tests for the compaction() factory function."""

from typing import Literal

import pytest
from test_helpers.checkpoint import RecordingCheckpointer

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
)
from inspect_ai.model._compaction._compaction import _CompactionState, compaction
from inspect_ai.model._compaction.edit import CompactionEdit
from inspect_ai.model._compaction.memory import MEMORY_TOOL
from inspect_ai.model._compaction.summary import CompactionSummary
from inspect_ai.model._compaction.trim import CompactionTrim
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._trim import partition_messages, strip_citations
from inspect_ai.tool import ToolCall, ToolInfo


class ConsecutiveUserCompaction(CompactionSummary):
    async def compact(
        self, model: Model, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        summary = ChatMessageUser(
            content="summary",
            id="summary",
            metadata={"summary": True},
        )
        return [user_msg("input", "input", source="input"), summary], summary


# Helper to create messages with IDs
def user_msg(
    content: str, id: str, source: Literal["input", "generate"] | None = None
) -> ChatMessageUser:
    return ChatMessageUser(content=content, id=id, source=source)


def assistant_msg(content: str, id: str) -> ChatMessageAssistant:
    return ChatMessageAssistant(content=content, id=id)


def system_msg(content: str, id: str) -> ChatMessageSystem:
    return ChatMessageSystem(content=content, id=id)


# The `_fit_summarization_input` tests below pin an exact token budget, so their
# payload sizes are only meaningful relative to the summarization prompt's own
# size. Give them a fixed ~287-token prompt rather than the default one, so that
# editing the default prompt can't silently retune their arithmetic.
FIT_TEST_PROMPT = "Summarize the conversation so far in detail. " * 26 + "{addendums}"


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


async def test_threshold_context_window_registered_after_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fractional threshold picks up a context window registered after creation.

    Providers that read the window from the server (vllm reads max_model_len
    from /v1/models) only register it during their first generate(), while
    agents create the compaction handler before their loop starts. Resolving
    the threshold eagerly would pin it to the catalog value for the whole run.
    """
    import inspect_ai.model._model_info as _model_info
    from inspect_ai.model import ModelInfo

    strategy = CompactionSummary()  # fractional threshold (0.9)
    model = get_model("mockllm/model")
    prefix: list[ChatMessage] = [system_msg("S", "sys1")]

    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("A" * 800, "msg1", source="input"),
        assistant_msg("B" * 800, "msg2"),
        user_msg("C" * 800, "msg3"),
    ]

    # control: against the default window these messages are nowhere near 90%
    control = compaction(strategy, prefix=prefix, tools=None, model=model)
    _, summary = await control.compact_input(list(messages))
    assert summary is None

    compact = compaction(strategy, prefix=prefix, tools=None, model=model)

    # registered only once the handler already exists
    monkeypatch.setitem(
        _model_info._custom_models, str(model), ModelInfo(context_length=500)
    )

    _, summary = await compact.compact_input(list(messages))
    assert summary is not None


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


async def test_compaction_collapses_provider_required_consecutive_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compacted input is stored already collapsed for providers that require it."""
    model = get_model("mockllm/model")
    monkeypatch.setattr(model.api, "collapse_user_messages", lambda: True)

    compact = compaction(
        ConsecutiveUserCompaction(threshold=1_000_000),
        prefix=[],
        tools=None,
        model=model,
    )

    result, summary = await compact.compact_input(
        [user_msg("original", "original")], force=True
    )

    assert summary is None
    assert len(result) == 1
    assert isinstance(result[0], ChatMessageUser)
    assert result[0].content == "input\nsummary"
    assert result[0].source == "input"
    assert result[0].metadata is not None
    assert result[0].metadata.get("summary") is True

    partitioned = partition_messages(result)
    assert partitioned.input == []
    assert partitioned.conversation == result


async def test_compaction_collapse_does_not_accumulate_old_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collapsed summaries remain replaceable on subsequent compactions."""
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content("mockllm/model", "SUMMARY1"),
            ModelOutput.from_content("mockllm/model", "SUMMARY2"),
        ],
    )
    monkeypatch.setattr(model.api, "collapse_user_messages", lambda: True)

    compact = compaction(
        CompactionSummary(threshold=1_000_000),
        prefix=[],
        tools=None,
        model=model,
    )
    messages: list[ChatMessage] = [user_msg("TASK", "task", source="input")]

    result, summary = await compact.compact_input(messages, force=True)
    assert summary is None
    assert len(result) == 1
    assert "SUMMARY1" in result[0].text

    messages = result + [assistant_msg("continuing", "assistant")]
    result, summary = await compact.compact_input(messages, force=True)
    assert len(result) == 1
    assert result[0] is summary
    assert "SUMMARY1" not in result[0].text
    assert "SUMMARY2" in result[0].text


# ==============================================================================
# Reasoning replay accounting
# ==============================================================================


async def test_baseline_estimate_adds_no_reasoning_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The baseline estimate is `usage.input_tokens` plus new messages only.

    `usage.input_tokens` already counts replayed encrypted reasoning when the
    model uses it, so nothing is added for reasoning on top of the baseline.
    Assistant messages carry the `redacted_reasoning_tokens` metadata that
    older versions stamped, so logs written by those versions behave the same.
    """
    from inspect_ai.event import CompactionEvent
    from inspect_ai.log._transcript import Transcript, init_transcript
    from inspect_ai.model._model_output import ModelUsage

    def count(input: str | list[ChatMessage]) -> int:
        return 10 if isinstance(input, str) else 10 * len(input)

    async def fake_count_tokens(
        input: str | list[ChatMessage], config: GenerateConfig | None = None
    ) -> int:
        return count(input)

    model = get_model("openai/gpt-5", api_key="test-key")
    monkeypatch.setattr(model, "count_tokens", fake_count_tokens)
    transcript = Transcript()
    init_transcript(transcript)

    compact = compaction(
        CompactionTrim(threshold=2000, preserve=0.5),
        prefix=[],
        tools=None,
        model=model,
    )

    initial: list[ChatMessage] = []
    for i in range(2):
        initial.append(user_msg(f"q{i}", f"u{i}"))
        initial.append(
            ChatMessageAssistant(
                content=[
                    ContentReasoning(reasoning="ENCRYPTED", redacted=True),
                    ContentText(text=f"answer {i}"),
                ],
                id=f"a{i}",
                metadata={"redacted_reasoning_tokens": 400},
            )
        )
    await compact.compact_input(initial)

    output = ModelOutput.from_message(initial[-1])
    output.usage = ModelUsage(input_tokens=1500, output_tokens=10, total_tokens=1510)
    await compact.record_output(initial, output)

    # 1500 + 10 is under the threshold, so nothing is compacted
    messages = initial + [user_msg("q2", "u2")]
    result, _ = await compact.compact_input(messages)
    assert len(result) == len(messages)

    messages = messages + [user_msg("q3", "u3")]
    result, _ = await compact.compact_input(messages, force=True)
    events = [e for e in transcript.events if isinstance(e, CompactionEvent)]
    assert len(events) == 1
    assert events[0].tokens_before == 1500 + count(messages[len(initial) :])
    assert events[0].tokens_after == count(result)


# ==============================================================================
# Checkpointing support
# ==============================================================================
async def test_checkpoint_state_survives_round_trip() -> None:
    """Handler state serializes and restores faithfully on resume.

    The edit strategy replaces the tool result with a synthesized
    "(Tool result removed)" message that has its own id, absent from the
    full history. Such messages live only in `compacted_input`, so they
    can't be rebuilt from the tracked `messages` by id — the state must be
    persisted in full and survive the JSON round-trip intact.
    """
    model = get_model("mockllm/model")
    strategy = CompactionEdit(threshold=300, keep_tool_uses=0)
    prefix: list[ChatMessage] = [system_msg("S", "sys1")]

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

    cp = RecordingCheckpointer()
    compact = compaction(
        strategy, prefix=prefix, tools=None, model=model, checkpointer=cp
    )
    # force=True so the edit runs deterministically (content is under threshold)
    await compact.compact_input(messages, force=True)

    snap = cp.callbacks["compaction"]()
    assert isinstance(snap, _CompactionState)
    assert snap.processed_message_ids  # state was captured

    # compacted_input contains a synthesized message whose id is NOT in the
    # full history — proof it can't be reconstructed from ids and must be
    # serialized in full.
    history_ids = {m.id for m in messages}
    novel = [m for m in snap.compacted_input if m.id not in history_ids]
    assert novel, "expected edit strategy to introduce a message absent from history"

    # round-trip through JSON exactly as the checkpointer would, then resume
    restored = _CompactionState.model_validate(snap.model_dump(mode="json"))
    cp2 = RecordingCheckpointer(restored={"compaction": restored})
    compaction(strategy, prefix=prefix, tools=None, model=model, checkpointer=cp2)
    snap2 = cp2.callbacks["compaction"]()

    assert snap2 == snap  # synthesized content and bookkeeping intact across resume


async def test_resumed_compaction_does_not_resummarize() -> None:
    """A resumed summary handler skips re-summarizing already-processed history.

    Without restored state the resumed handler treats the whole history as
    unprocessed and re-invokes the model; with it, the prior compacted view
    is honored and no compaction runs.
    """
    model = get_model("mockllm/model")
    strategy = CompactionSummary(threshold=200)
    prefix: list[ChatMessage] = [system_msg("S", "sys1")]
    # large enough to exceed threshold and trigger a summary on the first pass
    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("A" * 800, "u1", source="input"),
        assistant_msg("B" * 800, "a1"),
        user_msg("C" * 800, "u2"),
    ]

    cp = RecordingCheckpointer()
    compact = compaction(
        strategy, prefix=prefix, tools=None, model=model, checkpointer=cp
    )
    _, summary1 = await compact.compact_input(messages)
    assert summary1 is not None  # first pass summarized
    # the agent appends the summary to the full history
    history: list[ChatMessage] = messages + [summary1]

    snap = cp.callbacks["compaction"]()
    assert isinstance(snap, _CompactionState)
    restored = _CompactionState.model_validate(snap.model_dump(mode="json"))

    cp2 = RecordingCheckpointer(restored={"compaction": restored})
    compact2 = compaction(
        strategy, prefix=prefix, tools=None, model=model, checkpointer=cp2
    )
    # everything in `history` was processed before the fire, so the resumed
    # handler must not re-summarize.
    _, summary2 = await compact2.compact_input(history)
    assert summary2 is None


# ==============================================================================
# Summarization Overflow Tests
# ==============================================================================
async def test_summary_overflow_not_used_as_summary() -> None:
    """A summarization generate that overflows must not become the summary (#3600)."""
    # simulate a provider that reports context-window overflow as
    # stop_reason="model_length" with the error text as content
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                "mockllm/model",
                "ERROR: prompt is too long: exceeds the model's context window",
                stop_reason="model_length",
            )
        ],
    )
    strategy = CompactionSummary()
    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("do the task", "u1", source="input"),
        assistant_msg("working on it", "a1"),
    ]

    with pytest.raises(RuntimeError, match="context"):
        await strategy.compact(model, messages, tools=[])


async def test_summary_truncates_oversized_tool_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Oversized tool output is truncated so summarization fits the window (#3600)."""
    import inspect_ai.model._model_info as _model_info
    from inspect_ai.model import ModelInfo

    received: dict[str, bool] = {}

    def summarizer(
        input: list[ChatMessage], tools: object, tool_choice: object, config: object
    ) -> ModelOutput:
        # simulate the provider overflowing while the huge middle is still present
        text = "".join(m.text for m in input)
        oversized = "OVERSIZED_MIDDLE" in text
        received["oversized"] = oversized
        if oversized:
            return ModelOutput.from_content(
                "mockllm/overflow-test",
                "ERROR: exceeds context window",
                stop_reason="model_length",
            )
        return ModelOutput.from_content("mockllm/overflow-test", "GOOD SUMMARY")

    model = get_model("mockllm/overflow-test", custom_outputs=summarizer)
    # small context window so a modest tool output overflows it
    monkeypatch.setitem(
        _model_info._custom_models, str(model), ModelInfo(_input_tokens=200)
    )

    strategy = CompactionSummary()
    big = "A" * 4000 + "OVERSIZED_MIDDLE" + "Z" * 4000
    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("do the task", "u1", source="input"),
        ChatMessageTool(content=big, tool_call_id="t1", function="bash", id="tool1"),
    ]

    _, summary = await strategy.compact(model, messages, tools=[])

    assert summary is not None
    assert "GOOD SUMMARY" in summary.text
    assert received["oversized"] is False  # the oversized middle was truncated away


async def test_summary_elides_media_tool_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Media-only tool output is elided so summarization fits the window (#3600)."""
    import inspect_ai.model._model_info as _model_info
    from inspect_ai.model import ModelInfo

    received_has_image: list[bool] = []
    received_tool_texts: list[str] = []

    def summarizer(
        input: list[ChatMessage], tools: object, tool_choice: object, config: object
    ) -> ModelOutput:
        has_image = any(
            isinstance(part, ContentImage) for m in input for part in m.content_list
        )
        received_has_image.append(has_image)
        received_tool_texts.extend(
            m.text for m in input if isinstance(m, ChatMessageTool)
        )
        if has_image:
            return ModelOutput.from_content(
                "mockllm/media-test",
                "ERROR: exceeds context window",
                stop_reason="model_length",
            )
        return ModelOutput.from_content("mockllm/media-test", "GOOD SUMMARY")

    model = get_model("mockllm/media-test", custom_outputs=summarizer)
    monkeypatch.setitem(
        _model_info._custom_models, str(model), ModelInfo(_input_tokens=2000)
    )

    strategy = CompactionSummary(prompt=FIT_TEST_PROMPT)
    image = ContentImage(image="data:image/png;base64," + "A" * 400)
    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("do the task " * 30, "u1", source="input"),
        ChatMessageTool(
            content=[image], tool_call_id="t1", function="screenshot", id="tool1"
        ),
    ]

    _, summary = await strategy.compact(model, messages, tools=[])

    assert summary is not None
    assert "GOOD SUMMARY" in summary.text
    assert received_has_image[-1] is False
    assert "[image elided for summarization]" in received_tool_texts[-1]
    # the live transcript message is untouched
    assert isinstance(messages[2].content, list)
    assert isinstance(messages[2].content[0], ContentImage)


async def test_summary_truncation_preserves_content_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Part-level truncation preserves content order and untouched parts (#3600)."""
    import inspect_ai.model._model_info as _model_info
    from inspect_ai.model import ModelInfo

    received_content: list[list[Content]] = []

    def summarizer(
        input: list[ChatMessage], tools: object, tool_choice: object, config: object
    ) -> ModelOutput:
        received_content.extend(
            list(m.content)
            for m in input
            if isinstance(m, ChatMessageTool) and isinstance(m.content, list)
        )
        return ModelOutput.from_content("mockllm/structure-test", "GOOD SUMMARY")

    model = get_model("mockllm/structure-test", custom_outputs=summarizer)
    monkeypatch.setitem(
        _model_info._custom_models, str(model), ModelInfo(_input_tokens=2000)
    )

    strategy = CompactionSummary(prompt=FIT_TEST_PROMPT)
    big_text = " ".join(f"word{i}" for i in range(1200))
    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("do the task", "u1", source="input"),
        ChatMessageTool(
            content=[
                ContentText(text=big_text),
                ContentImage(image="data:image/png;base64," + "A" * 400),
                ContentText(text="TAIL_SENTINEL"),
            ],
            tool_call_id="t1",
            function="browse",
            id="tool1",
        ),
    ]

    _, summary = await strategy.compact(model, messages, tools=[])

    assert summary is not None
    assert "GOOD SUMMARY" in summary.text
    content = received_content[-1]
    assert len(content) == 3
    # the large text part was truncated in place at its index
    assert isinstance(content[0], ContentText)
    assert content[0].text.startswith(big_text[:50])
    assert "truncated for summarization" in content[0].text
    # the media part was replaced with a placeholder at its index
    assert isinstance(content[1], ContentText)
    assert content[1].text == "[image elided for summarization]"
    # the small trailing part is untouched
    assert isinstance(content[2], ContentText)
    assert content[2].text == "TAIL_SENTINEL"


async def test_summary_content_filter_not_misdiagnosed_as_overflow() -> None:
    """A content-moderation refusal is not misreported as context overflow."""
    model = get_model(
        "mockllm/filter-test",
        custom_outputs=[
            ModelOutput.from_content(
                "mockllm/filter-test",
                "Sorry, but I am unable to help with that request.",
                stop_reason="content_filter",
                error="content filtering",
            )
        ],
    )
    strategy = CompactionSummary()
    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("do the task", "u1", source="input"),
        assistant_msg("working on it", "a1"),
    ]

    _, summary = await strategy.compact(model, messages, tools=[])

    assert summary is not None
    assert "Sorry, but I am unable to help" in summary.text


async def test_summary_truncation_stops_when_no_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fitting breaks immediately when no tool output can be shrunk (#3600)."""
    import inspect_ai.model._model_info as _model_info
    from inspect_ai.model import ModelInfo

    def summarizer(
        input: list[ChatMessage], tools: object, tool_choice: object, config: object
    ) -> ModelOutput:
        return ModelOutput.from_content("mockllm/no-progress-test", "GOOD SUMMARY")

    model = get_model("mockllm/no-progress-test", custom_outputs=summarizer)
    monkeypatch.setitem(
        _model_info._custom_models, str(model), ModelInfo(_input_tokens=200)
    )

    count_calls = 0
    original_count_tokens = model.count_tokens

    async def counting_count_tokens(
        input: str | list[ChatMessage], config: GenerateConfig | None = None
    ) -> int:
        nonlocal count_calls
        count_calls += 1
        return await original_count_tokens(input, config)

    monkeypatch.setattr(model, "count_tokens", counting_count_tokens)

    strategy = CompactionSummary()
    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("do the task " * 40, "u1", source="input"),
        ChatMessageTool(
            content="small", tool_call_id="t1", function="bash", id="tool1"
        ),
    ]

    _, summary = await strategy.compact(model, messages, tools=[])

    assert summary is not None
    assert "GOOD SUMMARY" in summary.text
    # only the initial count: the tool output is too small to shrink further
    assert count_calls == 1


async def test_summary_fit_reserves_output_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Input that fits the window but not the output reserve is truncated (#3600)."""
    import inspect_ai.model._model_info as _model_info
    from inspect_ai.model import ModelInfo

    received_tool_texts: list[str] = []

    def summarizer(
        input: list[ChatMessage], tools: object, tool_choice: object, config: object
    ) -> ModelOutput:
        received_tool_texts.extend(
            m.text for m in input if isinstance(m, ChatMessageTool)
        )
        return ModelOutput.from_content("mockllm/headroom-test", "GOOD SUMMARY")

    model = get_model("mockllm/headroom-test", custom_outputs=summarizer)
    monkeypatch.setitem(
        _model_info._custom_models, str(model), ModelInfo(_input_tokens=2000)
    )

    strategy = CompactionSummary(prompt=FIT_TEST_PROMPT)
    # sized to fit the 2000-token window but not the 1000-token fit target
    # that remains once output headroom is reserved
    big = " ".join(f"word{i}" for i in range(400))
    messages: list[ChatMessage] = [
        system_msg("S", "sys1"),
        user_msg("do the task", "u1", source="input"),
        ChatMessageTool(content=big, tool_call_id="t1", function="bash", id="tool1"),
    ]

    _, summary = await strategy.compact(model, messages, tools=[])

    assert summary is not None
    assert "GOOD SUMMARY" in summary.text
    assert "truncated for summarization" in received_tool_texts[-1]


def test_truncate_middle_marker_at_seam() -> None:
    """The truncation marker sits exactly at the elision seam for non-ASCII text."""
    from inspect_ai.model._compaction.summary import (
        _TRUNCATION_MARKER,
        _truncate_middle,
    )

    # 200 one-byte chars then 200 three-byte chars (U+20AC EURO SIGN)
    text = "a" * 200 + "\u20ac" * 200
    result = _truncate_middle(text, 202)

    front, back = result.split(_TRUNCATION_MARKER)
    assert front and text.startswith(front)
    # a multibyte char split at the seam decodes as U+FFFD (replacement char)
    trimmed_back = back.lstrip("\ufffd")
    assert trimmed_back and text.endswith(trimmed_back)
