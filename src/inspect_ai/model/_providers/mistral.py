import json
import os
from typing import Any

from mistralai.async_client import MistralAsyncClient
from mistralai.exceptions import MistralAPIStatusException
from mistralai.models.chat_completion import (
    ChatCompletionResponse,
    ChatCompletionResponseChoice,
    FinishReason,
    FunctionCall,
    ToolType,
)
from mistralai.models.chat_completion import (
    ChatMessage as MistralChatMessage,
)
from mistralai.models.chat_completion import (
    ToolCall as MistralToolCall,
)
from mistralai.models.chat_completion import (
    ToolChoice as MistralToolChoice,
)
from typing_extensions import override

from inspect_ai._util.constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT,
)

from .._chat_message import ChatMessage, ChatMessageAssistant
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .._tool import ToolCall, ToolChoice, ToolFunction, ToolInfo
from .._util import chat_api_tool
from .util import model_base_url, parse_tool_call

AZURE_MISTRAL_API_KEY = "AZURE_MISTRAL_API_KEY"
AZUREAI_MISTRAL_API_KEY = "AZUREAI_MISTRAL_API_KEY"
MISTRAL_API_KEY = "MISTRAL_API_KEY"


class MistralAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(model_name=model_name, base_url=base_url, config=config)

        # resolve api_key -- look for mistral then azure
        api_key = os.environ.get(MISTRAL_API_KEY, None)
        if api_key:
            base_url = model_base_url(base_url, "MISTRAL_BASE_URL")
            if base_url:
                model_args["endpoint"] = base_url
        else:
            api_key = os.environ.get(
                AZUREAI_MISTRAL_API_KEY, os.environ.get(AZURE_MISTRAL_API_KEY, None)
            )
            if not api_key:
                raise ValueError(
                    f"{MISTRAL_API_KEY} or {AZUREAI_MISTRAL_API_KEY} environment variable not found."
                )
            base_url = model_base_url(base_url, "AZUREAI_MISTRAL_BASE_URL")
            if not base_url:
                raise ValueError(
                    "You must provide a base URL when using Mistral on Azure. Use the AZUREAI_MISTRAL_BASE_URL "
                    + " environment variable or the --model-base-url CLI flag to set the base URL."
                )
            model_args["endpoint"] = base_url

        # save key
        self.api_key = api_key

        # create client
        self.client = MistralAsyncClient(
            api_key=api_key,
            max_retries=(
                config.max_retries if config.max_retries else DEFAULT_MAX_RETRIES
            ),
            timeout=config.timeout if config.timeout else DEFAULT_TIMEOUT,
            **model_args,
        )

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # send request
        response = await self.client.chat(
            model=self.model_name,
            messages=[mistral_chat_message(message) for message in input],
            temperature=config.temperature,
            top_p=config.top_p,
            max_tokens=config.max_tokens,
            random_seed=config.seed,
            tools=mistral_chat_tools(tools) if len(tools) > 0 else None,
            tool_choice=(
                mistral_chat_tool_choice(tool_choice) if len(tools) > 0 else None
            ),
        )

        # return model output (w/ tool calls if they exist)
        choices = completion_choices_from_response(response)
        return ModelOutput(
            model=response.model,
            choices=choices,
            usage=ModelUsage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=(
                    response.usage.completion_tokens
                    if response.usage.completion_tokens
                    else response.usage.total_tokens - response.usage.prompt_tokens
                ),
                total_tokens=response.usage.total_tokens,
            ),
        )

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        return isinstance(ex, MistralAPIStatusException) and ex.http_status == 429

    @override
    def connection_key(self) -> str:
        return self.api_key

    # not clear what the mistral default max tokens is (not documented)
    # so we set it to the default to be sure
    @override
    def max_tokens(self) -> int:
        return DEFAULT_MAX_TOKENS


def mistral_chat_tools(tools: list[ToolInfo]) -> list[dict[str, Any]]:
    chat_tools = [chat_api_tool(tool) for tool in tools]
    return [dict(type=tool["type"], function=tool["function"]) for tool in chat_tools]


def mistral_chat_tool_choice(tool_choice: ToolChoice) -> MistralToolChoice:
    if isinstance(tool_choice, ToolFunction):
        # mistral doesn't support specifically named tools to use
        # (rather just 'any' which says use at least one tool)
        return MistralToolChoice.any
    elif tool_choice == "any":
        return MistralToolChoice.any
    elif tool_choice == "auto":
        return MistralToolChoice.auto
    else:
        return MistralToolChoice.none


def mistral_chat_message(message: ChatMessage) -> MistralChatMessage:
    if message.role == "assistant" and message.tool_calls:
        return MistralChatMessage(
            role=message.role,
            content=message.text,
            tool_calls=[mistral_tool_call(call) for call in message.tool_calls],
        )
    elif message.role == "tool":
        return MistralChatMessage(
            role=message.role,
            name=message.tool_call_id,
            content=(
                f"Error: {message.tool_error}" if message.tool_error else message.text
            ),
        )
    else:
        return MistralChatMessage(role=message.role, content=message.text)


def mistral_tool_call(tool_call: ToolCall) -> MistralToolCall:
    return MistralToolCall(
        id=tool_call.id,
        type=ToolType.function,
        function=mistral_function_call(tool_call),
    )


def mistral_function_call(tool_call: ToolCall) -> FunctionCall:
    return FunctionCall(
        name=tool_call.function, arguments=json.dumps(tool_call.arguments)
    )


def chat_tool_calls(message: MistralChatMessage) -> list[ToolCall] | None:
    if message.tool_calls:
        return [
            parse_tool_call(call.id, call.function.name, call.function.arguments)
            for call in message.tool_calls
        ]
    else:
        return None


def completion_choice(choice: ChatCompletionResponseChoice) -> ChatCompletionChoice:
    message = choice.message
    completion = message.content
    if isinstance(completion, list):
        completion = " ".join(completion)
    return ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=completion, tool_calls=chat_tool_calls(message), source="generate"
        ),
        stop_reason=(
            choice_stop_reason(choice)
            if choice.finish_reason is not None
            else "unknown"
        ),
    )


def completion_choices_from_response(
    response: ChatCompletionResponse,
) -> list[ChatCompletionChoice]:
    return [completion_choice(choice) for choice in response.choices]


def choice_stop_reason(choice: ChatCompletionResponseChoice) -> StopReason:
    match choice.finish_reason:
        case FinishReason.stop:
            return "stop"
        case FinishReason.length:
            return "length"
        case FinishReason.tool_calls:
            return "tool_calls"
        case _:
            return "unknown"
