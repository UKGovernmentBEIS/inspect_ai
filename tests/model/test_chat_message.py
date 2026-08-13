from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.model import ChatMessageUser


def test_chat_message_text_setter_order_preservation():
    msg = ChatMessageUser(
        content=[
            ContentText(text="initial text"),
            ContentImage(image="http://example.com/image.png"),
        ]
    )
    msg.text = "updated text"

    assert [c.type for c in msg.content] == ["text", "image"]
    assert msg.content[0].text == "updated text"


def test_chat_message_text_setter_image_first():
    msg = ChatMessageUser(
        content=[
            ContentImage(image="http://example.com/image.png"),
            ContentText(text="initial text"),
        ]
    )
    msg.text = "updated text"

    assert [c.type for c in msg.content] == ["image", "text"]
    assert msg.content[1].text == "updated text"


def test_chat_message_text_setter_multiple_text_blocks():
    msg = ChatMessageUser(
        content=[
            ContentText(text="first text"),
            ContentImage(image="http://example.com/image.png"),
            ContentText(text="second text"),
        ]
    )
    msg.text = "updated text"

    assert [c.type for c in msg.content] == ["text", "image"]
    assert len(msg.content) == 2
    assert msg.content[0].text == "updated text"


def test_chat_message_text_setter_no_text_block():
    msg = ChatMessageUser(
        content=[
            ContentImage(image="http://example.com/image.png"),
        ]
    )
    msg.text = "inserted text"

    assert [c.type for c in msg.content] == ["text", "image"]
    assert msg.content[0].text == "inserted text"