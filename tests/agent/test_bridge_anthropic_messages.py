from pathlib import Path
from typing import Any, cast

import pytest
from anthropic.types import ThinkingBlockParam

from inspect_ai._util.content import ContentDocument
from inspect_ai.agent._bridge.anthropic_api_impl import (
    anthropic_system_to_text,
    base_64_data,
    content_block_to_content,
    messages_from_anthropic_input,
)
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._providers.anthropic import message_block_params


@pytest.mark.anyio
async def test_inline_system_role_str_content() -> None:
    """Claude 4.8+ clients may send role="system" inside the messages array."""
    messages = await messages_from_anthropic_input(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "system", "content": "<system-reminder>note</system-reminder>"},
            {"role": "user", "content": "continue"},
        ],
        tools=[],
    )
    assert [type(m) for m in messages] == [
        ChatMessageUser,
        ChatMessageAssistant,
        ChatMessageSystem,
        ChatMessageUser,
    ]
    assert messages[2].text == "<system-reminder>note</system-reminder>"


@pytest.mark.anyio
async def test_inline_system_role_block_content() -> None:
    messages = await messages_from_anthropic_input(
        [
            {"role": "user", "content": "hello"},
            {
                "role": "system",
                "content": [{"type": "text", "text": "reminder"}],
            },
        ],
        tools=[],
    )
    assert isinstance(messages[1], ChatMessageSystem)
    assert messages[1].text == "reminder"


@pytest.mark.anyio
async def test_inline_text_document_round_trip() -> None:
    content = content_block_to_content(
        cast(
            Any,
            {
                "type": "document",
                "source": {
                    "type": "text",
                    "data": "hello inline document",
                    "media_type": "text/plain",
                },
            },
        )
    )
    assert isinstance(content, ContentDocument)
    assert content.document.startswith("data:text/plain;base64,")

    blocks = await message_block_params(content)
    block = cast(dict[str, Any], blocks[0])
    source = cast(dict[str, Any], block["source"])
    assert source == {
        "type": "text",
        "data": "hello inline document",
        "media_type": "text/plain",
    }


def test_anthropic_system_to_text() -> None:
    assert anthropic_system_to_text("plain") == "plain"
    assert (
        anthropic_system_to_text(
            [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
        )
        == "a\n\nb"
    )


@pytest.mark.anyio
async def test_unexpected_input_parameter_error_includes_value() -> None:
    """An unhandled user content block reports the offending block, not '{c}'."""
    block: ThinkingBlockParam = {
        "type": "thinking",
        "thinking": "hmm",
        "signature": "sig",
    }
    with pytest.raises(RuntimeError) as exc_info:
        await messages_from_anthropic_input(
            [{"role": "user", "content": [block]}],
            tools=[],
        )
    assert "thinking" in str(exc_info.value)
    assert "{c}" not in str(exc_info.value)


def test_base_64_data_error_includes_value() -> None:
    """A non-str, non-stream image source reports its value, not '{data}'."""
    with pytest.raises(RuntimeError) as exc_info:
        base_64_data(Path("/tmp/image.png"))
    assert "/tmp/image.png" in str(exc_info.value)
    assert "{data}" not in str(exc_info.value)
