import pytest
from test_helpers.tools import addition
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    ContentImage,
    ContentText,
    get_model,
)
from inspect_ai.model._model import collapse_consecutive_user_messages
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


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_anthropic_user_tool_messages() -> None:
    # Anthropic converts 'tool' messages into 'user' messages with tool content.
    # In the case where an additional user message is appended after the tool
    # call response, this results in an error unless the user messages are
    # correctly combined into a single one w/ tool and text content.
    try:
        model = get_model("anthropic/claude-3-haiku-20240307")
        await model.generate(
            input=[
                ChatMessageUser(content="What is 1 + 1?"),
                ChatMessageAssistant(
                    content="I can proceed with calling the add tool to compute the result.",
                    tool_calls=[
                        ToolCall(
                            id="toolu_01AhP9RozXEJSnuxMLcY8Xaf",
                            type="function",
                            function="addition",
                            arguments={"x": 1, "y": 1},
                        )
                    ],
                ),
                ChatMessageTool(
                    content="2",
                    tool_call_id="toolu_01AhP9RozXEJSnuxMLcY8Xaf",
                    function="addition",
                ),
                ChatMessageUser(content="Keep going!"),
            ],
            tools=[addition()],
        )
    except Exception as ex:
        pytest.fail(f"Exception raised: {ex}")
