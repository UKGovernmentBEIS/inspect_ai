import os
from contextvars import ContextVar
from copy import copy
from logging import getLogger
from typing import Any, Awaitable, Callable, Optional, Sequence, cast

import grpc
import grpc.aio
from google.protobuf.json_format import MessageToDict
from openai import APIStatusError
from openai.types.chat import ChatCompletion
from pydantic import JsonValue
from typing_extensions import override
from xai_sdk import AsyncClient  # type: ignore
from xai_sdk.chat import (  # type: ignore
    Response,
    ToolMode,
    assistant,
    chat_pb2,
    system,
    tool,
    tool_result,
    usage_pb2,
    user,
)
from xai_sdk.client import (  # type: ignore
    UnaryStreamAioInterceptor,
    UnaryUnaryAioInterceptor,
    create_channel_credentials,
)
from xai_sdk.tools import web_search  # type: ignore

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.constants import BASE_64_DATA_REMOVED, HTTP
from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.images import file_as_data_uri
from inspect_ai._util.url import is_http_url
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model import ModelAPI
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._providers.util.hooks import HttpHooks
from inspect_ai.model._providers.util.util import model_base_url
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._json import json_schema_to_base_model

from .._generate_config import GenerateConfig
from .._model_output import (
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    ModelUsage,
    StopReason,
    TopLogprob,
)
from .openai_compatible import OpenAICompatibleAPI

logger = getLogger(__name__)

XAI_API_KEY = "XAI_API_KEY"
XAI_BASE_URL = "XAI_BASE_URL"
GROK_API_KEY = "GROK_API_KEY"
GROK_BASE_URL = "GROK_BASE_URL"


class GrokAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[XAI_API_KEY, GROK_API_KEY],
            config=config,
        )

        # resolve api key
        if self.api_key is None:
            self.api_key = os.environ.get(
                XAI_API_KEY, os.environ.get(GROK_API_KEY, None)
            )
        if self.api_key is None:
            raise PrerequisiteError(
                f"No {XAI_API_KEY} defined in environment and no api_key expliictly provided to grok provider"
            )

        # resolve base url
        self.base_url = (
            model_base_url(self.base_url, [XAI_BASE_URL, GROK_BASE_URL]) or "api.x.ai"
        )

        # save model args
        self.model_args = model_args

        # create client
        self.initialize()

    def _create_client(self) -> AsyncClient:
        return AsyncClient(
            api_key=self.api_key,
            api_host=self.base_url,
            timeout=3600,  # api docs show tweaking this up for reasoning models
            **self.model_args,
        )

    def initialize(self) -> None:
        super().initialize()
        self._http_hooks = GrpcHooks()
        self.client = GrokAsyncClient(
            api_key=self.api_key,
            api_host=self.base_url,
            timeout=3600,  # api docs show tweaking this up for reasoning models
            grpc_hooks=self._http_hooks,
            **self.model_args,
        )

    @override
    async def aclose(self) -> None:
        await self.client.close()

    def is_grok_2(self) -> bool:
        return "grok-2" in self.model_name

    def is_grok_3(self) -> bool:
        return "grok-3" in self.model_name

    def is_grok_3_mini(self) -> bool:
        return "grok-3-mini" in self.model_name

    def is_grok_4(self) -> bool:
        return "grok-4" in self.model_name

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # start request
        request_id = self._http_hooks.start_request()
        self._http_hooks.set_request_id(request_id)

        # setup request and response for ModelCall
        request: dict[str, Any] = {}
        response: dict[str, Any] = {}

        def model_call() -> ModelCall:
            return ModelCall.create(
                request=request,
                response=response,
                filter=_grok_media_filter,
                time=self._http_hooks.end_request(request_id),
            )

        try:
            # prepare input for chat call
            grok_messages = await _grok_messages(input)
            grok_tools = [self._grok_tool(tool) for tool in tools]
            grok_tool_choice = (
                self._grok_tool_choice(tool_choice) if len(tools) > 0 else None
            )
            grok_params = self._grok_params(config)

            # update request (convert proto to dict)
            request = dict(
                model=self.model_name,
                messages=[MessageToDict(m) for m in grok_messages],
                tools=[MessageToDict(t) for t in grok_tools],
                tool_choice=MessageToDict(grok_tool_choice)
                if isinstance(grok_tool_choice, chat_pb2.ToolChoice)
                else grok_tool_choice,
                **grok_params,
            )

            # chat call
            chat = self.client.chat.create(
                model=self.model_name,
                messages=grok_messages,
                tools=grok_tools,
                tool_choice=grok_tool_choice,
                **grok_params,
            )

            # handle structured output
            if config.response_schema is not None:
                chat_response, _ = await chat.parse(
                    json_schema_to_base_model(config.response_schema.json_schema)
                )
            # stream the reponse for improved connectivity for long requests
            else:
                async for chat_response, _ in chat.stream():
                    pass

            # update response
            response = MessageToDict(chat_response._proto)

            # return
            return self._model_output_from_response(chat_response, tools), model_call()
        except grpc.RpcError as ex:
            if ex.code() == grpc.StatusCode.PERMISSION_DENIED:
                handled = self._handle_grpc_permission_denied(ex)
                if handled:
                    return handled, model_call()
                else:
                    raise ex
            elif ex.code() == grpc.StatusCode.INVALID_ARGUMENT:
                return self._handle_grpc_bad_request(ex), model_call()
            else:
                raise ex

    def is_auth_failure(self, ex: Exception) -> bool:
        return (
            isinstance(ex, grpc.RpcError)
            and ex.code() == grpc.StatusCode.UNAUTHENTICATED
        )

    def should_retry(self, ex: BaseException) -> bool:
        if isinstance(ex, grpc.RpcError):
            return ex.code() in {
                grpc.StatusCode.UNAVAILABLE,
                grpc.StatusCode.DEADLINE_EXCEEDED,
                grpc.StatusCode.RESOURCE_EXHAUSTED,
            }
        else:
            return False

    def _handle_grpc_bad_request(self, ex: grpc.RpcError) -> ModelOutput | Exception:
        details = ex.details() or ""
        if "prompt_length" in details:
            return ModelOutput.from_content(
                model=self.model_name, content=details, stop_reason="model_length"
            )
        else:
            return ex

    def _handle_grpc_permission_denied(self, ex: grpc.RpcError) -> ModelOutput | None:
        details = ex.details() or ""
        if "safety_check" in details.lower():
            return ModelOutput.from_content(
                model=self.model_name, content=details, stop_reason="content_filter"
            )
        else:
            return None

    def _grok_tool_choice(
        self, tool_choice: ToolChoice
    ) -> ToolMode | chat_pb2.ToolChoice:
        match tool_choice:
            case "any":
                return "required"
            case "auto":
                return "auto"
            case "none":
                return "none"
            case ToolFunction(name=name):
                return chat_pb2.ToolChoice(
                    mode="TOOL_MODE_REQUIRED", function_name=name
                )

    def _grok_tool(self, tool_info: ToolInfo) -> chat_pb2.Tool:
        web_search_options = _get_grok_web_search_options(self.model_name, tool_info)
        if web_search_options is not None:
            return web_search(**web_search_options)
        else:
            return tool(
                name=tool_info.name,
                description=tool_info.description,
                parameters=tool_info.parameters.model_dump(exclude_none=True),
            )

    def _grok_params(self, config: GenerateConfig) -> dict[str, Any]:
        gconfig: dict[str, Any] = {}

        if config.max_tokens is not None:
            gconfig["max_tokens"] = config.max_tokens
        if config.seed is not None:
            gconfig["seed"] = config.seed
        # grok reasoning models (>= grok3) don't support these options
        if self.is_grok_2():
            if config.stop_seqs is not None:
                gconfig["stop"] = config.stop_seqs
            if config.frequency_penalty is not None:
                gconfig["frequency_penalty"] = config.frequency_penalty
            if config.presence_penalty is not None:
                gconfig["presence_penalty"] = config.presence_penalty
        if config.temperature is not None:
            gconfig["temperature"] = config.temperature
        if config.top_p is not None:
            gconfig["top_p"] = config.top_p
        if config.logprobs is not None:
            gconfig["logprobs"] = config.logprobs
        if config.top_logprobs is not None:
            gconfig["top_logprobs"] = config.top_logprobs
        if config.parallel_tool_calls is not None:
            gconfig["parallel_tool_calls"] = config.parallel_tool_calls

        if config.response_schema is not None:
            # we'll call chat.parse() above w/ the schema
            gconfig["response_format"] = "json_object"

        # note that grok-3-mini is the only model which supports a reasoning effort parameter
        if config.reasoning_effort is not None and self.is_grok_3_mini():
            match config.reasoning_effort:
                case "minimal" | "low":
                    gconfig["reasoning_effort"] = "low"
                case "medium" | "high":
                    gconfig["reasoning_effort"] = "high"

        # NOTE: this will be in an upcoming release (it's on main but not yet released)
        # gconfig["use_encypted_content"] = True

        return gconfig

    def _model_output_from_response(
        self, response: Response, tools: list[ToolInfo]
    ) -> ModelOutput:
        return ModelOutput(
            model=self.model_name,
            choices=[self._completion_choice_from_response(response, tools)],
            completion=response.content,
            usage=_model_usage_from_sampling_usage(response.usage),
        )

    def _completion_choice_from_response(
        self, response: Response, tools: list[ToolInfo]
    ) -> ChatCompletionChoice:
        # reasoning
        content: list[Content] = []
        if response.reasoning_content:
            content.append(ContentReasoning(reasoning=response.reasoning_content))

        # content + citations
        response_content = ContentText(text=response.content)
        if response.citations:
            response_content.citations = [
                UrlCitation(url=url) for url in response.citations
            ]
        content.append(response_content)

        # tool calls
        tool_calls: list[ToolCall] | None = None
        if response.tool_calls:
            tool_calls = [
                _tool_call_from_grok_call(tc, tools) for tc in response.tool_calls
            ]

        # logprobs
        logprobs = _logprobs_from_grok_logprobs(response.logprobs)

        return ChatCompletionChoice(
            message=ChatMessageAssistant(
                source="generate",
                content=content,
                tool_calls=tool_calls,
                model=self.model_name,
            ),
            stop_reason=_stop_reason_from_finish_reason(response.finish_reason),
            logprobs=logprobs,
        )


