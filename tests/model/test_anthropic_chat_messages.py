from typing import Any, cast

from inspect_ai._util.content import ContentText
from inspect_ai.agent._bridge.anthropic_api_impl import messages_from_anthropic_input
from inspect_ai.model import ChatMessageSystem, ChatMessageUser


async def test_anthropic_input_accepts_inline_system_messages() -> None:
    messages = await messages_from_anthropic_input(
        cast(
            Any,
            [
                {"role": "user", "content": "hello"},
                {
                    "role": "system",
                    "content": [
                        {"type": "text", "text": "answer in French"},
                    ],
                },
            ],
        ),
        tools=[],
    )

    assert isinstance(messages[0], ChatMessageUser)
    assert messages[0].content == "hello"
    assert isinstance(messages[1], ChatMessageSystem)
    assert isinstance(messages[1].content, list)
    assert messages[1].content == [ContentText(text="answer in French")]
