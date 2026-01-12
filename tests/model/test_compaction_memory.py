"""Tests for memory integration with compaction strategies."""

import pytest

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._compaction.edit import CompactionEdit
from inspect_ai.model._compaction.memory import clear_memory_content
from inspect_ai.model._compaction.trim import CompactionTrim
from inspect_ai.model._model import get_model
from inspect_ai.tool import ToolCall

# Fixtures


@pytest.fixture
def memory_create_call() -> ToolCall:
    return ToolCall(
        id="mem1",
        function="memory",
        arguments={
            "command": "create",
            "path": "/memories/notes.txt",
            "file_text": "Large content that should be cleared...",
        },
    )


@pytest.fixture
def memory_insert_call() -> ToolCall:
    return ToolCall(
        id="mem2",
        function="memory",
        arguments={
            "command": "insert",
            "path": "/memories/notes.txt",
            "insert_line": 5,
            "insert_text": "Inserted content to be cleared...",
        },
    )


@pytest.fixture
def memory_str_replace_call() -> ToolCall:
    return ToolCall(
        id="mem3",
        function="memory",
        arguments={
            "command": "str_replace",
            "path": "/memories/notes.txt",
            "old_str": "old text",
            "new_str": "New replacement text to be cleared...",
        },
    )


@pytest.fixture
def non_memory_call() -> ToolCall:
    return ToolCall(id="tool1", function="bash", arguments={"command": "ls -la"})


# Tests for clear_memory_content()


def test_clear_memory_content_clears_file_text(memory_create_call: ToolCall) -> None:
    """Test that file_text argument is replaced with placeholder."""
    messages: list[ChatMessage] = [
        ChatMessageUser(content="Save this"),
        ChatMessageAssistant(
            content="Saving to memory", tool_calls=[memory_create_call]
        ),
        ChatMessageTool(content="File created", tool_call_id="mem1", function="memory"),
    ]

    result = clear_memory_content(messages)

    assistant = result[1]
    assert isinstance(assistant, ChatMessageAssistant)
    assert assistant.tool_calls is not None
    tc = assistant.tool_calls[0]
    assert tc.arguments["file_text"] == "(content saved to memory)"


def test_clear_memory_content_clears_insert_text(memory_insert_call: ToolCall) -> None:
    """Test that insert_text argument is replaced with placeholder."""
    messages: list[ChatMessage] = [
        ChatMessageUser(content="Insert this"),
        ChatMessageAssistant(content="Inserting", tool_calls=[memory_insert_call]),
        ChatMessageTool(content="Inserted", tool_call_id="mem2", function="memory"),
    ]

    result = clear_memory_content(messages)

    assistant = result[1]
    assert isinstance(assistant, ChatMessageAssistant)
    assert assistant.tool_calls is not None
    tc = assistant.tool_calls[0]
    assert tc.arguments["insert_text"] == "(content saved to memory)"


def test_clear_memory_content_clears_new_str(memory_str_replace_call: ToolCall) -> None:
    """Test that new_str argument is replaced with placeholder."""
    messages: list[ChatMessage] = [
        ChatMessageUser(content="Replace this"),
        ChatMessageAssistant(content="Replacing", tool_calls=[memory_str_replace_call]),
        ChatMessageTool(content="Replaced", tool_call_id="mem3", function="memory"),
    ]

    result = clear_memory_content(messages)

    assistant = result[1]
    assert isinstance(assistant, ChatMessageAssistant)
    assert assistant.tool_calls is not None
    tc = assistant.tool_calls[0]
    assert tc.arguments["new_str"] == "(content saved to memory)"


def test_clear_memory_content_preserves_metadata(
    memory_create_call: ToolCall, memory_str_replace_call: ToolCall
) -> None:
    """Test that metadata arguments are preserved."""
    messages: list[ChatMessage] = [
        ChatMessageAssistant(content="Creating", tool_calls=[memory_create_call]),
        ChatMessageTool(content="Created", tool_call_id="mem1", function="memory"),
        ChatMessageAssistant(content="Replacing", tool_calls=[memory_str_replace_call]),
        ChatMessageTool(content="Replaced", tool_call_id="mem3", function="memory"),
    ]

    result = clear_memory_content(messages)

    # Check create call metadata
    create_tc = result[0]
    assert isinstance(create_tc, ChatMessageAssistant)
    assert create_tc.tool_calls is not None
    tc1 = create_tc.tool_calls[0]
    assert tc1.arguments["command"] == "create"
    assert tc1.arguments["path"] == "/memories/notes.txt"

    # Check str_replace call metadata
    replace_tc = result[2]
    assert isinstance(replace_tc, ChatMessageAssistant)
    assert replace_tc.tool_calls is not None
    tc2 = replace_tc.tool_calls[0]
    assert tc2.arguments["command"] == "str_replace"
    assert tc2.arguments["path"] == "/memories/notes.txt"
    assert tc2.arguments["old_str"] == "old text"  # old_str should be preserved


def test_clear_memory_content_non_memory_tools_unchanged(
    non_memory_call: ToolCall,
) -> None:
    """Test that non-memory tool calls are not modified."""
    messages: list[ChatMessage] = [
        ChatMessageUser(content="Run command"),
        ChatMessageAssistant(content="Running", tool_calls=[non_memory_call]),
        ChatMessageTool(content="Output", tool_call_id="tool1", function="bash"),
    ]

    result = clear_memory_content(messages)

    assistant = result[1]
    assert isinstance(assistant, ChatMessageAssistant)
    assert assistant.tool_calls is not None
    tc = assistant.tool_calls[0]
    assert tc.arguments == {"command": "ls -la"}


