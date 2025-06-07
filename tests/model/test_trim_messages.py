import pytest

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    trim_messages,
)
from inspect_ai.model._trim import PartitionedMessages, _partition_messages
from inspect_ai.tool import ToolCall


@pytest.fixture
def tool_call() -> ToolCall:
    return ToolCall(
        id="tool1", function="get_weather", arguments={"location": "London"}
    )


@pytest.fixture
def assistant_with_tool_call(tool_call: ToolCall) -> ChatMessageAssistant:
    return ChatMessageAssistant(
        content="Let me check the weather for you.", tool_calls=[tool_call]
    )


@pytest.fixture
def tool_response() -> ChatMessageTool:
    return ChatMessageTool(
        content='{"temperature": 22, "condition": "sunny"}',
        tool_call_id="tool1",
        function="get_weather",
    )


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
    assert trim_messages(messages) == messages[:-1]


def test_no_system_messages() -> None:
    """Test trimming a conversation with no system messages."""
    messages: list[ChatMessage] = [
        ChatMessageUser(content="Hello!"),
        ChatMessageAssistant(content="How can I help you today?"),
    ]
    assert trim_messages(messages) == messages[:-1]


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
    assert len(trimmed) == 2 + 10 - 1
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


def test_tool_calls(
    assistant_with_tool_call: ChatMessageAssistant,
    tool_response: ChatMessageTool,
) -> None:
    """Test trimming with tool calls."""
    messages: list[ChatMessage] = [
        ChatMessageSystem(content="You are a helpful assistant."),
        ChatMessageUser(content="Hello!"),
        ChatMessageAssistant(content="Hi there"),
        ChatMessageUser(content="How can you help me today?"),
        assistant_with_tool_call,
        tool_response,
        ChatMessageUser(content="Thanks for the weather info!"),
    ]
    trimmed = trim_messages(messages, preserve=1)
    # All messages should be retained
    assert trimmed == messages

    # Now test with a higher trim rate
    trimmed = trim_messages(messages, preserve=0.5)
    # Even with high trim, tool_response should be kept because assistant_with_tool_call is kept
    assert assistant_with_tool_call in trimmed
    assert tool_response in trimmed


def test_orphaned_tool_responses(
    assistant_with_tool_call: ChatMessageAssistant,
    tool_response: ChatMessageTool,
) -> None:
    """Test handling of orphaned tool responses."""
    system_message = ChatMessageSystem(content="You are a helpful assistant.")
    user_message = ChatMessageUser(content="Hello!")
    # Create a scenario with a tool response without a corresponding assistant message
    messages: list[ChatMessage] = [
        system_message,
        user_message,
        ChatMessageTool(
            content='{"error": "No corresponding assistant"}',
            tool_call_id="orphaned_tool",
            function="unknown_function",
        ),
        assistant_with_tool_call,
        tool_response,
    ]

    trimmed = trim_messages(messages)

    # The orphaned tool message should be removed
    assert (
        len(
            [
                m
                for m in trimmed
                if m.role == "tool" and m.tool_call_id == "orphaned_tool"
            ]
        )
        == 0
    )
    # The valid tool message should be kept
    assert (
        len([m for m in trimmed if m.role == "tool" and m.tool_call_id == "tool1"]) == 1
    )


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


def test_first_user_as_input() -> None:
    """Test that the first user message is treated as input if no input source is specified."""
    # When no source="input" is specified, the first user message becomes input
    system_message = ChatMessageSystem(content="You are a helpful assistant.")
    user1 = ChatMessageUser(content="First user")
    assistant1 = ChatMessageAssistant(content="First assistant")
    user2 = ChatMessageUser(content="Second user")
    assistant2 = ChatMessageAssistant(content="Second assistant")

    messages: list[ChatMessage] = [system_message, user1, assistant1, user2, assistant2]

    # With preserve=0, only system and input (first user) should be kept
    trimmed = trim_messages(messages, preserve=0)
    assert system_message in trimmed
    assert user1 in trimmed
    assert assistant1 not in trimmed


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
    assert trimmed == messages[:-1]

    # Test with preserve > 1
    with pytest.raises(ValueError):
        trim_messages(messages, preserve=1.5)

    # Test with preserve < 0
    with pytest.raises(ValueError):
        trim_messages(messages, preserve=-0.5)


def test_consecutive_assistant_tool_chains() -> None:
    """Test with multiple consecutive assistant-tool chains."""
    # Test with multiple assistant-tool chains
    assistant1 = ChatMessageAssistant(
        content="First tool call",
        tool_calls=[ToolCall(id="tool1", function="func1", arguments={})],
    )
    tool1 = ChatMessageTool(
        content='{"result": "result1"}', tool_call_id="tool1", function="func1"
    )

    assistant2 = ChatMessageAssistant(
        content="Second tool call",
        tool_calls=[ToolCall(id="tool2", function="func2", arguments={})],
    )
    tool2 = ChatMessageTool(
        content='{"result": "result2"}', tool_call_id="tool2", function="func2"
    )

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Can you help?"),
        assistant1,
        tool1,
        assistant2,
        tool2,
    ]

    # With preserve=0.5, we should keep the second assistant-tool chain
    trimmed = trim_messages(messages, preserve=0.5)
    assert assistant1 not in trimmed
    assert tool1 not in trimmed
    assert assistant2 in trimmed
    assert tool2 in trimmed


