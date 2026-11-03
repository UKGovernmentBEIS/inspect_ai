import base64
from unittest.mock import MagicMock

import pytest
from openai.types.chat import ChatCompletionAssistantMessageParam

from inspect_ai._util.content import ContentAudio, ContentReasoning, ContentText
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._openai import (
    messages_from_openai,
    messages_to_openai,
    openai_assistant_content,
    openai_chat_completion_part,
)
from inspect_ai.model._openai_responses import (
    _openai_input_items_from_chat_message_assistant,
)
from inspect_ai.model._providers.google import content as google_content_from_message
from inspect_ai.model._providers.openai_compatible import ModelInfo
from inspect_ai.tool import ToolCall


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


async def test_assistant_message_reasoning_content_round_trip():
    messages = [
        DummyMessage("assistant", content="assistant output"),
    ]
    messages[0]["reasoning_content"] = "visible reasoning"

    chat_msgs = await messages_from_openai(messages)

    assert len(chat_msgs) == 1
    msg = chat_msgs[0]
    assert isinstance(msg.content, list)
    assert isinstance(msg.content[0], ContentReasoning)
    assert msg.content[0].reasoning == "visible reasoning"
    assert msg.content[0].internal == "reasoning_content"
    assert isinstance(msg.content[1], ContentText)
    assert msg.content[1].text == "assistant output"

    # replay should re-emit reasoning as a reasoning_content field (not <think>)
    replayed = await messages_to_openai(chat_msgs)
    assert len(replayed) == 1
    assistant_param = replayed[0]
    assert assistant_param["role"] == "assistant"
    assert assistant_param["reasoning_content"] == "visible reasoning"
    content = assistant_param["content"]
    assert isinstance(content, str)
    assert "<think>" not in content
    assert "assistant output" in content


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


def _gemini_tool_call_message() -> ChatMessageAssistant:
    # the shape of a Gemini 3 tool-calling output from the google provider: a
    # thought summary, text, and the redacted anchor that carries the function
    # call's thought signature
    return ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="Plan the listing", redacted=False),
            ContentText(text="Let me look."),
            ContentReasoning(
                reasoning=base64.b64encode(b"sig-1").decode(),
                redacted=True,
                internal={"gemini_function_call_id": "call_1"},
            ),
        ],
        tool_calls=[
            ToolCall(id="call_1", function="bash", arguments={"command": "ls"})
        ],
    )


async def _bridge_round_trip(as_list: bool) -> ChatMessageAssistant:
    message = _gemini_tool_call_message()
    text, _ = openai_assistant_content(message)
    oai_message: ChatCompletionAssistantMessageParam = {
        "role": "assistant",
        "content": [{"type": "text", "text": text}] if as_list else text,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "bash", "arguments": '{"command": "ls"}'},
            }
        ],
    }
    chat_msgs = await messages_from_openai([oai_message])
    assert len(chat_msgs) == 1
    assert isinstance(chat_msgs[0], ChatMessageAssistant)
    return chat_msgs[0]


@pytest.mark.parametrize("as_list", [False, True])
async def test_assistant_smuggled_reasoning_keeps_text_indentation(as_list: bool):
    original = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="plan"),
            ContentText(text="def f():"),
            ContentReasoning(reasoning="choose result"),
            ContentText(text="    return 1"),
        ]
    )
    text, _ = openai_assistant_content(original)
    oai_message: ChatCompletionAssistantMessageParam = {
        "role": "assistant",
        "content": [{"type": "text", "text": text}] if as_list else text,
    }
    chat_msgs = await messages_from_openai([oai_message])
    assert chat_msgs[0].content == original.content


@pytest.mark.parametrize("as_list", [False, True])
async def test_assistant_multiple_smuggled_reasoning_blocks_round_trip(as_list: bool):
    original = _gemini_tool_call_message()
    restored = await _bridge_round_trip(as_list)
    assert restored.content == original.content


@pytest.mark.parametrize("as_list", [False, True])
async def test_assistant_smuggled_gemini_anchor_replays_thought_signature(
    as_list: bool,
):
    restored = await _bridge_round_trip(as_list)

    google_content = await google_content_from_message(
        MagicMock(), restored, emulate_reasoning=False
    )

    assert google_content.parts is not None
    function_call_parts = [
        p for p in google_content.parts if p.function_call is not None
    ]
    assert len(function_call_parts) == 1
    assert function_call_parts[0].thought_signature == b"sig-1"
    assert not any("<think" in (p.text or "") for p in google_content.parts)
