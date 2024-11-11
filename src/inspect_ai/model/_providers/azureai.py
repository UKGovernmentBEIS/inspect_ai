import json
import os
from copy import copy
from typing import Any

from azure.ai.inference.aio import ChatCompletionsClient
from azure.ai.inference.models import (
    AssistantMessage,
    ChatChoice,
    ChatCompletions,
    ChatCompletionsNamedToolChoice,
    ChatCompletionsNamedToolChoiceFunction,
    ChatCompletionsToolCall,
    ChatCompletionsToolChoicePreset,
    ChatCompletionsToolDefinition,
    ChatRequestMessage,
    ChatResponseMessage,
    CompletionsFinishReason,
    ContentItem,
    FunctionCall,
    FunctionDefinition,
    ImageContentItem,
    ImageUrl,
    SystemMessage,
    TextContentItem,
    ToolMessage,
    UserMessage,
)
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError, HttpResponseError
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai._util.content import Content, ContentText
from inspect_ai._util.images import image_as_data_uri
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolFunction

from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from .._generate_config import GenerateConfig
from .._image import image_url_filter
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .util import (
    environment_prerequisite_error,
    model_base_url,
)
from .util.chatapi import ChatAPIHandler
from .util.llama31 import Llama31Handler
from .util.util import parse_tool_call

AZUREAI_API_KEY = "AZUREAI_API_KEY"
AZUREAI_ENDPOINT_KEY = "AZUREAI_ENDPOINT_KEY"
AZUREAI_BASE_URL = "AZUREAI_BASE_URL"
AZUREAI_ENDPOINT_URL = "AZUREAI_ENDPOINT_URL"

# legacy vars for migration
AZURE_API_KEY = "AZURE_API_KEY"
AZURE_ENDPOINT_URL = "AZURE_ENDPOINT_URL"


class AzureAIAPI(ModelAPI):
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
            api_key_vars=[AZURE_API_KEY, AZUREAI_ENDPOINT_KEY],
            config=config,
        )

        # resolve api_key
        if not self.api_key:
            self.api_key = os.environ.get(
                AZURE_API_KEY, os.environ.get(AZUREAI_API_KEY, "")
            )
            if not self.api_key:
                raise environment_prerequisite_error("AzureAI", AZURE_API_KEY)

        # resolve base url
        endpoint_url = model_base_url(
            base_url,
            [
                AZURE_ENDPOINT_URL,
                AZUREAI_ENDPOINT_URL,
                AZUREAI_BASE_URL,
            ],
        )
        if not endpoint_url:
            raise environment_prerequisite_error("AzureAI", AZUREAI_BASE_URL)
        self.endpoint_url = endpoint_url

        # create client
        self.client = ChatCompletionsClient(
            endpoint=self.endpoint_url,
            credential=AzureKeyCredential(self.api_key),
            model=self.model_name,
            model_extras=model_args,
        )

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        # if its llama then do fake tool calls
        handler: ChatAPIHandler | None = Llama31Handler() if self.is_llama() else None
        if handler:
            input = handler.input_with_tools(input, tools)

        # prepare request
        request = dict(
            messages=await chat_request_messages(input, handler),
            tools=chat_tools(tools) if len(tools) > 0 else None,
            tool_choice=chat_tool_choice(tool_choice) if len(tools) > 0 else None,
            **self.completion_params(config),
        )

        # make call
        try:
            response: ChatCompletions = await self.client.complete(**request)
            return ModelOutput(
                model=response.model,
                choices=chat_completion_choices(response.choices, tools, handler),
                usage=ModelUsage(
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                ),
            ), ModelCall.create(
                request=request
                | dict(
                    messages=[message.as_dict() for message in request["messages"]],
                    tools=[tool.as_dict() for tool in request["tools"]]
                    if request.get("tools", None) is not None
                    else None,
                ),
                response=response.as_dict(),
                filter=image_url_filter,
            )
        except AzureError as ex:
            return self.handle_azure_error(ex)

    def completion_params(self, config: GenerateConfig) -> dict[str, Any]:
        params: dict[str, str | int | float | list[str]] = {}
        if config.frequency_penalty is not None:
            params["frequency_penalty"] = config.frequency_penalty
        if config.presence_penalty is not None:
            params["presence_penalty"] = config.presence_penalty
        if config.temperature is not None:
            params["temperature"] = config.temperature
        if config.top_p is not None:
            params["top_p"] = config.top_p
        if config.max_tokens is not None:
            params["max_tokens"] = config.max_tokens
        if config.stop_seqs is not None:
            params["stop"] = config.stop_seqs
        if config.seed is not None:
            params["seed"] = config.seed

        return params

    @override
    def max_tokens(self) -> int | None:
        if self.is_llama3():
            return 8192  # context window is 128k

        elif self.is_llama():
            return 2048  # llama2 context window is 4096

        # Mistral uses a default of 8192 which is fine, so we don't mess with it
        # see: https://learn.microsoft.com/en-us/azure/ai-studio/how-to/deploy-models-mistral#request-schema
        elif self.is_mistral():
            return None

        # Not sure what do to about other model types... (there aren't currently any others)
        else:
            return DEFAULT_MAX_TOKENS

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        if isinstance(ex, HttpResponseError):
            return (
                ex.status_code == 408
                or ex.status_code == 409
                or ex.status_code == 429
                or ex.status_code == 500
            )
        else:
            return False

    @override
    def collapse_user_messages(self) -> bool:
        return True

    @override
    def connection_key(self) -> str:
        return f"{self.api_key}{self.model_name}"

    def is_llama(self) -> bool:
        return "llama" in self.model_name.lower()

    def is_llama3(self) -> bool:
        return "llama-3" in self.model_name.lower()

    def is_mistral(self) -> bool:
        return "mistral" in self.model_name.lower()

    def handle_azure_error(self, ex: AzureError) -> ModelOutput:
        if isinstance(ex, HttpResponseError):
            response = str(ex.message)
            if "maximum context length" in response.lower():
                return ModelOutput.from_content(
                    model=self.model_name,
                    content=response,
                    stop_reason="model_length",
                )
            elif ex.status_code == 400 and ex.error:
                return ModelOutput.from_content(
                    model=self.model_name,
                    content=f"Your request triggered an error: {ex.error}",
                    stop_reason="content_filter",
                )

        raise ex


