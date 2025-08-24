from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._chat_message import ChatMessage
from ._providers.providers import validate_openai_client

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam


async def messages_to_openai(
    messages: list[ChatMessage],
    system_role: Literal["user", "system", "developer"] = "system",
) -> "list[ChatCompletionMessageParam]":
    """Convert messages to OpenAI Completions API compatible messages.

    ::: callout-note
    The `message_to_openai()` function is available only in the development version of Inspect. To install the development version from GitHub:

    ``` bash
    pip install git+https://github.com/UKGovernmentBEIS/inspect_ai
    ```
    :::


    Args:
       messages: List of messages to convert
       system_role: Role to use for system messages (newer OpenAI models use "developer" rather than "system").
    """
    validate_openai_client("messages_to_openai()")

    from ._openai import messages_to_openai as messages_to_openai_impl

    return await messages_to_openai_impl(messages, system_role)


async def messages_from_openai(
    messages: "list[ChatCompletionMessageParam]",
    model: str | None = None,
) -> list[ChatMessage]:
    """Convert OpenAI Completions API messages into Inspect messages.

    ::: callout-note
    The `messages_from_openai()` function is available only in the development version of Inspect. To install the development version from GitHub:

    ``` bash
    pip install git+https://github.com/UKGovernmentBEIS/inspect_ai
    ```
    :::

    Args:
        messages: OpenAI Completions API Messages
        model: Optional model name to tag assistant messages with.
    """
    validate_openai_client("messages_from_openai()")

    from ._openai import messages_from_openai as messages_from_openai_impl

    return await messages_from_openai_impl(messages, model)