def _tool_call_from_grok_call(
    tool_call: chat_pb2.ToolCall, tools: list[ToolInfo]
) -> ToolCall:
    return parse_tool_call(
        id=tool_call.id,
        function=tool_call.function.name,
        arguments=tool_call.function.arguments,
        tools=tools,
    )


def _stop_reason_from_finish_reason(finish_reason: str) -> StopReason:
    match finish_reason:
        case "REASON_STOP":
            return "stop"
        case "REASON_TOOL_CALLS":
            return "tool_calls"
        case "REASON_MAX_CONTEXT":
            return "model_length"
        case "REASON_MAX_LEN":
            return "max_tokens"
        case _:
            return "unknown"


def _logprobs_from_grok_logprobs(grok_logprobs: chat_pb2.LogProbs) -> Logprobs | None:
    if len(grok_logprobs.content) == 0:
        return None

    content = [
        Logprob(
            token=lp.token,
            logprob=lp.logprob,
            bytes=list(lp.bytes),
            top_logprobs=[
                TopLogprob(token=tlp.token, logprob=tlp.logprob, bytes=list(tlp.bytes))
                for tlp in lp.top_logprobs
            ],
        )
        for lp in grok_logprobs.content
    ]

    return Logprobs(content=content)


def _model_usage_from_sampling_usage(usage: usage_pb2.SamplingUsage) -> ModelUsage:
    return ModelUsage(
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        input_tokens_cache_read=usage.cached_prompt_text_tokens,
        reasoning_tokens=usage.reasoning_tokens,
    )


async def _grok_messages(messages: list[ChatMessage]) -> list[chat_pb2.Message]:
    return [await _grok_message(message) for message in messages]


async def _grok_message(message: ChatMessage) -> chat_pb2.Message:
    match message:
        case ChatMessageSystem():
            return system(*(await _grok_content(message.content)))
        case ChatMessageUser():
            return user(*(await _grok_content(message.content)))
        case ChatMessageAssistant():
            return assistant(*(await _grok_content(message.content)))
        case ChatMessageTool():
            return tool_result(message.text)


async def _grok_content(content: str | list[Content]) -> list[str | chat_pb2.Content]:
    if isinstance(content, str):
        return [content]
    else:
        return [await _grok_content_item(c) for c in content]


async def _grok_content_item(content: Content) -> chat_pb2.Content:
    if isinstance(content, ContentText):
        return chat_pb2.Content(text=content.text)
    elif isinstance(content, ContentImage):
        return chat_pb2.Content(
            image_url={
                "image_url": content.image
                if is_http_url(content.image)
                else await file_as_data_uri(content.image),
                "detail": content.detail,
            }
        )
    else:
        raise ValueError(f"Unexpected content type for grok api: {type(content)}")


