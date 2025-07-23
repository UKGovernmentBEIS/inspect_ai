import pytest

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.model._openai import chat_messages_from_openai


# Minimal stubs for OpenAI message params
class DummyMessage(dict):
    def __init__(self, role, content=None, tool_call_id=None):
        super().__init__()
        self["role"] = role
        if content is not None:
            self["content"] = content
        if tool_call_id is not None:
            self["tool_call_id"] = tool_call_id


@pytest.mark.parametrize(
    "tool_content,expected",
    [
        ("plain tool output", "plain tool output"),
        (
            '<think signature="sig">reasoning</think>actual tool output',
            "actual tool output",
        ),
        (
            "actual tool output<internal>eyJmb28iOiAiYmFyIn0=</internal>",
            "actual tool output",
        ),
        (
            '<think signature="sig">reasoning</think>actual tool<internal>eyJmb28iOiAiYmFyIn0=</internal> output',
            "actual tool output",
        ),
    ],
)
def test_tool_message_smuggled_variants(tool_content, expected):
    messages = [
        DummyMessage("tool", content=tool_content, tool_call_id="abc123"),
    ]
    chat_msgs = chat_messages_from_openai("test-model", messages)
    assert len(chat_msgs) == 1
    msg = chat_msgs[0]
    assert hasattr(msg, "tool_call_id")
    assert msg.content == expected


def test_assistant_message_with_smuggled_tags():
    # Assistant message with smuggled <think> and <internal> tags
    asst_content = (
        '<think signature="sig">reasoning here</think>'
        "assistant output"
        "<internal>eyJmb28iOiAiYmFyIn0=</internal>"
    )
    messages = [
        DummyMessage("assistant", content=asst_content),
    ]
    chat_msgs = chat_messages_from_openai("test-model", messages)
    assert len(chat_msgs) == 1
    msg = chat_msgs[0]
    # Should be a ChatMessageAssistant
    assert hasattr(msg, "model")
    # Content should be a list with ContentReasoning and ContentText
    assert isinstance(msg.content, list)
    assert any(isinstance(c, ContentReasoning) for c in msg.content)
    assert any(isinstance(c, ContentText) for c in msg.content)
    # The ContentText should not contain <think> or <internal>
    for c in msg.content:
        if isinstance(c, ContentText):
            assert "<think" not in c.text
            assert "<internal" not in c.text


def test_user_message_passthrough():
    # User message should be passed through unchanged
    user_content = "user says hello"
    messages = [
        DummyMessage("user", content=user_content),
    ]
    chat_msgs = chat_messages_from_openai("test-model", messages)
    assert len(chat_msgs) == 1
    msg = chat_msgs[0]
    assert msg.content == user_content
