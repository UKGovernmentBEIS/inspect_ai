from unittest.mock import MagicMock

import pytest

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._compaction.edit import CompactionEdit
from inspect_ai.tool import ToolCall


@pytest.fixture
def tool_call_1() -> ToolCall:
    return ToolCall(
        id="tool1", function="get_weather", arguments={"location": "London"}
    )


@pytest.fixture
def tool_call_2() -> ToolCall:
    return ToolCall(id="tool2", function="get_time", arguments={"timezone": "UTC"})


@pytest.fixture
def tool_call_3() -> ToolCall:
    return ToolCall(id="tool3", function="search", arguments={"query": "hello"})


@pytest.fixture
def tool_call_4() -> ToolCall:
    return ToolCall(id="tool4", function="read_file", arguments={"path": "/tmp/test"})


# Tests for thinking block clearing


@pytest.mark.asyncio
async def test_clear_thinking_keep_one_turn() -> None:
    """Test that only the last assistant turn keeps thinking blocks."""
    strategy = CompactionEdit(keep_thinking_turns=1, keep_tool_uses=10)

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Question 1"),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="Thinking about question 1"),
                ContentText(text="Answer 1"),
            ]
        ),
        ChatMessageUser(content="Question 2"),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="Thinking about question 2"),
                ContentText(text="Answer 2"),
            ]
        ),
    ]

    compacted, summary = await strategy.compact(messages)

    assert summary is None
    assert len(compacted) == 5

    # First assistant turn should have reasoning cleared
    first_assistant = compacted[2]
    assert isinstance(first_assistant, ChatMessageAssistant)
    assert isinstance(first_assistant.content, list)
    assert len(first_assistant.content) == 1
    assert isinstance(first_assistant.content[0], ContentText)
    assert first_assistant.content[0].text == "Answer 1"

    # Last assistant turn should keep reasoning
    last_assistant = compacted[4]
    assert isinstance(last_assistant, ChatMessageAssistant)
    assert isinstance(last_assistant.content, list)
    assert len(last_assistant.content) == 2
    assert isinstance(last_assistant.content[0], ContentReasoning)


@pytest.mark.asyncio
async def test_clear_thinking_keep_all() -> None:
    """Test that 'all' keeps all thinking blocks."""
    strategy = CompactionEdit(keep_thinking_turns="all", keep_tool_uses=10)

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Question 1"),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="Thinking 1"),
                ContentText(text="Answer 1"),
            ]
        ),
        ChatMessageUser(content="Question 2"),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="Thinking 2"),
                ContentText(text="Answer 2"),
            ]
        ),
    ]

    compacted, _ = await strategy.compact(messages)

    # Both should keep reasoning
    for i in [1, 3]:
        msg = compacted[i]
        assert isinstance(msg, ChatMessageAssistant)
        assert isinstance(msg.content, list)
        assert any(isinstance(c, ContentReasoning) for c in msg.content)


@pytest.mark.asyncio
async def test_clear_thinking_keep_n_turns() -> None:
    """Test keeping last N turns with thinking blocks."""
    strategy = CompactionEdit(keep_thinking_turns=2, keep_tool_uses=10)

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Q1"),
        ChatMessageAssistant(
            content=[ContentReasoning(reasoning="T1"), ContentText(text="A1")]
        ),
        ChatMessageUser(content="Q2"),
        ChatMessageAssistant(
            content=[ContentReasoning(reasoning="T2"), ContentText(text="A2")]
        ),
        ChatMessageUser(content="Q3"),
        ChatMessageAssistant(
            content=[ContentReasoning(reasoning="T3"), ContentText(text="A3")]
        ),
    ]

    compacted, _ = await strategy.compact(messages)

    # First turn should be cleared
    msg1 = compacted[1]
    assert isinstance(msg1, ChatMessageAssistant)
    assert isinstance(msg1.content, list)
    assert not any(isinstance(c, ContentReasoning) for c in msg1.content)

    # Second and third turns should keep reasoning
    for i in [3, 5]:
        msg = compacted[i]
        assert isinstance(msg, ChatMessageAssistant)
        assert isinstance(msg.content, list)
        assert any(isinstance(c, ContentReasoning) for c in msg.content)


