import pytest

from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    ContentImage,
    ContentText,
)
from inspect_ai.model._model import collapse_consecutive_assistant_messages


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
