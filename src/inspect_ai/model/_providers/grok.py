import json
import os
import time
from copy import copy
from typing import Any, Literal, cast

import grpc
from google.protobuf.json_format import MessageToDict
from pydantic import JsonValue
from tenacity import wait_exponential_jitter
from tenacity.wait import WaitBaseT
from typing_extensions import override
from xai_sdk import AsyncClient  # type: ignore
from xai_sdk.chat import (  # type: ignore
    Response,
    ToolMode,
    chat_pb2,
    system,
    tool,
    tool_result,
    usage_pb2,
    user,
)
from xai_sdk.tools import (  # type: ignore
    code_execution,
    get_tool_call_type,
    mcp,
    web_search,
)

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.constants import BASE_64_DATA_REMOVED
from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
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
from inspect_ai.model._providers.util.util import model_base_url
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._mcp._remote import is_mcp_server_tool
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
        disable_retry: bool = False,
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
        self.disable_retry = disable_retry
        if self.disable_retry:
            # retrying may be disabled so we can accurately track waiting time
            # (challenging to track GRPC internal retries w/o monkey patching).
            # we also implement a custom retry_wait method which retries a bit
            # more aggressively (the default is for an outer retry which is is
            # presumed is only being hit after many internal retries)
            model_args["channel_options"] = [
                ("grpc.enable_retries", 0),
                ("grpc.service_config", "{}"),
            ]
        self.model_args = model_args

        # create client
        self.initialize()

    def is_grok_2(self) -> bool:
        return "grok-2" in self.model_name

    def is_grok_3(self) -> bool:
        return "grok-3" in self.model_name

    def is_grok_3_mini(self) -> bool:
        return "grok-3-mini" in self.model_name

    def is_grok_4(self) -> bool:
        return "grok-4" in self.model_name

    def is_at_least_grok_4(self) -> bool:
        return not self.is_grok_2() and not self.is_grok_3()

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # create client
        client = AsyncClient(
            api_key=self.api_key,
            api_host=self.base_url,
            timeout=3600,  # api docs show tweaking this up for reasoning models
            **self.model_args,
        )

        # set start time
        start_time = time.monotonic()

        # setup request and response for ModelCall
        request: dict[str, Any] = {}
        response: dict[str, Any] = {}

        def model_call() -> ModelCall:
            return ModelCall.create(
                request=request,
                response=response,
                filter=_grok_media_filter,
                time=time.monotonic() - start_time,
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
            chat = client.chat.create(
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
                grpc.StatusCode.UNKNOWN,
                grpc.StatusCode.UNAVAILABLE,
                grpc.StatusCode.DEADLINE_EXCEEDED,
                grpc.StatusCode.RESOURCE_EXHAUSTED,
            }
        else:
            return False

    @override
    def retry_wait(self) -> WaitBaseT | None:
        if self.disable_retry:
            return wait_exponential_jitter(max=(30 * 60))
        else:
            return None

    @override
    def emulate_reasoning_history(self) -> bool:
        return False

    def _handle_grpc_bad_request(self, ex: grpc.RpcError) -> ModelOutput | Exception:
        details = ex.details() or ""
        if "prompt length" in details:
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
        web_search_options = self._get_grok_web_search_options(tool_info)
        if web_search_options is not None:
            return web_search(**web_search_options)
        elif self._is_internal_code_execution_tool(tool_info):
            return code_execution()
        elif is_mcp_server_tool(tool_info):
            mcp_config = MCPServerConfigHTTP.model_validate(tool_info.options)
            return mcp(
                server_url=mcp_config.url,
                server_label=mcp_config.name,
                server_description=mcp_config.name,
                allowed_tool_names=mcp_config.tools
                if isinstance(mcp_config.tools, list)
                else None,
                authorization=mcp_config.authorization_token,
                extra_headers=mcp_config.headers,
            )
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
                case "none":
                    raise ValueError(
                        "Grok models do not support 'none' for reasoning effort."
                    )
                case "minimal" | "low":
                    gconfig["reasoning_effort"] = "low"
                case "medium" | "high" | "xhigh":
                    gconfig["reasoning_effort"] = "high"

        # return encrypted reasoning blocks
        gconfig["use_encrypted_content"] = True

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
        # reasoning (use encrypted content if available)
        content: list[Content] = []
        if response.reasoning_content or response.encrypted_content:
            if response.encrypted_content:
                content.append(
                    ContentReasoning(
                        reasoning=response.encrypted_content,
                        redacted=True,
                        summary=response.reasoning_content
                        if response.reasoning_content
                        else None,
                    )
                )
            else:
                content.append(ContentReasoning(reasoning=response.reasoning_content))

        # partition tool calls into server and client
        server_tool_calls: list[chat_pb2.ToolCall] = []
        client_tool_calls: list[chat_pb2.ToolCall] = []
        for tool_call in response.tool_calls:
            if get_tool_call_type(tool_call) == "client_side_tool":
                client_tool_calls.append(tool_call)
            else:
                server_tool_calls.append(tool_call)

        # render server tool calls
        for tool_call in server_tool_calls:
            content.append(
                ContentToolUse(
                    tool_type=_tool_type_for_server_tool_call(tool_call),
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=tool_call.function.arguments,
                    result="",
                )
            )

        # content + citations
        if response.content or response.citations:
            response_content = ContentText(text=response.content)
            if response.citations:
                response_content.citations = [
                    UrlCitation(url=url) for url in response.citations
                ]
            content.append(response_content)

        # tool calls
        tool_calls: list[ToolCall] | None = None
        if client_tool_calls:
            tool_calls = [
                _tool_call_from_grok_call(tc, tools) for tc in client_tool_calls
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

    def _get_grok_web_search_options(self, tool: ToolInfo) -> dict[str, object] | None:
        """Check if a tool is a Grok web search tool and return its options."""
        return (
            cast(dict[str, object], grok_options)
            if (
                self.is_at_least_grok_4()
                and tool.name == "web_search"
                and tool.options is not None
                and (grok_options := tool.options.get("grok", None)) is not None
            )
            else None
        )

    def _is_internal_web_search_tool(self, tool: ToolInfo) -> bool:
        return self._get_grok_web_search_options(tool) is not None

    def _is_internal_code_execution_tool(self, tool: ToolInfo) -> bool:
        if tool.name == "code_execution" and tool.options is not None:
            return "grok" in tool.options.get("providers", {})
        else:
            return False


def _tool_call_from_grok_call(
    tool_call: chat_pb2.ToolCall, tools: list[ToolInfo]
) -> ToolCall:
    return parse_tool_call(
        id=tool_call.id,
        function=tool_call.function.name,
        arguments=tool_call.function.arguments,
        tools=tools,
    )


def _tool_type_for_server_tool_call(
    tool_call: chat_pb2.ToolCall,
) -> Literal["web_search", "code_execution"]:
    tool_call_type = get_tool_call_type(tool_call)
    if tool_call_type == "web_search_tool":
        return "web_search"
    elif tool_call_type == "code_execution_tool":
        return "code_execution"
    else:
        raise RuntimeError(f"Unexpcted server tool call type: {tool_call_type}")


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
            return await _grok_assistant_message(message)
        case ChatMessageTool():
            return tool_result(message.text)


async def _grok_assistant_message(message: ChatMessageAssistant) -> chat_pb2.Message:
    # assistant content and reasoning
    content: list[chat_pb2.Content] = []
    tool_calls: list[chat_pb2.ToolCall] = []
    reasoning_content: str | None = None
    encrypted_content: str | None = None
    if isinstance(message.content, str):
        content.append(chat_pb2.Content(text=message.content))
    else:
        for c in message.content:
            if isinstance(c, ContentReasoning):
                if c.redacted:
                    encrypted_content = c.reasoning
                else:
                    reasoning_content = c.reasoning
            elif isinstance(c, ContentToolUse):
                tool_calls.append(
                    chat_pb2.ToolCall(
                        id=c.id,
                        type=_grok_tool_call_type(c.tool_type),
                        function=chat_pb2.FunctionCall(
                            name=c.name, arguments=c.arguments
                        ),
                    )
                )
            else:
                content.append(await _grok_content_item(c))

    # tool calls
    if message.tool_calls is not None:
        for tool_call in message.tool_calls:
            tool_calls.append(
                chat_pb2.ToolCall(
                    id=tool_call.id,
                    type=chat_pb2.ToolCallType.TOOL_CALL_TYPE_CLIENT_SIDE_TOOL,
                    function=chat_pb2.FunctionCall(
                        name=tool_call.function,
                        arguments=json.dumps(tool_call.arguments),
                    ),
                )
            )

    # if content and tool calls are empty then fill with an empty assistant message
    if len(content) == 0 and len(tool_calls) == 0:
        content.append(chat_pb2.Content(text=""))

    # return message
    return chat_pb2.Message(
        role=chat_pb2.MessageRole.ROLE_ASSISTANT,
        content=content,
        reasoning_content=reasoning_content,
        encrypted_content=encrypted_content,
        tool_calls=tool_calls if len(tool_calls) > 0 else None,
    )


async def _grok_content(content: str | list[Content]) -> list[str | chat_pb2.Content]:
    if isinstance(content, str):
        return [content]
    else:
        return [await _grok_content_item(c) for c in content]


async def _grok_content_item(content: Content) -> chat_pb2.Content:
    if isinstance(content, ContentText):
        return chat_pb2.Content(text=content.text)
    elif isinstance(content, ContentImage):
        match content.detail:
            case "auto":
                detail = "DETAIL_AUTO"
            case "low":
                detail = "DETAIL_LOW"
            case "high":
                detail = "DETAIL_HIGH"
            case _:
                detail = "DETAIL_AUTO"

        return chat_pb2.Content(
            image_url={
                "image_url": content.image
                if is_http_url(content.image)
                else await file_as_data_uri(content.image),
                "detail": detail,
            }
        )
    elif isinstance(content, ContentToolUse):
        return chat_pb2.Content(text=f"{content.name}: {content.arguments}")
    else:
        raise ValueError(f"Unexpected content type for grok api: {type(content)}")


def _grok_tool_call_type(
    tool_type: Literal["web_search", "mcp_call", "code_execution"],
) -> chat_pb2.ToolCallType:
    match tool_type:
        case "web_search":
            return chat_pb2.ToolCallType.TOOL_CALL_TYPE_WEB_SEARCH_TOOL
        case "mcp_call":
            return chat_pb2.ToolCallType.TOOL_CALL_TYPE_MCP_TOOL
        case "code_execution":
            return chat_pb2.ToolCallType.TOOL_CALL_TYPE_CODE_EXECUTION_TOOL


def _grok_media_filter(key: JsonValue | None, value: JsonValue) -> JsonValue:
    # remove images from raw api call
    if isinstance(value, dict) and "image_url" in value:
        value = copy(value)
        value.update(image_url=BASE_64_DATA_REMOVED)
    return value