@pytest.mark.asyncio
async def test_clear_thinking_string_content() -> None:
    """Test that string content is not affected by thinking clearing."""
    strategy = CompactionEdit(keep_thinking_turns=0, keep_tool_uses=10)

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Question"),
        ChatMessageAssistant(content="Simple string response"),
    ]

    compacted, _ = await strategy.compact(messages)

    msg = compacted[1]
    assert isinstance(msg, ChatMessageAssistant)
    assert msg.content == "Simple string response"


@pytest.mark.asyncio
async def test_clear_thinking_empty_after_clearing() -> None:
    """Test that content becomes empty string when only reasoning is present."""
    strategy = CompactionEdit(keep_thinking_turns=0, keep_tool_uses=10)

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Question"),
        ChatMessageAssistant(content=[ContentReasoning(reasoning="Only thinking")]),
    ]

    compacted, _ = await strategy.compact(messages)

    msg = compacted[1]
    assert isinstance(msg, ChatMessageAssistant)
    assert msg.content == ""


# Tests for tool clearing with keep_tool_inputs=True


@pytest.mark.asyncio
async def test_clear_tool_results_keep_inputs(
    tool_call_1: ToolCall,
    tool_call_2: ToolCall,
    tool_call_3: ToolCall,
    tool_call_4: ToolCall,
) -> None:
    """Test clearing tool results while keeping tool calls."""
    strategy = CompactionEdit(keep_thinking_turns="all", keep_tool_uses=2)

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Start"),
        ChatMessageAssistant(content="Using tool 1", tool_calls=[tool_call_1]),
        ChatMessageTool(
            content="Weather: Sunny", tool_call_id="tool1", function="get_weather"
        ),
        ChatMessageAssistant(content="Using tool 2", tool_calls=[tool_call_2]),
        ChatMessageTool(
            content="Time: 12:00", tool_call_id="tool2", function="get_time"
        ),
        ChatMessageAssistant(content="Using tool 3", tool_calls=[tool_call_3]),
        ChatMessageTool(
            content="Search results", tool_call_id="tool3", function="search"
        ),
        ChatMessageAssistant(content="Using tool 4", tool_calls=[tool_call_4]),
        ChatMessageTool(
            content="File contents", tool_call_id="tool4", function="read_file"
        ),
    ]

    compacted, _ = await strategy.compact(messages)

    # Same number of messages
    assert len(compacted) == 9

    # First two tool results should be cleared
    tool_msg_1 = compacted[2]
    assert isinstance(tool_msg_1, ChatMessageTool)
    assert tool_msg_1.content == "(Tool result removed)"

    tool_msg_2 = compacted[4]
    assert isinstance(tool_msg_2, ChatMessageTool)
    assert tool_msg_2.content == "(Tool result removed)"

    # Last two tool results should be preserved
    tool_msg_3 = compacted[6]
    assert isinstance(tool_msg_3, ChatMessageTool)
    assert tool_msg_3.content == "Search results"

    tool_msg_4 = compacted[8]
    assert isinstance(tool_msg_4, ChatMessageTool)
    assert tool_msg_4.content == "File contents"

    # Tool calls should still be present
    assistant_1 = compacted[1]
    assert isinstance(assistant_1, ChatMessageAssistant)
    assert assistant_1.tool_calls is not None
    assert len(assistant_1.tool_calls) == 1


# Tests for tool clearing with keep_tool_inputs=False


