import pytest

from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    ContentImage,
    ContentText,
)
from inspect_ai.model._model import collapse_consecutive_user_messages


@pytest.fixture
def user_message_str():
    return ChatMessageUser(content="User message")


@pytest.fixture
def user_message_image_and_str():
    return ChatMessageUser(
        content=[ContentImage(image="foo"), ContentText(text="Message")]
    )


@pytest.fixture
def assistant_message():
    return ChatMessageAssistant(content="Assistant message")


@pytest.fixture
def combined_user_message():
    return ChatMessageUser(
        content=[ContentText(text="Message 1"), ContentText(text="Message 2")]
    )


def test_collapse_consecutive_user_messages_single_user_message(user_message_str):
    messages = [user_message_str]
    assert collapse_consecutive_user_messages(messages) == messages


def test_collapse_consecutive_user_messages_alternating_messages(
    user_message_str, assistant_message
):
    messages = [user_message_str, assistant_message, user_message_str]
    assert collapse_consecutive_user_messages(messages) == messages


def test_collapse_consecutive_user_messages_consecutive_user_messages(user_message_str):
    messages = [user_message_str, user_message_str, user_message_str]
    assert len(collapse_consecutive_user_messages(messages)) == 1


def test_collapse_consecutive_user_messages_with_image_message(
    user_message_image_and_str,
):
    messages = [user_message_image_and_str, user_message_image_and_str]
    assert len(collapse_consecutive_user_messages(messages)) == 1
    assert isinstance(
        collapse_consecutive_user_messages(messages)[0].content[0], ContentImage
    )
