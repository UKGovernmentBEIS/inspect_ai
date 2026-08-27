import functools
import json
import os
from copy import copy
from logging import getLogger
from typing import Any, AsyncIterator, Literal, cast

from azure.ai.inference.aio import ChatCompletionsClient
from azure.ai.inference.models import (
    AssistantMessage,
    AsyncStreamingChatCompletions,
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
    StreamingChatCompletionsUpdate,
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
from inspect_ai._util.http import (
    is_retryable_http_status,
    parse_retry_after_from_exception,
)
from inspect_ai._util.images import inline_media_data_uri
from inspect_ai.log._samples import set_active_model_event_call
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolFunction
from inspect_ai.util._json import JSON_SCHEMA_EXTENDED_FIELDS, json_schema_dump

from .._call_tools import parse_tool_call
from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from .._generate_config import GenerateConfig
from .._model import ModelAPI, RetryDecision
from .._model_call import ModelCall
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
    collect_stop_details,
)
from .._openai import (
    needs_max_completion_tokens,
    openai_media_filter,
    openai_stop_details,
)
from .._stream import (
    StreamTextEvent,
    StreamToolCallEvent,
    model_stream_requested,
    report_model_stream_delta,
    report_model_stream_progress,
    report_model_stream_start,
)
from .util import (
    environment_prerequisite_error,
    model_base_url,
    normalize_stream_arg,
)
from .util.chatapi import ChatAPIHandler
from .util.llama31 import Llama31Handler

logger = getLogger(__name__)

AZUREAI_API_KEY = "AZUREAI_API_KEY"
AZUREAI_BASE_URL = "AZUREAI_BASE_URL"
AZUREAI_ENDPOINT_URL = "AZUREAI_ENDPOINT_URL"
AZUREAI_AUDIENCE = "AZUREAI_AUDIENCE"

# legacy vars for migration
AZURE_API_KEY = "AZURE_API_KEY"
AZURE_ENDPOINT_URL = "AZURE_ENDPOINT_URL"


def _is_llama_model(name: str) -> bool:
    return "llama" in name.lower()


def _is_llama3_model(name: str) -> bool:
    return "llama-3" in name.lower()


def _is_mistral_model(name: str) -> bool:
    return "mistral" in name.lower()


def _is_openai_model(name: str) -> bool:
    """Check for OpenAI model naming conventions."""
    name = name.lower()
    return (
        name.startswith("gpt-")
        or name.startswith("o1")
        or name.startswith("o3")
        or name.startswith("o4")
    )


class AzureAIAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        streaming: bool | Literal["auto"] = "auto",
        **model_args: Any,
    ):
        # record streaming preference (unset/"auto" streams when the caller
        # passes on_stream to generate; an explicit True/False overrides)
        self.streaming: bool | None = normalize_stream_arg(streaming, "streaming")

        # Check for explicit org prefix: azureai/moonshotai/kimi-k2.5 -> org=moonshotai
        # We keep the full model_name (including prefix) so it appears in logs
        # but use service_model_name() for actual API calls
        self.org_prefix: str | None = None
        if "/" in model_name:
            self.org_prefix = model_name.split("/", 1)[0]

        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[AZURE_API_KEY, AZUREAI_API_KEY],
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
        if not self.api_key:
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

        # prepare request (resolve streaming while building it, so the
        # ModelCall snapshot below matches the wire request)
        streaming = self.resolve_streaming(config)
        request = dict(
            messages=await chat_request_messages(input, handler, self.is_mistral()),
            **self.completion_params(config),
        )
        if streaming:
            request["stream"] = True
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
            model=self.service_model_name(),
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
            if streaming:
                updates = cast(
                    AsyncStreamingChatCompletions, await client.complete(**request)
                )
                try:
                    response = await azureai_completion_from_stream(updates)
                finally:
                    await updates.aclose()
            else:
                response = cast(ChatCompletions, await client.complete(**request))

            model_call.set_response(response.as_dict())

            return ModelOutput(
                model=response.model,
                choices=chat_completion_choices(
                    response.model, response.choices, tools, handler
                ),
                # a streamed response may end without a usage chunk
                usage=ModelUsage(
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                )
                if response.usage is not None
                else None,
            ), model_call

        except AzureError as ex:
            model_call.set_error({"error": {"message": str(ex.message)}})
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
            if needs_max_completion_tokens(self.model_family()):
                params["max_completion_tokens"] = config.max_tokens
            else:
                params["max_tokens"] = config.max_tokens
        if config.stop_seqs is not None:
            params["stop"] = config.stop_seqs
        if config.seed is not None:
            params["seed"] = config.seed

        return params

    def resolve_streaming(self, config: GenerateConfig) -> bool:
        """Whether to use the streaming API for this generate call.

        An explicit `streaming` model arg wins; when unset ("auto"), stream
        when the caller passed `on_stream` to `Model.generate()`. Unlike the
        openai provider's Azure chat-completions path (which never
        auto-streams because the SDK accumulator only keeps the first chunk's
        `content_filter_results`), the hand-rolled accumulation here
        preserves the last filter annotation seen per choice — the update
        that carries `finish_reason="content_filter"` also carries the
        results for the filtered content — so stop details survive
        streaming.
        """
        if self.streaming is not None:
            return self.streaming
        return model_stream_requested()

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
    def should_retry(self, ex: Exception) -> bool | RetryDecision:
        if isinstance(ex, HttpResponseError) and ex.status_code is not None:
            if not is_retryable_http_status(ex.status_code):
                return RetryDecision.no()
            retry_after = parse_retry_after_from_exception(ex)
            if ex.status_code == 429:
                return RetryDecision.rate_limit(retry_after=retry_after)
            return RetryDecision.transient(retry_after=retry_after)
        if isinstance(ex, ServiceResponseError):
            return RetryDecision.transient()
        return RetryDecision.no()

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
        return f"{self.initial_api_key}:{self.model_name}"

    def service_model_name(self) -> str:
        """Model name without any org prefix, for API calls."""
        if self.org_prefix:
            return self.model_name.replace(f"{self.org_prefix}/", "", 1)
        return self.model_name

    def is_llama(self) -> bool:
        return _is_llama_model(self.model_family())

    def is_llama3(self) -> bool:
        return _is_llama3_model(self.model_family())

    def is_mistral(self) -> bool:
        return _is_mistral_model(self.model_family())

    def is_openai_model(self) -> bool:
        """Check if this is an OpenAI model (gpt-*, o1, o3, o4, etc.)."""
        return _is_openai_model(self.model_family())

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        Maps AzureAI model names to their organization's canonical format.
        Users can explicitly specify org: azureai/moonshotai/kimi-k2.5 → moonshotai/kimi-k2.5
        Otherwise auto-detects for known models: azureai/gpt-4o → openai/gpt-4o
        """
        base_name = self.service_model_name()
        # Explicit org prefix takes precedence
        if self.org_prefix:
            return f"{self.org_prefix}/{base_name}"
        # Auto-detect organization from model name
        if _is_openai_model(base_name):
            return f"openai/{base_name}"
        elif _is_mistral_model(base_name):
            return f"mistral/{base_name}"
        # For other models, return as-is and rely on fuzzy matching
        return base_name

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


class _StreamChoice:
    """Accumulated state for one streamed choice."""

    def __init__(self) -> None:
        self.content: list[str] = []
        # each entry: {"id", "type", "function": {"name", "arguments": [fragments]}}
        self.tool_calls: list[dict[str, Any]] = []
        self.finish_reason: str | None = None
        self.content_filter_results: dict[str, Any] | None = None


async def azureai_completion_from_stream(
    updates: AsyncIterator[StreamingChatCompletionsUpdate],
) -> ChatCompletions:
    """Consume an Azure AI chat-completions update stream into a completion.

    Reports each update once to the model layer's stream observer
    (`inspect_ai.model._stream`), which fans out to the caller's `on_stream`
    callback and the pending event's progress record. Accumulates all
    choices, but reports content deltas from the first choice only —
    interleaving multiple choices' fragments into the single delta stream
    would corrupt accumulating consumers.

    Updates are read through their raw mapping form (`azure.ai.inference`
    models are dict-backed) so undeclared fields — notably the per-choice
    `content_filter_results` Azure attaches — carry into the synthesized
    response for stop-details extraction. Tool-call fragments carry no index;
    a fragment bearing an `id` starts a new call and bare argument fragments
    extend the latest one.
    """
    report_model_stream_start()
    completion_id: str | None = None
    created: int | None = None
    model: str | None = None
    usage: dict[str, Any] | None = None
    choices: dict[int, _StreamChoice] = {}

    async for update in updates:
        completion_id = completion_id or update.get("id")
        created = created if created is not None else update.get("created")
        model = model or update.get("model")
        update_usage = update.get("usage")
        if update_usage is not None:
            usage = update_usage
            report_model_stream_progress(update_usage.get("completion_tokens"))

        reported = False
        for update_choice in update.get("choices") or []:
            index = update_choice.get("index", 0)
            choice = choices.setdefault(index, _StreamChoice())
            if update_choice.get("finish_reason") is not None:
                choice.finish_reason = update_choice["finish_reason"]
            filter_results = update_choice.get("content_filter_results")
            if filter_results:
                choice.content_filter_results = filter_results
            delta = update_choice.get("delta") or {}
            report = index == 0
            content = delta.get("content")
            if content:
                choice.content.append(content)
                if report:
                    await report_model_stream_delta(StreamTextEvent(text=content))
                    reported = True
            for tool_call in delta.get("tool_calls") or []:
                function = tool_call.get("function") or {}
                arguments = function.get("arguments") or ""
                if tool_call.get("id") or not choice.tool_calls:
                    choice.tool_calls.append(
                        {
                            "id": tool_call.get("id"),
                            "type": "function",
                            "function": {
                                "name": function.get("name"),
                                "arguments": [arguments] if arguments else [],
                            },
                        }
                    )
                else:
                    current = choice.tool_calls[-1]["function"]
                    current["name"] = current["name"] or function.get("name")
                    if arguments:
                        current["arguments"].append(arguments)
                if report:
                    current = choice.tool_calls[-1]
                    await report_model_stream_delta(
                        StreamToolCallEvent(
                            id=current["id"],
                            function=current["function"]["name"],
                            arguments=arguments,
                        )
                    )
                    reported = True
        if not reported and update_usage is None:
            report_model_stream_progress()

    if completion_id is None and model is None:
        raise RuntimeError("Streaming response ended without delivering any chunks.")

    response: dict[str, Any] = {
        "id": completion_id or "",
        "created": created or 0,
        "model": model or "",
        "object": "chat.completion",
        "choices": [
            {
                "index": index,
                "finish_reason": choice.finish_reason,
                "message": {
                    "role": "assistant",
                    "content": "".join(choice.content),
                }
                | (
                    {
                        "tool_calls": [
                            {
                                "id": tool_call["id"] or f"tool_call_{index}_{i}",
                                "type": "function",
                                "function": {
                                    "name": tool_call["function"]["name"] or "",
                                    "arguments": "".join(
                                        tool_call["function"]["arguments"]
                                    ),
                                },
                            }
                            for i, tool_call in enumerate(choice.tool_calls)
                        ]
                    }
                    if choice.tool_calls
                    else {}
                ),
            }
            | (
                {"content_filter_results": choice.content_filter_results}
                if choice.content_filter_results
                else {}
            )
            for index, choice in sorted(choices.items())
        ],
    }
    if usage is not None:
        response["usage"] = usage
    return ChatCompletions(response)


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
                url=inline_media_data_uri(content.image, "image"),
                detail=content.detail,
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
            parameters=json_schema_dump(
                tool.parameters, exclude=JSON_SCHEMA_EXTENDED_FIELDS
            ),
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
        # best-effort: azure.ai.inference may surface content_filter_results
        stop_details=collect_stop_details(
            "azureai", logger, lambda: openai_stop_details(choice)
        ),
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