@pytest.mark.asyncio
async def test_clear_tool_results_remove_inputs(
    tool_call_1: ToolCall, tool_call_2: ToolCall
) -> None:
    """Test clearing both tool calls and results."""
    strategy = CompactionEdit(
        keep_thinking_turns="all", keep_tool_uses=1, keep_tool_inputs=False
    )

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Start"),
        ChatMessageAssistant(content="Using tool 1", tool_calls=[tool_call_1]),
        ChatMessageTool(
            content="Weather: Sunny", tool_call_id="tool1", function="get_weather"
        ),
        ChatMessageAssistant(content="Using tool 2", tool_calls=[tool_call_2]),
        ChatMessageTool(
            content="Time: 12:00", tool_call_id="tool2", function="get_time"
        ),
    ]

    compacted, _ = await strategy.compact(messages)

    # Tool message should be removed (was at index 2)
    assert len(compacted) == 4

    # First assistant should have tool call removed and placeholder added
    assistant_1 = compacted[1]
    assert isinstance(assistant_1, ChatMessageAssistant)
    assert assistant_1.tool_calls is None
    assert isinstance(assistant_1.content, list)
    assert any(
        isinstance(c, ContentText)
        and "get_weather" in c.text
        and "removed from history" in c.text
        for c in assistant_1.content
    )

    # Second tool result should be preserved
    tool_msg = compacted[3]
    assert isinstance(tool_msg, ChatMessageTool)
    assert tool_msg.content == "Time: 12:00"


@pytest.mark.asyncio
async def test_clear_tool_multiple_calls_per_turn(
    tool_call_1: ToolCall, tool_call_2: ToolCall, tool_call_3: ToolCall
) -> None:
    """Test clearing when an assistant message has multiple tool calls."""
    strategy = CompactionEdit(
        keep_thinking_turns="all", keep_tool_uses=1, keep_tool_inputs=False
    )

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Start"),
        ChatMessageAssistant(
            content="Using multiple tools", tool_calls=[tool_call_1, tool_call_2]
        ),
        ChatMessageTool(
            content="Weather: Sunny", tool_call_id="tool1", function="get_weather"
        ),
        ChatMessageTool(
            content="Time: 12:00", tool_call_id="tool2", function="get_time"
        ),
        ChatMessageAssistant(content="Using tool 3", tool_calls=[tool_call_3]),
        ChatMessageTool(
            content="Search results", tool_call_id="tool3", function="search"
        ),
    ]

    compacted, _ = await strategy.compact(messages)

    # Two tool messages should be removed (indices 2 and 3)
    # Original: 6 messages, after: 4 messages
    assert len(compacted) == 4

    # First assistant should have both tool calls removed
    assistant_1 = compacted[1]
    assert isinstance(assistant_1, ChatMessageAssistant)
    assert assistant_1.tool_calls is None
    assert isinstance(assistant_1.content, list)
    # Should have placeholders for both tools
    placeholder_texts = [
        c.text for c in assistant_1.content if isinstance(c, ContentText)
    ]
    assert any("get_weather" in t for t in placeholder_texts)
    assert any("get_time" in t for t in placeholder_texts)


# Tests for tool exclusions


@pytest.mark.asyncio
async def test_tool_exclusions(
    tool_call_1: ToolCall, tool_call_2: ToolCall, tool_call_3: ToolCall
) -> None:
    """Test that excluded tools are never cleared."""
    strategy = CompactionEdit(
        keep_thinking_turns="all",
        keep_tool_uses=1,
        exclude_tools=["get_weather"],
    )

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Start"),
        ChatMessageAssistant(content="Using tool 1", tool_calls=[tool_call_1]),
        ChatMessageTool(
            content="Weather: Sunny", tool_call_id="tool1", function="get_weather"
        ),
        ChatMessageAssistant(content="Using tool 2", tool_calls=[tool_call_2]),
        ChatMessageTool(
            content="Time: 12:00", tool_call_id="tool2", function="get_time"
        ),
        ChatMessageAssistant(content="Using tool 3", tool_calls=[tool_call_3]),
        ChatMessageTool(
            content="Search results", tool_call_id="tool3", function="search"
        ),
    ]

    compacted, _ = await strategy.compact(messages)

    # Same number of messages
    assert len(compacted) == 7

    # get_weather should be preserved (excluded)
    tool_msg_1 = compacted[2]
    assert isinstance(tool_msg_1, ChatMessageTool)
    assert tool_msg_1.content == "Weather: Sunny"

    # get_time should be cleared (not in keep_tool_uses=1)
    tool_msg_2 = compacted[4]
    assert isinstance(tool_msg_2, ChatMessageTool)
    assert tool_msg_2.content == "(Tool result removed)"

    # search should be preserved (most recent)
    tool_msg_3 = compacted[6]
    assert isinstance(tool_msg_3, ChatMessageTool)
    assert tool_msg_3.content == "Search results"


