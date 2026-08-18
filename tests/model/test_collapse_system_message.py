from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    ContentText,
)
from inspect_ai.model._model import collapse_consecutive_system_messages


def test_collapse_consecutive_system_messages_single_message():
    messages = [ChatMessageSystem(content="System message")]
    assert collapse_consecutive_system_messages(messages) == messages


def test_collapse_consecutive_system_messages_alternating():
    messages = [
        ChatMessageSystem(content="One"),
        ChatMessageUser(content="Hi"),
        ChatMessageSystem(content="Two"),
    ]
    assert collapse_consecutive_system_messages(messages) == messages


def test_collapse_consecutive_system_messages_two_strings():
    messages = [
        ChatMessageSystem(content="One"),
        ChatMessageSystem(content="Two"),
        ChatMessageUser(content="Hi"),
    ]
    result = collapse_consecutive_system_messages(messages)
    assert len(result) == 2
    assert isinstance(result[0], ChatMessageSystem)
    assert result[0].text == "One\nTwo"
    assert isinstance(result[1], ChatMessageUser)


def test_collapse_consecutive_system_messages_mixed_content_shapes():
    messages = [
        ChatMessageSystem(content="Plain"),
        ChatMessageSystem(
            content=[ContentText(text="Part A"), ContentText(text="Part B")]
        ),
        ChatMessageUser(content="Hi"),
    ]
    result = collapse_consecutive_system_messages(messages)
    assert len(result) == 2
    combined = result[0]
    assert isinstance(combined, ChatMessageSystem)
    assert isinstance(combined.content, list)
    assert [c.text for c in combined.content] == ["Plain", "Part A", "Part B"]


def test_collapse_consecutive_system_messages_three_in_a_row():
    messages = [
        ChatMessageSystem(content="One"),
        ChatMessageSystem(content="Two"),
        ChatMessageSystem(content="Three"),
        ChatMessageUser(content="Hi"),
        ChatMessageAssistant(content="Reply"),
        ChatMessageSystem(content="Late"),
    ]
    result = collapse_consecutive_system_messages(messages)
    assert len(result) == 4
    assert isinstance(result[0], ChatMessageSystem)
    assert result[0].text == "One\nTwo\nThree"
    assert isinstance(result[1], ChatMessageUser)
    assert isinstance(result[2], ChatMessageAssistant)
    assert isinstance(result[3], ChatMessageSystem)
    assert result[3].text == "Late"


def test_collapse_system_messages_preserves_metadata():
    msg_a = ChatMessageSystem(
        content="First",
        source="input",
        metadata={"key1": "val1", "shared": "from_a"},
    )
    msg_b = ChatMessageSystem(
        content="Second",
        source="generate",
        metadata={"key2": "val2", "shared": "from_b"},
    )
    result = collapse_consecutive_system_messages([msg_a, msg_b])
    assert len(result) == 1
    combined = result[0]
    assert isinstance(combined, ChatMessageSystem)
    assert combined.source == "generate"
    assert combined.metadata is not None
    assert combined.metadata["key1"] == "val1"
    assert combined.metadata["key2"] == "val2"
    assert combined.metadata["shared"] == "from_b"
    assert combined.metadata["combined_from"] == [msg_a.id, msg_b.id]
