import pytest

from inspect_ai._util.content import ContentAudio, ContentReasoning, ContentText
from inspect_ai.model._openai import (
    messages_from_openai,
    openai_chat_completion_part,
)
from inspect_ai.model._openai_responses import (
    _openai_input_items_from_chat_message_assistant,
)
from inspect_ai.model._providers.openai_compatible import ModelInfo


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
            "actual tool output",
            "actual tool output",
        ),
        (
            '<think signature="sig">reasoning</think>actual tool output',
            "actual tool output",
        ),
    ],
)
async def test_tool_message_smuggled_variants(tool_content, expected):
    messages = [
        DummyMessage("tool", content=tool_content, tool_call_id="abc123"),
    ]
    chat_msgs = await messages_from_openai(messages)
    assert len(chat_msgs) == 1
    msg = chat_msgs[0]
    assert hasattr(msg, "tool_call_id")
    assert msg.content == expected


async def test_assistant_message_with_smuggled_tags():
    # Assistant message with smuggled <think> and <internal> tags
    asst_content = '<think signature="sig">reasoning here</think>assistant output'
    messages = [
        DummyMessage("assistant", content=asst_content),
    ]
    chat_msgs = await messages_from_openai(messages)
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


async def test_assistant_tool_call_with_smuggled_reasoning_only():
    messages = [
        DummyMessage(
            "assistant",
            content='<think signature="sig" redacted="true">encrypted</think>',
        ),
    ]
    messages[0]["tool_calls"] = [
        {
            "id": "call_123",
            "type": "function",
            "function": {"name": "lookup", "arguments": "{}"},
        }
    ]

    chat_msgs = await messages_from_openai(messages)

    assert len(chat_msgs) == 1
    msg = chat_msgs[0]
    assert msg.tool_calls is not None
    assert msg.tool_calls[0].function == "lookup"
    assert isinstance(msg.content, list)
    assert [type(c) for c in msg.content] == [ContentReasoning]
    assert msg.content[0].reasoning == "encrypted"
    assert msg.content[0].signature == "sig"
    assert msg.content[0].redacted is True


async def test_assistant_tool_call_with_list_smuggled_reasoning_only():
    messages = [
        DummyMessage(
            "assistant",
            content=[
                {
                    "type": "text",
                    "text": '<think signature="sig" redacted="true">encrypted</think>',
                }
            ],
        ),
    ]
    messages[0]["tool_calls"] = [
        {
            "id": "call_123",
            "type": "function",
            "function": {"name": "lookup", "arguments": "{}"},
        }
    ]

    chat_msgs = await messages_from_openai(messages)

    assert len(chat_msgs) == 1
    msg = chat_msgs[0]
    assert msg.tool_calls is not None
    assert msg.tool_calls[0].function == "lookup"
    assert isinstance(msg.content, list)
    assert [type(c) for c in msg.content] == [ContentReasoning]
    assert msg.content[0].reasoning == "encrypted"
    assert msg.content[0].signature == "sig"
    assert msg.content[0].redacted is True

    items = _openai_input_items_from_chat_message_assistant(
        msg, ModelInfo(), synthesize_phase=True
    )
    assert [item.get("type") for item in items] == ["reasoning", "function_call"]
    assert items[0]["encrypted_content"] == "encrypted"
    assert items[0]["id"] == "sig"


async def test_assistant_list_smuggled_reasoning_only_without_tool_call():
    messages = [
        DummyMessage(
            "assistant",
            content=[
                {
                    "type": "text",
                    "text": '<think signature="sig" redacted="true">encrypted</think>',
                }
            ],
        ),
    ]

    chat_msgs = await messages_from_openai(messages)

    assert len(chat_msgs) == 1
    msg = chat_msgs[0]
    assert isinstance(msg.content, list)
    assert [type(c) for c in msg.content] == [ContentReasoning]
    assert msg.content[0].reasoning == "encrypted"
    assert msg.content[0].signature == "sig"
    assert msg.content[0].redacted is True

    items = _openai_input_items_from_chat_message_assistant(msg, ModelInfo())
    assert [item.get("type") for item in items] == ["reasoning", "message"]
    assert items[0]["encrypted_content"] == "encrypted"
    assert items[0]["id"] == "sig"
    assert items[1]["content"][0]["text"] == "(no content)"


async def test_assistant_message_with_openrouter_reasoning_details():
    messages = [
        DummyMessage("assistant", content="assistant output"),
    ]
    messages[0]["reasoning_details"] = [
        {
            "type": "reasoning.text",
            "text": "visible reasoning",
            "format": "unknown",
            "index": 0,
        }
    ]

    chat_msgs = await messages_from_openai(messages)

    assert len(chat_msgs) == 1
    msg = chat_msgs[0]
    assert isinstance(msg.content, list)
    assert isinstance(msg.content[0], ContentReasoning)
    assert msg.content[0].reasoning == "visible reasoning"
    assert "reasoning.text" not in msg.content[0].reasoning
    assert isinstance(msg.content[1], ContentText)
    assert msg.content[1].text == "assistant output"


async def test_user_message_passthrough():
    # User message should be passed through unchanged
    user_content = "user says hello"
    messages = [
        DummyMessage("user", content=user_content),
    ]
    chat_msgs = await messages_from_openai(messages)
    assert len(chat_msgs) == 1
    msg = chat_msgs[0]
    assert msg.content == user_content


async def test_user_input_audio_is_normalized_to_data_uri():
    audio_data = "aGVsbG8="
    messages = [
        DummyMessage(
            "user",
            content=[
                {
                    "type": "input_audio",
                    "input_audio": {"data": audio_data, "format": "mp3"},
                }
            ],
        ),
    ]

    chat_msgs = await messages_from_openai(messages)
    content = chat_msgs[0].content
    assert isinstance(content, list)
    audio = content[0]
    assert isinstance(audio, ContentAudio)
    assert audio.audio == f"data:audio/mpeg;base64,{audio_data}"

    serialized = await openai_chat_completion_part(audio)
    assert serialized["input_audio"] == {"data": audio_data, "format": "mp3"}