# Tests for mixed scenarios


@pytest.mark.asyncio
async def test_mixed_thinking_and_tools(tool_call_1: ToolCall) -> None:
    """Test clearing both thinking and tools together."""
    strategy = CompactionEdit(keep_thinking_turns=1, keep_tool_uses=0)

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Q1"),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="Thinking"),
                ContentText(text="Let me use a tool"),
            ],
            tool_calls=[tool_call_1],
        ),
        ChatMessageTool(
            content="Weather: Sunny", tool_call_id="tool1", function="get_weather"
        ),
        ChatMessageUser(content="Q2"),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="More thinking"),
                ContentText(text="Final answer"),
            ]
        ),
    ]

    compacted, _ = await strategy.compact(messages)

    # First assistant: thinking cleared, tool result cleared
    assistant_1 = compacted[1]
    assert isinstance(assistant_1, ChatMessageAssistant)
    assert isinstance(assistant_1.content, list)
    # No reasoning in first turn
    assert not any(isinstance(c, ContentReasoning) for c in assistant_1.content)

    # Tool result cleared
    tool_msg = compacted[2]
    assert isinstance(tool_msg, ChatMessageTool)
    assert tool_msg.content == "(Tool result removed)"

    # Last assistant keeps reasoning
    assistant_2 = compacted[4]
    assert isinstance(assistant_2, ChatMessageAssistant)
    assert isinstance(assistant_2.content, list)
    assert any(isinstance(c, ContentReasoning) for c in assistant_2.content)


# Tests for edge cases


@pytest.mark.asyncio
async def test_orphaned_tool_calls(tool_call_1: ToolCall) -> None:
    """Test that tool calls without matching results are skipped."""
    strategy = CompactionEdit(keep_thinking_turns="all", keep_tool_uses=0)

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Start"),
        ChatMessageAssistant(content="Using tool", tool_calls=[tool_call_1]),
        # No ChatMessageTool for tool1
        ChatMessageUser(content="User interruption"),
    ]

    compacted, _ = await strategy.compact(messages)

    # No changes - orphaned tool call is skipped
    assert len(compacted) == 3
    assistant = compacted[1]
    assert isinstance(assistant, ChatMessageAssistant)
    assert assistant.tool_calls is not None
    assert len(assistant.tool_calls) == 1


@pytest.mark.asyncio
async def test_keep_tool_uses_zero(tool_call_1: ToolCall, tool_call_2: ToolCall) -> None:
    """Test clearing all tool uses when keep_tool_uses=0."""
    strategy = CompactionEdit(keep_thinking_turns="all", keep_tool_uses=0)

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Start"),
        ChatMessageAssistant(content="Using tool 1", tool_calls=[tool_call_1]),
        ChatMessageTool(
            content="Weather: Sunny", tool_call_id="tool1", function="get_weather"
        ),
        ChatMessageAssistant(content="Using tool 2", tool_calls=[tool_call_2]),
        ChatMessageTool(
            content="Time: 12:00", tool_call_id="tool2", function="get_time"
        ),
    ]

    compacted, _ = await strategy.compact(messages)

    # Both tool results should be cleared
    tool_msg_1 = compacted[2]
    assert isinstance(tool_msg_1, ChatMessageTool)
    assert tool_msg_1.content == "(Tool result removed)"

    tool_msg_2 = compacted[4]
    assert isinstance(tool_msg_2, ChatMessageTool)
    assert tool_msg_2.content == "(Tool result removed)"


