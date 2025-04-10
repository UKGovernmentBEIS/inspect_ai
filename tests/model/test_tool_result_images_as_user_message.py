from inspect_ai._util.content import ContentText
from inspect_ai.model import ChatMessage, ChatMessageTool, ChatMessageUser, ContentImage
from inspect_ai.model._model import tool_result_images_as_user_message


# see bug description in https://github.com/UKGovernmentBEIS/inspect_ai/pull/1217
def test_multiple_tool_responses_remain_adjacent():
    tool_a = ChatMessageTool(
        tool_call_id="a",
        content=[ContentImage(image="image_for_a")],
    )
    tool_b = ChatMessageTool(
        tool_call_id="b",
        content=[ContentImage(image="image_for_b")],
    )

    execute_and_assert(
        [tool_a, tool_b],
        [
            _modified_image_response_message(tool_a),
            _modified_image_response_message(tool_b),
            ChatMessageUser(
                content=tool_a.content + tool_b.content,
                tool_call_id=["a", "b"],
            ),
        ],
    )


def test_multiple_tool_responses_remain_adjacent_when_not_at_end_of_list():
    tool_a = ChatMessageTool(
        tool_call_id="a",
        content=[ContentImage(image="image_for_a")],
    )
    tool_b = ChatMessageTool(
        tool_call_id="b",
        content=[ContentImage(image="image_for_b")],
    )
    user = ChatMessageUser(content="yo")

    execute_and_assert(
        [tool_a, tool_b, user],
        [
            _modified_image_response_message(tool_a),
            _modified_image_response_message(tool_b),
            ChatMessageUser(
                content=tool_a.content + tool_b.content,
                tool_call_id=["a", "b"],
            ),
            user,
        ],
    )


def execute_and_assert(input_messages: list[ChatMessage], expected: list[ChatMessage]):
    # transform the messages
    transformed = tool_result_images_as_user_message(input_messages)

    # compare based on content (as id can't be known in advance)
    assert all([t.content == e.content] for t, e in zip(transformed, expected))


def _modified_image_response_message(message: ChatMessageTool) -> ChatMessageTool:
    return message.model_copy(
        update={"content": [ContentText(text="Image content is included below.")]}
    )
