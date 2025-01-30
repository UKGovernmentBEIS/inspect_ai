from inspect_ai._util.content import ContentText
from inspect_ai.model import ChatMessageTool, ChatMessageUser, ContentImage
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
    messages = [tool_a, tool_b]

    modified_a = _modified_image_response_message(tool_a)
    modified_b = _modified_image_response_message(tool_b)
    fabricated_user = ChatMessageUser(
        content=tool_a.content + tool_b.content, tool_call_id=["a", "b"]
    )

    assert tool_result_images_as_user_message(messages) == [
        modified_a,
        modified_b,
        fabricated_user,
    ]


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
    messages = [tool_a, tool_b, user]

    modified_a = _modified_image_response_message(tool_a)
    modified_b = _modified_image_response_message(tool_b)
    fabricated_user = ChatMessageUser(
        content=tool_a.content + tool_b.content, tool_call_id=["a", "b"]
    )

    assert tool_result_images_as_user_message(messages) == [
        modified_a,
        modified_b,
        fabricated_user,
        user,
    ]


def _modified_image_response_message(message: ChatMessageTool) -> ChatMessageTool:
    return message.model_copy(
        update={"content": [ContentText(text="Image content is included below.")]}
    )
