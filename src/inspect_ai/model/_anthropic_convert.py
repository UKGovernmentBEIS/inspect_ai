from typing import TYPE_CHECKING, Any, Union

from inspect_ai.model._chat_message import ChatMessage, ChatMessageSystem

if TYPE_CHECKING:
    from anthropic.types import Message, MessageParam

from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._providers.providers import validate_anthropic_client


async def messages_from_anthropic(
    messages: "list[MessageParam]", system_message: str | None = None
) -> list[ChatMessage]:
    """Convert OpenAI Responses API messages into Inspect messages.

    Args:
        messages: OpenAI Responses API Messages
        system_message: System message accompanying messages (optional).
    """
    validate_anthropic_client("messages_from_anthropic()")

    from inspect_ai.agent._bridge.anthropic_api_impl import (
        messages_from_anthropic_input,
    )

    chat_messages = await messages_from_anthropic_input(messages, tools=[])
    if system_message:
        chat_messages.insert(0, ChatMessageSystem(content=system_message))
    return chat_messages


async def model_output_from_anthropic(
    message: Union["Message", dict[str, Any]],
) -> ModelOutput:
    """Convert Anthropic Message response into Inspect `ModelOutput`

    Args:
        message: Anthropic `Message` object or dict that can converted into one.

    Raises:
        ValidationError: If the `dict` can't be converted into a `Message`.
    """
    validate_anthropic_client("model_output_from_anthropic()")

    from anthropic.types import Message

    from inspect_ai.model._providers.anthropic import model_output_from_message

    if isinstance(message, dict):
        message = Message.model_validate(message)

    model_output, _ = await model_output_from_message(
        client=None, model=None, message=message, tools=[]
    )
    return model_output