def test_preserve_assistant_tool_sequence() -> None:
    """Test preserving assistant-tool sequences."""
    # Create a longer conversation with tool calls
    messages: list[ChatMessage] = []
    for i in range(5):
        messages.append(ChatMessageUser(content=f"User message {i}"))
        assistant = ChatMessageAssistant(
            content=f"Assistant message {i}",
            tool_calls=[ToolCall(id=f"tool{i}", function=f"func{i}", arguments={})],
        )
        messages.append(assistant)
        messages.append(
            ChatMessageTool(
                content=f'{{"result": "result{i}"}}',
                tool_call_id=f"tool{i}",
                function=f"func{i}",
            )
        )

    # With preserve=0.4, we should keep 2 out of 5 assistant-tool sequences
    trimmed = trim_messages(messages, preserve=0.4)

    # Check that we have exactly 2 assistant-tool sequences
    assistant_count = len([m for m in trimmed if m.role == "assistant"])
    tool_count = len([m for m in trimmed if m.role == "tool"])
    assert assistant_count == 2
    assert tool_count == 2

    # Check that the tool messages correspond to the assistant messages
    assistant_ids = set()
    for msg in trimmed:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                assistant_ids.add(tc.id)

    tool_ids = set()
    for msg in trimmed:
        if msg.role == "tool":
            tool_ids.add(msg.tool_call_id)

    # All tool IDs should correspond to assistant tool calls
    assert tool_ids.issubset(assistant_ids)


def test_alternating_conversation() -> None:
    """Test with alternating user-assistant pairs."""
    # Create a conversation with alternating user-assistant pairs
    system_message = ChatMessageSystem(content="You are a helpful assistant.")
    messages: list[ChatMessage] = [system_message]
    for i in range(10):
        messages.append(ChatMessageUser(content=f"User message {i}"))
        messages.append(ChatMessageAssistant(content=f"Assistant message {i}"))

    # With preserve=0.5, we should keep 5 out of 10 user-assistant pairs
    trimmed = trim_messages(messages, preserve=0.5)

    # Check that we have the right number of each type of message
    system_count = len([m for m in trimmed if m.role == "system"])
    user_count = len([m for m in trimmed if m.role == "user"])
    assistant_count = len([m for m in trimmed if m.role == "assistant"])

    assert system_count == 1
    assert user_count == 6
    assert assistant_count == 4

    # The conversation should start with "User message 0"
    first_user_idx = next(i for i, m in enumerate(trimmed) if m.role == "user")
    assert trimmed[first_user_idx].content == "User message 0"


# Tests for the _partition_messages helper function
def test_partition_messages() -> None:
    """Test basic message partitioning."""
    system_message = ChatMessageSystem(content="You are a helpful assistant.")
    input_user = ChatMessageUser(content="User input", source="input")
    conversation_user = ChatMessageUser(content="User conversation")
    conversation_assistant = ChatMessageAssistant(content="Assistant conversation")

    messages: list[ChatMessage] = [
        system_message,
        input_user,
        conversation_user,
        conversation_assistant,
    ]

    partitioned = _partition_messages(messages)

    assert partitioned.system == [system_message]
    assert partitioned.input == [input_user]
    assert partitioned.conversation == [conversation_user, conversation_assistant]


def test_partition_no_input_messages() -> None:
    """Test partitioning when no messages have source='input'."""
    system_message = ChatMessageSystem(content="You are a helpful assistant.")
    user1 = ChatMessageUser(content="First user")
    assistant1 = ChatMessageAssistant(content="First assistant")
    user2 = ChatMessageUser(content="Second user")

    messages: list[ChatMessage] = [system_message, user1, assistant1, user2]

    partitioned = _partition_messages(messages)

    assert partitioned.system == [system_message]
    # When no input source is specified, messages up to first user become input
    assert partitioned.input == [user1]
    assert partitioned.conversation == [assistant1, user2]


def test_partition_edge_cases() -> None:
    """Test edge cases for partitioning."""
    # Test with empty list
    assert _partition_messages([]) == PartitionedMessages()

    # Test with only system messages
    system = ChatMessageSystem(content="System message")
    assert _partition_messages([system]) == PartitionedMessages(system=[system])

    # Test with no user messages
    assistant = ChatMessageAssistant(content="Assistant message")
    partitioned = _partition_messages([assistant])
    # Without any user messages, all non-system become input
    assert partitioned.input == [assistant]
    assert partitioned.conversation == []
