from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.model import ChatMessageUser


def test_chat_message_text_setter_ordering():
    # 1. Message with text first, then image
    msg1 = ChatMessageUser(
        content=[
            ContentText(text="initial text"),
            ContentImage(image="http://example.com/image.png"),
        ]
    )
    msg1.text = "updated text"

    # The text property setter should replace the first text item in-place
    assert isinstance(msg1.content, list)
    assert len(msg1.content) == 2
    assert isinstance(msg1.content[0], ContentText)
    assert msg1.content[0].text == "updated text"
    assert isinstance(msg1.content[1], ContentImage)

    # 2. Message with image first, then text
    msg2 = ChatMessageUser(
        content=[
            ContentImage(image="http://example.com/image.png"),
            ContentText(text="initial text"),
        ]
    )
    msg2.text = "updated text"

    # Should preserve text at index 1
    assert isinstance(msg2.content, list)
    assert len(msg2.content) == 2
    assert isinstance(msg2.content[0], ContentImage)
    assert isinstance(msg2.content[1], ContentText)
    assert msg2.content[1].text == "updated text"

    # 3. Message with multiple text items
    msg3 = ChatMessageUser(
        content=[
            ContentText(text="text 1"),
            ContentImage(image="http://example.com/image.png"),
            ContentText(text="text 2"),
        ]
    )
    msg3.text = "updated text"

    # Multiple text items should collapse into one at the initial text position
    assert isinstance(msg3.content, list)
    assert len(msg3.content) == 2
    assert isinstance(msg3.content[0], ContentText)
    assert msg3.content[0].text == "updated text"
    assert isinstance(msg3.content[1], ContentImage)

    # 4. Message with image only (no text item)
    msg4 = ChatMessageUser(
        content=[
            ContentImage(image="http://example.com/image.png"),
        ]
    )
    msg4.text = "inserted text"

    # Should insert text at index 0
    assert isinstance(msg4.content, list)
    assert len(msg4.content) == 2
    assert isinstance(msg4.content[0], ContentText)
    assert msg4.content[0].text == "inserted text"
    assert isinstance(msg4.content[1], ContentImage)