@pytest.mark.asyncio
async def test_empty_messages() -> None:
    """Test with empty message list."""
    strategy = CompactionEdit()

    compacted, summary = await strategy.compact([])

    assert compacted == []
    assert summary is None


@pytest.mark.asyncio
async def test_no_assistant_messages() -> None:
    """Test with no assistant messages."""
    strategy = CompactionEdit()

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System"),
        ChatMessageUser(content="User"),
    ]

    compacted, _ = await strategy.compact(messages)

    assert compacted == messages


@pytest.mark.asyncio
async def test_preserve_message_immutability(tool_call_1: ToolCall) -> None:
    """Test that original messages are not mutated."""
    strategy = CompactionEdit(keep_thinking_turns=0, keep_tool_uses=0)

    original_assistant = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="Original thinking"),
            ContentText(text="Original text"),
        ],
        tool_calls=[tool_call_1],
    )
    original_tool = ChatMessageTool(
        content="Original result", tool_call_id="tool1", function="get_weather"
    )

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Start"),
        original_assistant,
        original_tool,
    ]

    await strategy.compact(messages)

    # Original messages should be unchanged
    assert isinstance(original_assistant.content, list)
    assert len(original_assistant.content) == 2
    assert isinstance(original_assistant.content[0], ContentReasoning)
    assert original_tool.content == "Original result"


# Tests for provider opt-out of thinking compaction


@pytest.mark.asyncio
async def test_thinking_preserved_when_provider_opts_out() -> None:
    """Test that thinking blocks are preserved when provider doesn't support compaction."""
    strategy = CompactionEdit(keep_thinking_turns=0, keep_tool_uses=10)

    # Mock the model with an API that returns False for compact_reasoning_history
    mock_api = MagicMock()
    mock_api.compact_reasoning_history.return_value = False
    mock_model = MagicMock()
    mock_model.api = mock_api

    # Inject the mock model
    strategy.model = mock_model

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Question 1"),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="Thinking about question 1"),
                ContentText(text="Answer 1"),
            ]
        ),
        ChatMessageUser(content="Question 2"),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="Thinking about question 2"),
                ContentText(text="Answer 2"),
            ]
        ),
    ]

    compacted, _ = await strategy.compact(messages)

    # Even with keep_thinking_turns=0, all reasoning should be preserved
    # because the provider doesn't support thinking compaction
    for i in [1, 3]:
        msg = compacted[i]
        assert isinstance(msg, ChatMessageAssistant)
        assert isinstance(msg.content, list)
        assert any(isinstance(c, ContentReasoning) for c in msg.content)


@pytest.mark.asyncio
async def test_thinking_cleared_when_provider_supports_it() -> None:
    """Test that thinking blocks are cleared when provider supports compaction."""
    strategy = CompactionEdit(keep_thinking_turns=0, keep_tool_uses=10)

    # Mock the model with an API that returns True for compact_reasoning_history
    mock_api = MagicMock()
    mock_api.compact_reasoning_history.return_value = True
    mock_model = MagicMock()
    mock_model.api = mock_api

    # Inject the mock model
    strategy.model = mock_model

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Question 1"),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="Thinking about question 1"),
                ContentText(text="Answer 1"),
            ]
        ),
        ChatMessageUser(content="Question 2"),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="Thinking about question 2"),
                ContentText(text="Answer 2"),
            ]
        ),
    ]

    compacted, _ = await strategy.compact(messages)

    # With keep_thinking_turns=0 and provider supporting it, all reasoning should be cleared
    for i in [1, 3]:
        msg = compacted[i]
        assert isinstance(msg, ChatMessageAssistant)
        assert isinstance(msg.content, list)
        assert not any(isinstance(c, ContentReasoning) for c in msg.content)
