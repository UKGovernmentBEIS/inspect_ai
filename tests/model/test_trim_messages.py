from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    trim_messages,
)
from inspect_ai.tool import ToolCall


# Tests for the trim_messages function
def test_empty_list() -> None:
    """Test trimming an empty list of messages."""
    assert trim_messages([]) == []


def test_simple_conversation() -> None:
    """Test trimming a simple conversation."""
    messages: list[ChatMessage] = [
        ChatMessageSystem(content="You are a helpful assistant."),
        ChatMessageUser(content="Hello!"),
        ChatMessageAssistant(content="How can I help you today?"),
    ]
    # With default preserve=0.7, all messages should be retained
    assert trim_messages(messages) == messages


def test_preserve_ratio() -> None:
    """Test preserving a specific ratio of messages."""
    # Create a longer conversation
    system_message = ChatMessageSystem(content="You are a helpful assistant.")
    messages: list[ChatMessage] = [system_message]
    for i in range(10):
        messages.append(ChatMessageUser(content=f"User message {i}"))
        messages.append(ChatMessageAssistant(content=f"Assistant message {i}"))

    # With preserve=0.5, we should keep 50% of the conversation messages (plus the first user and system message)
    trimmed = trim_messages(messages, preserve=0.5)

    # System message + user message + 10 preserved conversation messages (5 user-assistant pairs)
    assert len(trimmed) == 2 + 10
    # The system message should be the first one
    assert trimmed[0] == system_message
    assert trimmed[1].content == "User message 0"
    assert trimmed[2].content == "User message 5"


def test_tool_message_without_assistant() -> None:
    """Test a tool message without a corresponding assistant message."""
    # A tool message without a corresponding assistant message should be excluded
    tool_message = ChatMessageTool(
        content='{"result": "orphaned"}',
        tool_call_id="orphaned",
        function="orphaned_function",
    )
    user_message = ChatMessageUser(content="User message")

    messages: list[ChatMessage] = [user_message, tool_message]

    # The tool message should be excluded
    trimmed = trim_messages(messages)
    assert tool_message not in trimmed
    assert user_message in trimmed


def test_user_message_resets_tool_ids() -> None:
    """Test that a user message resets the active tool IDs."""
    assistant1 = ChatMessageAssistant(
        content="First tool call",
        tool_calls=[ToolCall(id="tool1", function="func1", arguments={})],
    )

    user = ChatMessageUser(content="User interruption")

    tool1 = ChatMessageTool(
        content='{"result": "result1"}', tool_call_id="tool1", function="func1"
    )

    messages: list[ChatMessage] = [assistant1, user, tool1]

    # The tool message should be excluded since active_tool_ids is reset by the user message
    trimmed = trim_messages(messages)
    assert assistant1 in trimmed
    assert user in trimmed
    assert tool1 not in trimmed


def test_input_source() -> None:
    """Test handling of messages with source='input'."""
    # Test with messages explicitly marked as input
    system_message = ChatMessageSystem(content="You are a helpful assistant.")
    input_user = ChatMessageUser(content="User input", source="input")
    input_assistant = ChatMessageAssistant(content="Assistant input", source="input")
    conversation_user = ChatMessageUser(content="User conversation")
    conversation_assistant = ChatMessageAssistant(content="Assistant conversation")

    messages: list[ChatMessage] = [
        system_message,
        input_user,
        input_assistant,
        conversation_user,
        conversation_assistant,
    ]

    # Even with preserve=0, input messages should be kept
    trimmed = trim_messages(messages, preserve=0)
    assert system_message in trimmed
    assert input_user in trimmed
    assert input_assistant in trimmed
    # But conversation messages should be trimmed
    assert conversation_user not in trimmed
    assert conversation_assistant not in trimmed


def test_preserve_edge_cases() -> None:
    """Test edge cases of the preserve parameter."""
    # Create a longer conversation
    system_message = ChatMessageSystem(content="You are a helpful assistant.")
    messages: list[ChatMessage] = [system_message]
    for i in range(10):
        messages.append(ChatMessageUser(content=f"User message {i}"))
        messages.append(ChatMessageAssistant(content=f"Assistant message {i}"))

    # Test with preserve=0
    trimmed = trim_messages(messages, preserve=0)
    # Only system message and first user message should remain
    assert len(trimmed) == 2
    assert trimmed[0] == system_message

    # Test with preserve=1
    trimmed = trim_messages(messages, preserve=1)
    # All messages should be preserved
    assert trimmed == messages

    # Test with preserve > 1 (should be treated as 1)
    trimmed = trim_messages(messages, preserve=1.5)
    assert trimmed == messages

    # Test with preserve < 0 (should be treated as 0)
    trimmed = trim_messages(messages, preserve=-0.5)
    assert len(trimmed) == 2
    assert trimmed[0] == system_message
