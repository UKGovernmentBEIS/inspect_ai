from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Union

from inspect_ai.model._model_output import ModelOutput

from ._chat_message import ChatMessage
from ._providers.providers import validate_openai_client

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
    from openai.types.responses import Response, ResponseInputItemParam


async def messages_to_openai(
    messages: list[ChatMessage],
    system_role: Literal["user", "system", "developer"] = "system",
) -> "list[ChatCompletionMessageParam]":
    """Convert messages to OpenAI Completions API compatible messages.

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

    Args:
        messages: OpenAI Completions API Messages
        model: Optional model name to tag assistant messages with.
    """
    validate_openai_client("messages_from_openai()")

    from ._openai import messages_from_openai as messages_from_openai_impl

    return await messages_from_openai_impl(messages, model)


async def messages_from_openai_responses(
    messages: "list[ResponseInputItemParam]",
    model: str | None = None,
) -> list[ChatMessage]:
    """Convert OpenAI Responses API messages into Inspect messages.

    Args:
        messages: OpenAI Responses API Messages
        model: Optional model name to tag assistant messages with.
    """
    validate_openai_client("messages_from_openai_responses()")

    from inspect_ai.agent._bridge.responses_impl import messages_from_responses_input

    return messages_from_responses_input(messages, tools=[], model_name=model)


async def messages_to_openai_responses(
    messages: list[ChatMessage],
) -> "list[ResponseInputItemParam]":
    """Convert messages to OpenAI Responses API input item params.

    Args:
       messages: List of messages to convert
    """
    validate_openai_client("messages_to_openai_responses()")

    from ._openai_responses import openai_responses_inputs

    return await openai_responses_inputs(messages)


async def model_output_from_openai(
    completion: Union["ChatCompletion", dict[str, Any]],
) -> ModelOutput:
    """Convert OpenAI ChatCompletion into Inspect `ModelOutput`

    Args:
        completion: OpenAI `ChatCompletion` object or dict that can converted into one.

    Raises:
        ValidationError: If the `dict` can't be converted into a `ChatCompletion`.
    """
    validate_openai_client("model_output_from_openai()")

    from openai.types.chat import ChatCompletion

    from inspect_ai.model._openai import (
        chat_choices_from_openai,
        model_output_from_openai,
    )

    if isinstance(completion, dict):
        completion = ChatCompletion.model_validate(completion)

    choices = chat_choices_from_openai(completion, tools=[])
    return model_output_from_openai(completion, choices)


async def model_output_from_openai_responses(
    response: Union["Response", dict[str, Any]],
) -> ModelOutput:
    """Convert OpenAI `Response` into Inspect `ModelOutput`

    Args:
        response: OpenAI `Response` object or dict that can converted into one.

    Raises:
        ValidationError: If the `dict` can't be converted into a `Response`.
    """
    validate_openai_client("model_output_from_openai_responses()")

    from openai.types.responses import Response

    from inspect_ai.model._openai_responses import openai_responses_chat_choices
    from inspect_ai.model._providers.openai_responses import model_usage_from_response

    if isinstance(response, dict):
        response = Response.model_validate(response)

    choices = openai_responses_chat_choices(model=None, response=response, tools=[])
    return ModelOutput(
        model=response.model,
        choices=choices,
        usage=model_usage_from_response(response),
    )