def _grok_media_filter(key: JsonValue | None, value: JsonValue) -> JsonValue:
    # remove images from raw api call
    if isinstance(value, dict) and "image_url" in value:
        value = copy(value)
        value.update(image_url=BASE_64_DATA_REMOVED)
    return value


class GrokAPI1(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="Grok",
            service_base_url="https://api.x.ai/v1",
        )

    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        # call super
        params = super().completion_params(config, tools)

        # only grok-3-mini supports reasoning effort:
        # https://docs.x.ai/docs/guides/reasoning#control-how-hard-the-model-thinks
        # further, reasoning effort must be either low or high
        if "reasoning_effort" in params:
            if "grok-3-mini" in self.model_name:
                match params["reasoning_effort"]:
                    case "minimal" | "low":
                        params["reasoning_effort"] = "low"
                    case "medium" | "high":
                        params["reasoning_effort"] = "high"
            else:
                params.pop("reasoning_effort", None)
        return params

    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        if ex.status_code == 400:
            # extract message
            if isinstance(ex.body, dict) and "message" in ex.body.keys():
                content = str(ex.body.get("message"))
            else:
                content = ex.message

            if "prompt length" in content:
                return ModelOutput.from_content(
                    model=self.model_name, content=content, stop_reason="model_length"
                )
            else:
                return ex
        elif ex.status_code == 403:
            # extract message
            if isinstance(ex.body, dict) and "message" in ex.body.keys():
                content = str(ex.body.get("message"))
            else:
                content = ex.message

            if "Content violates usage guidelines" in content:
                return ModelOutput.from_content(
                    model=self.model_name,
                    content=content,
                    stop_reason="content_filter",
                )
            else:
                return ex
        else:
            return ex

    @override
    def chat_choices_from_completion(
        self, completion: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        result = super().chat_choices_from_completion(completion, tools)

        return (
            [_add_citations(choice, citations) for choice in result]
            if (citations := _get_citations(completion))
            else result
        )

    @override
    def resolve_tools(
        self, tools: list[ToolInfo], tool_choice: ToolChoice, config: GenerateConfig
    ) -> tuple[list[ToolInfo], ToolChoice, GenerateConfig]:
        tools, tool_choice, config = super().resolve_tools(tools, tool_choice, config)

        new_config = config.model_copy()
        if new_config.extra_body is None:
            new_config.extra_body = {}

        grok_search_options, new_tools = _extract_web_search_options(
            self.model_name, tools
        )

        force_web_search = (
            isinstance(tool_choice, ToolFunction) and tool_choice.name == "web_search"
        )

        new_config.extra_body["search_parameters"] = (
            {"mode": "off"}
            if grok_search_options is None
            else {
                "mode": "on" if force_web_search else "auto",
                **grok_search_options,
            }
        )

        return (
            new_tools,
            "none" if force_web_search else tool_choice,
            new_config,
        )


def _get_citations(completion: ChatCompletion) -> list[UrlCitation] | None:
    """Extract citations from ChatCompletion model_extra."""
    model_extra = completion.model_extra
    grok_citations = model_extra.get("citations") if model_extra else None

    return (
        [
            UrlCitation(url=url)
            for url in [url for url in grok_citations if isinstance(url, str)]
        ]
        if grok_citations and isinstance(grok_citations, list)
        else None
    )


def _extract_web_search_options(
    model_name: str,
    tools: list[ToolInfo],
) -> tuple[dict[str, object] | None, list[ToolInfo]]:
    """Extract Grok web search options from tools and return filtered tools.

    Returns:
        A tuple of (web_search_options, filtered_tools) where:
        - web_search_options: The Grok options if a web_search tool is found, None otherwise
        - filtered_tools: All tools except the web_search tool with Grok options
    """
    filtered_tools = []
    web_search_options = None

    for t in tools:
        if (options := _get_grok_web_search_options(model_name, t)) is not None:
            web_search_options = options
        else:
            filtered_tools.append(t)

    return web_search_options, filtered_tools


def _get_grok_web_search_options(
    model_name: str, tool: ToolInfo
) -> dict[str, object] | None:
    """Check if a tool is a Grok web search tool and return its options."""
    return (
        cast(dict[str, object], grok_options)
        if (
            not model_name.startswith("grok-2")
            and tool.name == "web_search"
            and tool.options is not None
            and (grok_options := tool.options.get("grok", None)) is not None
        )
        else None
    )


def _add_citations(
    choice: ChatCompletionChoice, citations: list[UrlCitation] | None
) -> ChatCompletionChoice:
    if not choice.message.content:
        return choice

    # Grok citations are in no way correlated to any subset of a ChatCompletionChoice.
    # Because of this, we don't have any clue what cited text is relevant. This
    # code simply adds the citations to the last non-empty text content in the message

    updated_choice = choice.model_copy(deep=True)
    content_list: list[Content] = (
        [ContentText(text=updated_choice.message.content)]
        if isinstance(updated_choice.message.content, str)
        else updated_choice.message.content
    )
    updated_choice.message.content = content_list

    # Find the last non-empty ContentText entry
    last_text_content = next(
        (
            content
            for content in reversed(content_list)
            if isinstance(content, ContentText) and content.text.strip()
        ),
        None,
    )

    if last_text_content:
        last_text_content.citations = citations

    return updated_choice


class GrpcUnaryUnaryInterceptor(grpc.aio.UnaryUnaryClientInterceptor):
    """Interceptor for tracking unary-unary gRPC calls"""

    def __init__(self, hooks: "GrpcHooks") -> None:
        self.hooks = hooks

    async def intercept_unary_unary(
        self,
        continuation: Callable[[grpc.aio.ClientCallDetails, Any], Awaitable[Any]],
        client_call_details: grpc.aio.ClientCallDetails,
        request: Any,
    ) -> Any:
        # Get request_id from context and update request time
        request_id = self.hooks.get_request_id()
        if request_id:
            self.hooks.update_request_time(request_id)

        # Make the call and log it
        response = await continuation(client_call_details, request)
        logger.log(HTTP, f"gRPC {client_call_details.method} - OK")
        return response


class GrpcUnaryStreamInterceptor(grpc.aio.UnaryStreamClientInterceptor):
    """Interceptor for tracking unary-stream gRPC calls"""

    def __init__(self, hooks: "GrpcHooks") -> None:
        self.hooks = hooks

    async def intercept_unary_stream(
        self,
        continuation: Callable[  # type: ignore[type-arg]
            [grpc.aio.ClientCallDetails, Any], Awaitable[grpc.aio.UnaryStreamCall]
        ],
        client_call_details: grpc.aio.ClientCallDetails,
        request: Any,
    ) -> grpc.aio.UnaryStreamCall:  # type: ignore[type-arg]
        # Get request_id from context and update request time
        request_id = self.hooks.get_request_id()
        if request_id:
            self.hooks.update_request_time(request_id)

        # Make the call and log it
        response = await continuation(client_call_details, request)
        logger.log(HTTP, f"gRPC Stream {client_call_details.method} - Started")
        return response


class GrpcHooks(HttpHooks):
    def __init__(self) -> None:
        super().__init__()

        self.unary_unary_interceptor: grpc.aio.UnaryUnaryClientInterceptor = (
            GrpcUnaryUnaryInterceptor(self)
        )
        self.unary_stream_interceptor: grpc.aio.UnaryStreamClientInterceptor = (
            GrpcUnaryStreamInterceptor(self)
        )

    def get_interceptors(self) -> list[grpc.aio.ClientInterceptor]:
        return [self.unary_unary_interceptor, self.unary_stream_interceptor]

    def set_request_id(self, request_id: str) -> None:
        _request_id_var.set(request_id)

    def get_request_id(self) -> str | None:
        return _request_id_var.get()


_request_id_var: ContextVar[str | None] = ContextVar("grpc_request_id", default=None)


class GrokAsyncClient(AsyncClient):  # type: ignore[misc]
    def __init__(self, *args: Any, grpc_hooks: GrpcHooks, **kwargs: Any) -> None:
        self._grpc_hooks = grpc_hooks
        super().__init__(*args, **kwargs)

    def _make_grpc_channel(
        self,
        api_key: str,
        api_host: str,
        metadata: Optional[tuple[tuple[str, str]]],
        channel_options: Sequence[tuple[str, Any]],
        timeout: float,
    ) -> grpc.aio.Channel:
        """Creates a gRPC channel with a default timeout."""
        channel = grpc.aio.secure_channel(
            api_host,
            create_channel_credentials(api_key, api_host, metadata),
            options=channel_options,
            interceptors=[
                UnaryUnaryAioInterceptor(timeout),
                UnaryStreamAioInterceptor(timeout),
                *self._grpc_hooks.get_interceptors(),
            ],  # type: ignore
        )
        return channel
