import pytest

from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    ContentImage,
    ContentText,
)
from inspect_ai.model._model import collapse_consecutive_assistant_messages
from inspect_ai.tool import ToolCall


@pytest.fixture
def user_message_str():
    return ChatMessageUser(content="User message")


@pytest.fixture
def user_message_image_and_str():
    return ChatMessageUser(
        content=[ContentImage(image="foo"), ContentText(text="Message")]
    )


@pytest.fixture
def assistant_message_str():
    return ChatMessageAssistant(content="Assistant message")


def test_collapse_consecutive_assistant_messages_single_assistant_message(
    assistant_message_str,
):
    messages = [assistant_message_str]
    assert collapse_consecutive_assistant_messages(messages) == messages


def test_collapse_consecutive_assistant_messages_alternating_messages(
    user_message_str, user_message_image_and_str, assistant_message_str
):
    messages = [user_message_str]
    assert collapse_consecutive_assistant_messages(messages) == messages

    messages = [user_message_str, assistant_message_str]
    assert collapse_consecutive_assistant_messages(messages) == messages

    messages = [user_message_str, assistant_message_str, user_message_str]
    assert collapse_consecutive_assistant_messages(messages) == messages

    messages = [user_message_str, assistant_message_str, user_message_image_and_str]
    assert collapse_consecutive_assistant_messages(messages) == messages


def test_collapse_consecutive_assistant_messages_consecutive_assistant_messages(
    assistant_message_str,
):
    messages = [assistant_message_str, assistant_message_str, assistant_message_str]
    assert len(collapse_consecutive_assistant_messages(messages)) == 1


def test_collapse_assistant_messages_preserves_fields():
    tool_call_a = ToolCall(id="tc_1", function="foo", arguments={"x": 1})
    tool_call_b = ToolCall(id="tc_2", function="bar", arguments={"y": 2})
    msg_a = ChatMessageAssistant(
        content="First",
        tool_calls=[tool_call_a],
        model="model-a",
        source="generate",
        metadata={"key1": "val1", "shared": "from_a"},
    )
    msg_b = ChatMessageAssistant(
        content="Second",
        tool_calls=[tool_call_b],
        model="model-b",
        source="input",
        metadata={"key2": "val2", "shared": "from_b"},
    )

    result = collapse_consecutive_assistant_messages([msg_a, msg_b])
    assert len(result) == 1
    combined = result[0]
    assert isinstance(combined, ChatMessageAssistant)

    # tool_calls are concatenated
    assert combined.tool_calls == [tool_call_a, tool_call_b]

    # later message's model and source win
    assert combined.model == "model-b"
    assert combined.source == "input"

    # metadata is merged (later wins on conflicts), combined_from is set
    assert combined.metadata is not None
    assert combined.metadata["key1"] == "val1"
    assert combined.metadata["key2"] == "val2"
    assert combined.metadata["shared"] == "from_b"
    assert combined.metadata["combined_from"] == [msg_a.id, msg_b.id]