def test_clear_memory_content_empty_messages() -> None:
    """Test that empty message list returns empty list."""
    result = clear_memory_content([])
    assert result == []


def test_clear_memory_content_no_tool_calls() -> None:
    """Test that messages without tool calls are unchanged."""
    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Hello"),
        ChatMessageAssistant(content="Hi there"),
    ]

    result = clear_memory_content(messages)

    assert len(result) == 3
    assert result[0].content == "System prompt"
    assert result[1].content == "Hello"
    assert result[2].content == "Hi there"


def test_clear_memory_content_mixed_tools(
    memory_create_call: ToolCall, non_memory_call: ToolCall
) -> None:
    """Test that memory calls are cleared while others are preserved."""
    messages: list[ChatMessage] = [
        ChatMessageAssistant(
            content="Using both tools", tool_calls=[memory_create_call, non_memory_call]
        ),
        ChatMessageTool(content="Created", tool_call_id="mem1", function="memory"),
        ChatMessageTool(content="Output", tool_call_id="tool1", function="bash"),
    ]

    result = clear_memory_content(messages)

    assistant = result[0]
    assert isinstance(assistant, ChatMessageAssistant)
    assert assistant.tool_calls is not None
    assert len(assistant.tool_calls) == 2

    # Memory call should be cleared
    memory_tc = next(tc for tc in assistant.tool_calls if tc.function == "memory")
    assert memory_tc.arguments["file_text"] == "(content saved to memory)"

    # Non-memory call should be unchanged
    bash_tc = next(tc for tc in assistant.tool_calls if tc.function == "bash")
    assert bash_tc.arguments == {"command": "ls -la"}


# Tests for CompactionEdit + Memory integration


@pytest.mark.asyncio
async def test_compaction_edit_clears_memory_content(
    memory_create_call: ToolCall,
) -> None:
    """Test that CompactionEdit with memory=True clears memory content."""
    strategy = CompactionEdit(memory=True, keep_tool_uses=10, keep_thinking_turns="all")

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Save this"),
        ChatMessageAssistant(content="Saving", tool_calls=[memory_create_call]),
        ChatMessageTool(content="Created", tool_call_id="mem1", function="memory"),
    ]

    compacted, _ = await strategy.compact(messages, get_model("mockllm/model"))

    assistant = compacted[1]
    assert isinstance(assistant, ChatMessageAssistant)
    assert assistant.tool_calls is not None
    tc = assistant.tool_calls[0]
    assert tc.arguments["file_text"] == "(content saved to memory)"
    assert tc.arguments["command"] == "create"  # metadata preserved


@pytest.mark.asyncio
async def test_compaction_edit_preserves_memory_content_when_disabled(
    memory_create_call: ToolCall,
) -> None:
    """Test that CompactionEdit with memory=False preserves memory content."""
    strategy = CompactionEdit(
        memory=False, keep_tool_uses=10, keep_thinking_turns="all"
    )

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Save this"),
        ChatMessageAssistant(content="Saving", tool_calls=[memory_create_call]),
        ChatMessageTool(content="Created", tool_call_id="mem1", function="memory"),
    ]

    compacted, _ = await strategy.compact(messages, get_model("mockllm/model"))

    assistant = compacted[1]
    assert isinstance(assistant, ChatMessageAssistant)
    assert assistant.tool_calls is not None
    tc = assistant.tool_calls[0]
    assert tc.arguments["file_text"] == "Large content that should be cleared..."


# Tests for CompactionTrim + Memory integration


@pytest.mark.asyncio
async def test_compaction_trim_clears_memory_content(
    memory_create_call: ToolCall,
) -> None:
    """Test that CompactionTrim with memory=True clears memory content."""
    strategy = CompactionTrim(memory=True, preserve=1.0)

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Save this"),
        ChatMessageAssistant(content="Saving", tool_calls=[memory_create_call]),
        ChatMessageTool(content="Created", tool_call_id="mem1", function="memory"),
    ]

    compacted, _ = await strategy.compact(messages, get_model("mockllm/model"))

    assistant = compacted[1]
    assert isinstance(assistant, ChatMessageAssistant)
    assert assistant.tool_calls is not None
    tc = assistant.tool_calls[0]
    assert tc.arguments["file_text"] == "(content saved to memory)"
    assert tc.arguments["command"] == "create"  # metadata preserved


@pytest.mark.asyncio
async def test_compaction_trim_preserves_memory_content_when_disabled(
    memory_create_call: ToolCall,
) -> None:
    """Test that CompactionTrim with memory=False preserves memory content."""
    strategy = CompactionTrim(memory=False, preserve=1.0)

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Save this"),
        ChatMessageAssistant(content="Saving", tool_calls=[memory_create_call]),
        ChatMessageTool(content="Created", tool_call_id="mem1", function="memory"),
    ]

    compacted, _ = await strategy.compact(messages, get_model("mockllm/model"))

    assistant = compacted[1]
    assert isinstance(assistant, ChatMessageAssistant)
    assert assistant.tool_calls is not None
    tc = assistant.tool_calls[0]
    assert tc.arguments["file_text"] == "Large content that should be cleared..."
