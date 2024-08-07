import json
import os
from typing import Any

from mistralai import FunctionCall, Mistral
from mistralai.models.assistantmessage import (
    AssistantMessage as MistralAssistantMessage,
)
from mistralai.models.chatcompletionchoice import (
    ChatCompletionChoice as MistralChatCompletionChoice,
)
from mistralai.models.chatcompletionchoice import (
    FinishReason,
)
from mistralai.models.chatcompletionrequest import (
    ToolChoice as MistralToolChoice,
)
from mistralai.models.chatcompletionresponse import ChatCompletionResponse
from mistralai.models.sdkerror import SDKError
from mistralai.models.systemmessage import SystemMessage as MistralSystemMessage
from mistralai.models.toolcall import (
    ToolCall as MistralToolCall,
)
from mistralai.models.toolmessage import ToolMessage as MistralToolMessage
from mistralai.models.usermessage import UserMessage as MistralUserMessage
from typing_extensions import override

# TODO: Tool use in general in rough shape
# TODO: Migration guide:
# https://github.com/mistralai/client-python/blob/main/MIGRATION.md
from inspect_ai._util.constants import (
    # TODO: LEarn whats up with retries DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT,
)
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo

from .._chat_message import ChatMessage, ChatMessageAssistant
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .util import model_base_url, parse_tool_call

AZURE_MISTRAL_API_KEY = "AZURE_MISTRAL_API_KEY"
AZUREAI_MISTRAL_API_KEY = "AZUREAI_MISTRAL_API_KEY"
MISTRAL_API_KEY = "MISTRAL_API_KEY"


class MistralAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[
                MISTRAL_API_KEY,
                AZURE_MISTRAL_API_KEY,
                AZUREAI_MISTRAL_API_KEY,
            ],
            config=config,
        )

        # resolve api_key -- look for mistral then azure
        if not self.api_key:
            self.api_key = os.environ.get(MISTRAL_API_KEY, None)
            if self.api_key:
                base_url = model_base_url(base_url, "MISTRAL_BASE_URL")
                if base_url:
                    model_args["endpoint"] = base_url
            else:
                self.api_key = os.environ.get(
                    AZUREAI_MISTRAL_API_KEY, os.environ.get(AZURE_MISTRAL_API_KEY, None)
                )
                if not self.api_key:
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

        # create client
        self.client = Mistral(
            api_key=self.api_key,
            # max_retries=(
            #    config.max_retries if config.max_retries else DEFAULT_MAX_RETRIES
            # ),
            timeout_ms=config.timeout if config.timeout else DEFAULT_TIMEOUT,
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
        response = await self.client.chat.complete_async(
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

        if response is None:
            raise ValueError("No response from model")

        # return model output (w/ tool calls if they exist)
        choices = completion_choices_from_response(response, tools)
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
        return isinstance(ex, SDKError) and ex.status_code == 429

    @override
    def connection_key(self) -> str:
        return str(self.api_key)

    # not clear what the mistral default max tokens is (not documented)
    # so we set it to the default to be sure
    @override
    def max_tokens(self) -> int:
        return DEFAULT_MAX_TOKENS


def mistral_chat_tools(tools: list[ToolInfo]) -> list[dict[str, Any]]:
    return [
        dict(type="function", function=tool.model_dump(exclude_none=True))
        for tool in tools
    ]


def mistral_chat_tool_choice(tool_choice: ToolChoice) -> MistralToolChoice:
    if isinstance(tool_choice, ToolFunction):
        # mistral doesn't support specifically named tools to use
        # (rather just 'any' which says use at least one tool)
        return "any"
    elif tool_choice == "any":
        return "any"
    elif tool_choice == "auto":
        return "auto"
    else:
        return "none"


def mistral_chat_message(
    message: ChatMessage,
) -> (
    MistralSystemMessage
    | MistralUserMessage
    | MistralAssistantMessage
    | MistralToolMessage
):
    if message.role == "assistant" and message.tool_calls:
        return MistralAssistantMessage(
            role=message.role,
            content=message.text,
            tool_calls=[mistral_tool_call(call) for call in message.tool_calls],
        )
    elif message.role == "tool":
        return MistralToolMessage(
            role=message.role,
            name=message.tool_call_id,
            content=(
                f"Error: {message.error.message}" if message.error else message.text
            ),
        )
    elif message.role == "user":
        return MistralUserMessage(content=message.text)
    else:
        return MistralAssistantMessage(content=message.text)


def mistral_tool_call(tool_call: ToolCall) -> MistralToolCall:
    return MistralToolCall(
        id=tool_call.id,
        function=mistral_function_call(tool_call),
    )


def mistral_function_call(tool_call: ToolCall) -> FunctionCall:
    return FunctionCall(
        name=tool_call.function, arguments=json.dumps(tool_call.arguments)
    )


def chat_tool_calls(
    message: MistralToolMessage, tools: list[ToolInfo]
) -> list[ToolCall] | None:
    if message.tool_calls:
        return [
            parse_tool_call(call.id, call.function.name, call.function.arguments, tools)
            for call in message.tool_calls
        ]
    else:
        return None


def completion_choice(
    choice: MistralChatCompletionChoice, tools: list[ToolInfo]
) -> ChatCompletionChoice:
    message = choice.message

    completion = message.content
    if isinstance(completion, list):
        completion = " ".join(completion)
    return ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=completion,
            tool_calls=chat_tool_calls(message, tools),
            source="generate",
        ),
        stop_reason=(
            choice_stop_reason(choice)
            if choice.finish_reason is not None
            else "unknown"
        ),
    )


def completion_choices_from_response(
    response: ChatCompletionResponse, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    if response.choices is None:
        return []
    else:
        return [completion_choice(choice, tools) for choice in response.choices]


def choice_stop_reason(choice: ChatCompletionChoice) -> StopReason:
    match choice.finish_reason:
        case FinishReason.stop:
            return "stop"
        case FinishReason.length:
            return "length"
        case FinishReason.tool_calls:
            return "tool_calls"
        case _:
            return "unknown"
