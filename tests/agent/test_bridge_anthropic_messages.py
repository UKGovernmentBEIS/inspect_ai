import pytest

from inspect_ai.agent._bridge.anthropic_api_impl import messages_from_anthropic_input
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)


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
