import functools
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
from azure.core.exceptions import (
    AzureError,
    HttpResponseError,
    ServiceResponseError,
)
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.http import is_retryable_http_status
from inspect_ai._util.images import file_as_data_uri
from inspect_ai.log._samples import set_active_model_event_call
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolFunction

from .._call_tools import parse_tool_call
from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .._openai import needs_max_completion_tokens, openai_media_filter
from .util import (
    environment_prerequisite_error,
    model_base_url,
)
from .util.chatapi import ChatAPIHandler
from .util.llama31 import Llama31Handler

AZUREAI_API_KEY = "AZUREAI_API_KEY"
AZUREAI_ENDPOINT_KEY = "AZUREAI_ENDPOINT_KEY"
AZUREAI_BASE_URL = "AZUREAI_BASE_URL"
AZUREAI_ENDPOINT_URL = "AZUREAI_ENDPOINT_URL"
AZUREAI_AUDIENCE = "AZUREAI_AUDIENCE"

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

        # collect known model_args (then delete them so we can pass the rest on)
        def collect_model_arg(name: str) -> Any | None:
            nonlocal model_args
            value = model_args.get(name, None)
            if value is not None:
                model_args.pop(name)
            return value

        emulate_tools = collect_model_arg("emulate_tools")
        self.emulate_tools = (
            not not emulate_tools if emulate_tools is not None else None
        )

        # resolve api_key or managed identity (for Azure)
        self.token_provider = None
        self.api_key = os.environ.get(
            AZURE_API_KEY, os.environ.get(AZUREAI_API_KEY, None)
        )
        if not self.api_key:
            # try managed identity (Microsoft Entra ID)
            try:
                from azure.identity import (
                    DefaultAzureCredential,
                    get_bearer_token_provider,
                )

                self.token_provider = get_bearer_token_provider(
                    DefaultAzureCredential(),
                    os.environ.get(
                        AZUREAI_AUDIENCE,
                        "https://cognitiveservices.azure.com/.default",
                    ),
                )
            except ImportError:
                raise PrerequisiteError(
                    "ERROR: The AzureAI provider requires the `azure-identity` package for managed identity support."
                )
        if not self.api_key and not self.token_provider:
            raise environment_prerequisite_error(
                "AzureAI",
                [
                    AZURE_API_KEY,
                    AZUREAI_API_KEY,
                    "or managed identity (Entra ID)",
                ],
            )
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
        self.model_args = model_args

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # emulate tools (auto for llama, opt-in for others)
        if self.emulate_tools is None and self.is_llama():
            self.emulate_tools = True
            handler: ChatAPIHandler | None = Llama31Handler(self.model_name)
        elif self.emulate_tools:
            handler = Llama31Handler(self.model_name)
        else:
            handler = None

        # resolve input
        if handler:
            input = handler.input_with_tools(input, tools)

        # prepare request
        request = dict(
            messages=await chat_request_messages(input, handler, self.is_mistral()),
            **self.completion_params(config),
        )
        # newer versions of vllm reject requests with tools or tool_choice if the
        # server hasn't been started explicitly with the --tool-call-parser and
        # --enable-auto-tool-choice flags
        if (not self.emulate_tools) and len(tools) > 0:
            request["tools"] = chat_tools(tools)
            request["tool_choice"] = chat_tool_choice(tool_choice)

        # create client (note the client needs to be created and closed
        # with each call so it can be cleaned up and not end up on another
        # event loop in a subsequent pass of eval)
        if self.api_key is not None:
            credential = AzureKeyCredential(self.api_key)
        elif self.token_provider is not None:
            credential = AzureKeyCredential(self.token_provider())
        else:
            raise PrerequisiteError(
                "Azure AI must have either an API key or token provider."
            )
        client = ChatCompletionsClient(
            endpoint=self.endpoint_url,
            credential=credential,
            model=self.model_name,
            model_extras=self.model_args,
        )

        model_call = set_active_model_event_call(
            request=request
            | dict(
                messages=[message.as_dict() for message in request["messages"]],
                tools=[tool.as_dict() for tool in request["tools"]]
                if request.get("tools", None) is not None
                else None,
            ),
            filter=openai_media_filter,
        )

        # make call
        try:
            response: ChatCompletions = await client.complete(**request)

            model_call.set_response(response.as_dict())

            return ModelOutput(
                model=response.model,
                choices=chat_completion_choices(
                    response.model, response.choices, tools, handler
                ),
                usage=ModelUsage(
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                ),
            ), model_call

        except AzureError as ex:
            model_call.set_response({"error": {"message": str(ex.message)}})
            return self.handle_azure_error(ex), model_call
        finally:
            await client.close()

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
            if needs_max_completion_tokens(self.model_name.lower()):
                params["max_completion_tokens"] = config.max_tokens
            else:
                params["max_tokens"] = config.max_tokens
        if config.stop_seqs is not None:
            params["stop"] = config.stop_seqs
        if config.seed is not None:
            params["seed"] = config.seed

        return params

    @override
    def max_tokens(self) -> int | None:
        if self.is_llama():
            return 2048  # llama2 and llama3 on azureai have context windows of 4096

        # Mistral uses a default of 8192 which is fine, so we don't mess with it
        # see: https://learn.microsoft.com/en-us/azure/ai-studio/how-to/deploy-models-mistral#request-schema
        elif self.is_mistral():
            return None

        # Not sure what do to about other model types... (there aren't currently any others)
        else:
            return DEFAULT_MAX_TOKENS

    @override
    def should_retry(self, ex: Exception) -> bool:
        if isinstance(ex, HttpResponseError) and ex.status_code is not None:
            return is_retryable_http_status(ex.status_code)
        elif isinstance(ex, ServiceResponseError):
            return True
        else:
            return False

    @override
    def is_auth_failure(self, ex: Exception) -> bool:
        if isinstance(ex, HttpResponseError):
            return ex.status_code == 401
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

    def is_openai_model(self) -> bool:
        """Check if this is an OpenAI model (gpt-*, o1, o3, o4, etc.)."""
        name = self.model_name.lower()
        return (
            name.startswith("gpt-")
            or name.startswith("o1")
            or name.startswith("o3")
            or name.startswith("o4")
        )

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        Maps AzureAI model names to their organization's canonical format.
        For example, "gpt-4o" → "openai/gpt-4o".
        """
        if self.is_openai_model():
            return f"openai/{self.model_name}"
        elif self.is_mistral():
            return f"mistral/{self.model_name}"
        # For other models (e.g., Llama), return as-is and rely on fuzzy matching
        return self.model_name

    def handle_azure_error(self, ex: AzureError) -> ModelOutput | Exception:
        if isinstance(ex, HttpResponseError):
            response = str(ex.message)
            if "maximum context length" in response.lower():
                return ModelOutput.from_content(
                    model=self.model_name,
                    content=response,
                    stop_reason="model_length",
                )
            elif ex.status_code == 400:
                return ex

        raise ex


async def chat_request_messages(
    messages: list[ChatMessage],
    handler: ChatAPIHandler | None,
    is_mistral: bool = False,
) -> list[ChatRequestMessage]:
    chat_messages = [
        await chat_request_message(message, handler) for message in messages
    ]
    if is_mistral:
        chat_messages = functools.reduce(mistral_message_reducer, chat_messages, [])

    return chat_messages


def mistral_message_reducer(
    messages: list[ChatRequestMessage],
    message: ChatRequestMessage,
) -> list[ChatRequestMessage]:
    """Fold any user messages found immediately after tool messages into the last tool message."""
    if (
        len(messages) > 0
        and isinstance(messages[-1], ToolMessage)
        and isinstance(message, UserMessage)
    ):
        messages[-1] = fold_user_message_into_tool_message(messages[-1], message)
    else:
        messages.append(message)

    return messages


def fold_user_message_into_tool_message(
    tool_message: ToolMessage,
    user_message: UserMessage,
) -> ToolMessage:
    def convert_content_items_to_string(list_content: list[ContentItem]) -> str:
        if not all(
            isinstance(item, (TextContentItem | ImageContentItem))
            for item in list_content
        ):
            raise TypeError(
                "Expected all items to be TextContentItem or ImageContentItem"
            )

        parts = []
        for item in list_content:
            if isinstance(item, TextContentItem):
                parts.append(item.text)
            elif isinstance(item, ImageContentItem):
                parts.append(f"[Image: {item.image_url.url}]")
            else:
                raise ValueError("Unexpected content item type")
        return "".join(parts)

    def normalise_content(
        content: str | list[ContentItem] | None,
    ) -> str | None:
        return (
            None
            if content is None
            else convert_content_items_to_string(content)
            if isinstance(content, list)
            else content
        )

    tool_content = normalise_content(tool_message.content)
    user_content = normalise_content(user_message.content)

    return ToolMessage(
        content=(tool_content or "") + (user_content or ""),
        tool_call_id=tool_message.tool_call_id,
    )


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
    elif isinstance(content, ContentImage):
        return ImageContentItem(
            image_url=ImageUrl(
                url=await file_as_data_uri(content.image), detail=content.detail
            )
        )
    else:
        raise RuntimeError("Azure AI models do not support audio or video inputs.")


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
    model: str,
    choices: list[ChatChoice],
    tools: list[ToolInfo],
    handler: ChatAPIHandler | None,
) -> list[ChatCompletionChoice]:
    choices = copy(choices)
    choices.sort(key=lambda c: c.index)
    return [
        chat_complection_choice(model, choice, tools, handler) for choice in choices
    ]


def chat_complection_choice(
    model: str,
    choice: ChatChoice,
    tools: list[ToolInfo],
    handler: ChatAPIHandler | None,
) -> ChatCompletionChoice:
    return ChatCompletionChoice(
        message=chat_completion_assistant_message(
            model, choice.message, tools, handler
        ),
        stop_reason=chat_completion_stop_reason(choice.finish_reason),
    )


def chat_completion_assistant_message(
    model: str,
    response: ChatResponseMessage,
    tools: list[ToolInfo],
    handler: ChatAPIHandler | None,
) -> ChatMessageAssistant:
    if handler:
        return handler.parse_assistant_response(response.content, tools)
    else:
        return ChatMessageAssistant(
            content=response.content or "",
            tool_calls=[
                chat_completion_tool_call(call, tools) for call in response.tool_calls
            ]
            if response.tool_calls is not None
            else None,
            model=model,
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