async def chat_request_messages(
    messages: list[ChatMessage], handler: ChatAPIHandler | None
) -> list[ChatRequestMessage]:
    return [await chat_request_message(message, handler) for message in messages]


async def chat_request_message(
    message: ChatMessage, handler: ChatAPIHandler | None
) -> ChatRequestMessage:
    if isinstance(message, ChatMessageSystem):
        return SystemMessage(content=message.text)
    elif isinstance(message, ChatMessageUser):
        return UserMessage(
            content=message.content
            if isinstance(message.content, str)
            else [await chat_content_item(item) for item in message.content]
        )
    elif isinstance(message, ChatMessageTool):
        return ToolMessage(
            content=(
                f"Error: {message.error.message}" if message.error else message.text
            ),
            tool_call_id=str(message.tool_call_id),
        )
    else:
        if message.tool_calls:
            if handler:
                return AssistantMessage(
                    content=handler.assistant_message(message)["content"]
                )
            else:
                return AssistantMessage(
                    content=message.text or None,
                    tool_calls=[chat_tool_call(call) for call in message.tool_calls],
                )
        else:
            return AssistantMessage(content=message.text)


async def chat_content_item(content: Content) -> ContentItem:
    if isinstance(content, ContentText):
        return TextContentItem(text=content.text)
    else:
        return ImageContentItem(
            image_url=ImageUrl(
                url=await image_as_data_uri(content.image), detail=content.detail
            )
        )


def chat_tool_call(tool_call: ToolCall) -> ChatCompletionsToolCall:
    return ChatCompletionsToolCall(
        id=tool_call.id,
        function=FunctionCall(
            name=tool_call.function, arguments=json.dumps(tool_call.arguments)
        ),
    )


def chat_tools(tools: list[ToolInfo]) -> list[ChatCompletionsToolDefinition]:
    return [chat_tool_definition(tool) for tool in tools]


def chat_tool_definition(tool: ToolInfo) -> ChatCompletionsToolDefinition:
    return ChatCompletionsToolDefinition(
        function=FunctionDefinition(
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters.model_dump(exclude_none=True),
        )
    )


def chat_tool_choice(
    tool_choice: ToolChoice,
) -> str | ChatCompletionsToolChoicePreset | ChatCompletionsNamedToolChoice:
    if isinstance(tool_choice, ToolFunction):
        return ChatCompletionsNamedToolChoice(
            function=ChatCompletionsNamedToolChoiceFunction(name=tool_choice.name)
        )
    elif tool_choice == "auto":
        return ChatCompletionsToolChoicePreset.AUTO
    elif tool_choice == "none":
        return ChatCompletionsToolChoicePreset.NONE
    elif tool_choice == "any":
        return ChatCompletionsToolChoicePreset.REQUIRED


def chat_completion_choices(
    choices: list[ChatChoice], tools: list[ToolInfo], handler: ChatAPIHandler | None
) -> list[ChatCompletionChoice]:
    choices = copy(choices)
    choices.sort(key=lambda c: c.index)
    return [chat_complection_choice(choice, tools, handler) for choice in choices]


def chat_complection_choice(
    choice: ChatChoice, tools: list[ToolInfo], handler: ChatAPIHandler | None
) -> ChatCompletionChoice:
    return ChatCompletionChoice(
        message=chat_completion_assistant_message(choice.message, tools, handler),
        stop_reason=chat_completion_stop_reason(choice.finish_reason),
    )


def chat_completion_assistant_message(
    response: ChatResponseMessage, tools: list[ToolInfo], handler: ChatAPIHandler | None
) -> ChatMessageAssistant:
    if handler:
        return handler.parse_assistant_response(response.content, tools)
    else:
        return ChatMessageAssistant(
            content=response.content,
            tool_calls=[
                chat_completion_tool_call(call, tools) for call in response.tool_calls
            ]
            if response.tool_calls is not None
            else None,
        )


def chat_completion_tool_call(
    tool_call: ChatCompletionsToolCall, tools: list[ToolInfo]
) -> ToolCall:
    return parse_tool_call(
        tool_call.id, tool_call.function.name, tool_call.function.arguments, tools
    )


def chat_completion_stop_reason(reason: str) -> StopReason:
    match reason:
        case CompletionsFinishReason.STOPPED:
            return "stop"

        case CompletionsFinishReason.TOKEN_LIMIT_REACHED:
            return "max_tokens"

        case CompletionsFinishReason.CONTENT_FILTERED:
            return "content_filter"

        case CompletionsFinishReason.TOOL_CALLS:
            return "tool_calls"

        case _:
            return "unknown"
