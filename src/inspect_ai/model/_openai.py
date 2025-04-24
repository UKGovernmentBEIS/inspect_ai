import json
import re
import socket
from copy import copy
from typing import Any, Literal

import httpx
from openai import (
    DEFAULT_CONNECTION_LIMITS,
    DEFAULT_TIMEOUT,
    APIStatusError,
    APITimeoutError,
    OpenAIError,
    RateLimitError,
)
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartInputAudioParam,
    ChatCompletionContentPartParam,
    ChatCompletionContentPartRefusalParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionDeveloperMessageParam,
    ChatCompletionMessage,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCall,
    ChatCompletionMessageToolCallParam,
    ChatCompletionNamedToolChoiceParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolChoiceOptionParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolParam,
    ChatCompletionUserMessageParam,
)
from openai.types.chat.chat_completion import Choice, ChoiceLogprobs
from openai.types.chat.chat_completion_message_tool_call import Function
from openai.types.completion_usage import CompletionUsage
from openai.types.shared_params.function_definition import FunctionDefinition
from pydantic import JsonValue

from inspect_ai._util.constants import BASE_64_DATA_REMOVED
from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai._util.http import is_retryable_http_status
from inspect_ai._util.images import file_as_data_uri
from inspect_ai._util.url import is_http_url
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ChatCompletionChoice, Logprobs
from inspect_ai.model._reasoning import parse_content_with_reasoning
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo

from ._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from ._model_output import ModelOutput, ModelUsage, StopReason, as_stop_reason


class OpenAIResponseError(OpenAIError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def is_o_series(name: str) -> bool:
    if bool(re.match(r"^o\d+", name)):
        return True
    else:
        return not is_gpt(name) and bool(re.search(r"o\d+", name))


def is_o1(name: str) -> bool:
    return "o1" in name and not is_o1_early(name)


def is_o1_early(name: str) -> bool:
    return "o1-mini" in name or "o1-preview" in name


def is_o3_mini(name: str) -> bool:
    return "o3-mini" in name


def is_computer_use_preview(name: str) -> bool:
    return "computer-use-preview" in name


def is_gpt(name: str) -> bool:
    return "gpt" in name


def openai_chat_tool_call(tool_call: ToolCall) -> ChatCompletionMessageToolCall:
    return ChatCompletionMessageToolCall(
        type="function",
        id=tool_call.id,
        function=Function(
            name=tool_call.function, arguments=json.dumps(tool_call.arguments)
        ),
    )


def openai_chat_tool_call_param(
    tool_call: ToolCall,
) -> ChatCompletionMessageToolCallParam:
    return ChatCompletionMessageToolCallParam(
        id=tool_call.id,
        function=dict(
            name=tool_call.function, arguments=json.dumps(tool_call.arguments)
        ),
        type="function",
    )


async def openai_chat_completion_part(
    content: Content,
) -> ChatCompletionContentPartParam:
    if content.type == "text":
        return ChatCompletionContentPartTextParam(type="text", text=content.text)
    elif content.type == "image":
        # API takes URL or base64 encoded file. If it's a remote file or
        # data URL leave it alone, otherwise encode it
        image_url = content.image
        detail = content.detail

        if not is_http_url(image_url):
            image_url = await file_as_data_uri(image_url)

        return ChatCompletionContentPartImageParam(
            type="image_url",
            image_url=dict(url=image_url, detail=detail),
        )
    elif content.type == "audio":
        audio_data_uri = await file_as_data_uri(content.audio)
        audio_data = audio_data_uri.split("base64,")[1]

        return ChatCompletionContentPartInputAudioParam(
            type="input_audio", input_audio=dict(data=audio_data, format=content.format)
        )

    else:
        raise RuntimeError(
            "Video content is not currently supported by Open AI chat models."
        )


async def openai_chat_message(
    message: ChatMessage, system_role: Literal["user", "system", "developer"] = "system"
) -> ChatCompletionMessageParam:
    if message.role == "system":
        match system_role:
            case "user":
                return ChatCompletionUserMessageParam(role="user", content=message.text)
            case "system":
                return ChatCompletionSystemMessageParam(
                    role=message.role, content=message.text
                )
            case "developer":
                return ChatCompletionDeveloperMessageParam(
                    role="developer", content=message.text
                )
    elif message.role == "user":
        return ChatCompletionUserMessageParam(
            role=message.role,
            content=(
                message.content
                if isinstance(message.content, str)
                else [
                    await openai_chat_completion_part(content)
                    for content in message.content
                ]
            ),
        )
    elif message.role == "assistant":
        if message.tool_calls:
            return ChatCompletionAssistantMessageParam(
                role=message.role,
                content=openai_assistant_content(message),
                tool_calls=[
                    openai_chat_tool_call_param(call) for call in message.tool_calls
                ],
            )
        else:
            return ChatCompletionAssistantMessageParam(
                role=message.role, content=openai_assistant_content(message)
            )
    elif message.role == "tool":
        return ChatCompletionToolMessageParam(
            role=message.role,
            content=(
                f"Error: {message.error.message}" if message.error else message.text
            ),
            tool_call_id=str(message.tool_call_id),
        )
    else:
        raise ValueError(f"Unexpected message role {message.role}")


async def openai_chat_messages(
    messages: list[ChatMessage],
    system_role: Literal["user", "system", "developer"] = "system",
) -> list[ChatCompletionMessageParam]:
    return [await openai_chat_message(message, system_role) for message in messages]


def openai_completion_params(
    model: str, config: GenerateConfig, tools: bool
) -> dict[str, Any]:
    params: dict[str, Any] = dict(model=model)
    if config.max_tokens is not None:
        params["max_tokens"] = config.max_tokens
    if config.frequency_penalty is not None:
        params["frequency_penalty"] = config.frequency_penalty
    if config.stop_seqs is not None:
        params["stop"] = config.stop_seqs
    if config.presence_penalty is not None:
        params["presence_penalty"] = config.presence_penalty
    if config.logit_bias is not None:
        params["logit_bias"] = config.logit_bias
    if config.seed is not None:
        params["seed"] = config.seed
    if config.temperature is not None:
        params["temperature"] = config.temperature
    if config.top_p is not None:
        params["top_p"] = config.top_p
    if config.num_choices is not None:
        params["n"] = config.num_choices
    if config.logprobs is not None:
        params["logprobs"] = config.logprobs
    if config.top_logprobs is not None:
        params["top_logprobs"] = config.top_logprobs
    if tools and config.parallel_tool_calls is not None:
        params["parallel_tool_calls"] = config.parallel_tool_calls
    if config.reasoning_effort is not None:
        params["reasoning_effort"] = config.reasoning_effort
    if config.response_schema is not None:
        params["response_format"] = dict(
            type="json_schema",
            json_schema=dict(
                name=config.response_schema.name,
                schema=config.response_schema.json_schema.model_dump(exclude_none=True),
                description=config.response_schema.description,
                strict=config.response_schema.strict,
            ),
        )
    if config.extra_body:
        params["extra_body"] = config.extra_body

    return params


def openai_assistant_content(message: ChatMessageAssistant) -> str:
    if isinstance(message.content, str):
        content = message.content
    else:
        content = ""
        for c in message.content:
            if c.type == "reasoning":
                attribs = ""
                if c.signature is not None:
                    attribs = f'{attribs} signature="{c.signature}"'
                if c.redacted:
                    attribs = f'{attribs} redacted="true"'
                content = f"{content}\n<think{attribs}>\n{c.reasoning}\n</think>\n"
            elif c.type == "text":
                content = f"{content}\n{c.text}"
    return content


def openai_chat_choices(choices: list[ChatCompletionChoice]) -> list[Choice]:
    oai_choices: list[Choice] = []

    for index, choice in enumerate(choices):
        content = openai_assistant_content(choice.message)
        if choice.message.tool_calls:
            tool_calls = [openai_chat_tool_call(tc) for tc in choice.message.tool_calls]
        else:
            tool_calls = None
        message = ChatCompletionMessage(
            role="assistant", content=content, tool_calls=tool_calls
        )
        oai_choices.append(
            Choice(
                finish_reason=openai_finish_reason(choice.stop_reason),
                index=index,
                message=message,
                logprobs=ChoiceLogprobs(**choice.logprobs.model_dump())
                if choice.logprobs is not None
                else None,
            )
        )

    return oai_choices


def openai_completion_usage(usage: ModelUsage) -> CompletionUsage:
    return CompletionUsage(
        completion_tokens=usage.output_tokens,
        prompt_tokens=usage.input_tokens,
        total_tokens=usage.total_tokens,
    )


def openai_finish_reason(
    stop_reason: StopReason,
) -> Literal["stop", "length", "tool_calls", "content_filter", "function_call"]:
    match stop_reason:
        case "stop" | "tool_calls" | "content_filter":
            return stop_reason
        case "model_length":
            return "length"
        case _:
            return "stop"


def openai_chat_tool_param(tool: ToolInfo) -> ChatCompletionToolParam:
    function = FunctionDefinition(
        name=tool.name,
        description=tool.description,
        parameters=tool.parameters.model_dump(exclude_none=True),
    )
    return ChatCompletionToolParam(type="function", function=function)


def openai_chat_tools(tools: list[ToolInfo]) -> list[ChatCompletionToolParam]:
    return [openai_chat_tool_param(tool) for tool in tools]


def openai_chat_tool_choice(
    tool_choice: ToolChoice,
) -> ChatCompletionToolChoiceOptionParam:
    if isinstance(tool_choice, ToolFunction):
        return ChatCompletionNamedToolChoiceParam(
            type="function", function=dict(name=tool_choice.name)
        )
    # openai supports 'any' via the 'required' keyword
    elif tool_choice == "any":
        return "required"
    else:
        return tool_choice


def chat_tool_calls_from_openai(
    message: ChatCompletionMessage, tools: list[ToolInfo]
) -> list[ToolCall] | None:
    if message.tool_calls:
        return [
            parse_tool_call(call.id, call.function.name, call.function.arguments, tools)
            for call in message.tool_calls
        ]
    else:
        return None


def chat_messages_from_openai(
    model: str,
    messages: list[ChatCompletionMessageParam],
) -> list[ChatMessage]:
    # track tool names by id
    tool_names: dict[str, str] = {}

    chat_messages: list[ChatMessage] = []

    for message in messages:
        content: str | list[Content] = []
        if message["role"] == "system" or message["role"] == "developer":
            sys_content = message["content"]
            if isinstance(sys_content, str):
                chat_messages.append(ChatMessageSystem(content=sys_content))
            else:
                content = []
                for sc in sys_content:
                    content.extend(content_from_openai(sc))
                chat_messages.append(ChatMessageSystem(content=content))
        elif message["role"] == "user":
            user_content = message["content"]
            if isinstance(user_content, str):
                chat_messages.append(ChatMessageUser(content=user_content))
            else:
                content = []
                for uc in user_content:
                    content.extend(content_from_openai(uc))
                chat_messages.append(ChatMessageUser(content=content))
        elif message["role"] == "assistant":
            # resolve content
            refusal: Literal[True] | None = None
            asst_content = message.get("content", None)
            if isinstance(asst_content, str):
                result = parse_content_with_reasoning(asst_content)
                if result is not None:
                    content = [
                        ContentReasoning(
                            reasoning=result.reasoning,
                            signature=result.signature,
                            redacted=result.redacted,
                        ),
                        ContentText(text=result.content),
                    ]
                else:
                    content = asst_content
            elif asst_content is None:
                content = message.get("refusal", None) or ""
                if content:
                    refusal = True
            else:
                content = []
                for ac in asst_content:
                    content.extend(content_from_openai(ac, parse_reasoning=True))

            # resolve reasoning (OpenAI doesn't suport this however OpenAI-compatible
            # interfaces e.g. DeepSeek do include this field so we pluck it out)
            reasoning = message.get("reasoning_content", None) or message.get(
                "reasoning", None
            )
            if reasoning is not None:
                # normalize content to an array
                if isinstance(content, str):
                    content = [ContentText(text=content, refusal=refusal)]

                # insert reasoning
                content.insert(0, ContentReasoning(reasoning=str(reasoning)))

            # return message
            if "tool_calls" in message:
                tool_calls: list[ToolCall] = []
                for call in message["tool_calls"]:
                    tool_calls.append(tool_call_from_openai(call))
                    tool_names[call["id"]] = call["function"]["name"]

            else:
                tool_calls = []

            chat_messages.append(
                ChatMessageAssistant(
                    content=content,
                    tool_calls=tool_calls or None,
                    model=model,
                    source="generate",
                )
            )
        elif message["role"] == "tool":
            tool_content = message.get("content", None) or ""
            if isinstance(tool_content, str):
                content = tool_content
            else:
                content = []
                for tc in tool_content:
                    content.extend(content_from_openai(tc))
            chat_messages.append(
                ChatMessageTool(
                    content=content,
                    tool_call_id=message["tool_call_id"],
                    function=tool_names.get(message["tool_call_id"], ""),
                )
            )
        else:
            raise ValueError(f"Unexpected message param type: {type(message)}")

    return chat_messages


def tool_call_from_openai(tool_call: ChatCompletionMessageToolCallParam) -> ToolCall:
    return parse_tool_call(
        tool_call["id"],
        tool_call["function"]["name"],
        tool_call["function"]["arguments"],
    )


def content_from_openai(
    content: ChatCompletionContentPartParam | ChatCompletionContentPartRefusalParam,
    parse_reasoning: bool = False,
) -> list[Content]:
    # Some providers omit the type tag and use "object-with-a-single-field" encoding
    if "type" not in content and len(content) == 1:
        content["type"] = list(content.keys())[0]  # type: ignore[arg-type]
    if content["type"] == "text":
        text = content["text"]
        if parse_reasoning:
            result = parse_content_with_reasoning(text)
            if result:
                return [
                    ContentReasoning(
                        reasoning=result.reasoning,
                        signature=result.signature,
                        redacted=result.redacted,
                    ),
                    ContentText(text=result.content),
                ]
            else:
                return [ContentText(text=text)]
        else:
            return [ContentText(text=text)]
    elif content["type"] == "reasoning":  # type: ignore[comparison-overlap]
        return [ContentReasoning(reasoning=content["reasoning"])]
    elif content["type"] == "image_url":
        return [
            ContentImage(
                image=content["image_url"]["url"], detail=content["image_url"]["detail"]
            )
        ]
    elif content["type"] == "input_audio":
        return [
            ContentAudio(
                audio=content["input_audio"]["data"],
                format=content["input_audio"]["format"],
            )
        ]
    elif content["type"] == "refusal":
        return [ContentText(text=content["refusal"], refusal=True)]
    else:
        content_type = content["type"]
        raise ValueError(f"Unexpected content type '{content_type}' in message.")


def chat_message_assistant_from_openai(
    model: str, message: ChatCompletionMessage, tools: list[ToolInfo]
) -> ChatMessageAssistant:
    refusal = getattr(message, "refusal", None)
    reasoning = getattr(message, "reasoning_content", None) or getattr(
        message, "reasoning", None
    )

    msg_content = refusal or message.content or ""
    if reasoning is not None:
        content: str | list[Content] = [
            ContentReasoning(reasoning=str(reasoning)),
            ContentText(text=msg_content, refusal=True if refusal else None),
        ]
    elif refusal is not None:
        content = [ContentText(text=msg_content, refusal=True)]
    else:
        content = msg_content

    return ChatMessageAssistant(
        content=content,
        model=model,
        source="generate",
        tool_calls=chat_tool_calls_from_openai(message, tools),
    )


def model_output_from_openai(
    completion: ChatCompletion,
    choices: list[ChatCompletionChoice],
) -> ModelOutput:
    return ModelOutput(
        model=completion.model,
        choices=choices,
        usage=(
            ModelUsage(
                input_tokens=completion.usage.prompt_tokens,
                output_tokens=completion.usage.completion_tokens,
                input_tokens_cache_read=(
                    completion.usage.prompt_tokens_details.cached_tokens
                    if completion.usage.prompt_tokens_details is not None
                    else None  # openai only have cache read stats/pricing.
                ),
                reasoning_tokens=(
                    completion.usage.completion_tokens_details.reasoning_tokens
                    if completion.usage.completion_tokens_details is not None
                    else None
                ),
                total_tokens=completion.usage.total_tokens,
            )
            if completion.usage
            else None
        ),
    )


def chat_choices_from_openai(
    response: ChatCompletion, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    choices = list(response.choices)
    choices.sort(key=lambda c: c.index)
    return [
        ChatCompletionChoice(
            message=chat_message_assistant_from_openai(
                response.model, choice.message, tools
            ),
            stop_reason=as_stop_reason(choice.finish_reason),
            logprobs=(
                Logprobs(**choice.logprobs.model_dump())
                if choice.logprobs is not None
                else None
            ),
        )
        for choice in choices
    ]


def openai_should_retry(ex: Exception) -> bool:
    if isinstance(ex, RateLimitError):
        return True
    elif isinstance(ex, APIStatusError):
        return is_retryable_http_status(ex.status_code)
    elif isinstance(ex, OpenAIResponseError):
        return ex.code in ["rate_limit_exceeded", "server_error"]
    elif isinstance(ex, APITimeoutError):
        return True
    else:
        return False


def openai_handle_bad_request(
    model_name: str, e: APIStatusError
) -> ModelOutput | Exception:
    # extract message
    if isinstance(e.body, dict) and "message" in e.body.keys():
        content = str(e.body.get("message"))
    else:
        content = e.message

    # narrow stop_reason
    stop_reason: StopReason | None = None
    if e.code == "context_length_exceeded":
        stop_reason = "model_length"
    elif (
        e.code == "invalid_prompt"  # seems to happen for o1/o3
        or e.code == "content_policy_violation"  # seems to happen for vision
        or e.code == "content_filter"  # seems to happen on azure
    ):
        stop_reason = "content_filter"

    if stop_reason:
        return ModelOutput.from_content(
            model=model_name, content=content, stop_reason=stop_reason
        )
    else:
        return e


def openai_media_filter(key: JsonValue | None, value: JsonValue) -> JsonValue:
    # remove images from raw api call
    if key == "output" and isinstance(value, dict) and "image_url" in value:
        value = copy(value)
        value.update(image_url=BASE_64_DATA_REMOVED)
    if key == "image_url" and isinstance(value, dict) and "url" in value:
        url = str(value.get("url"))
        if url.startswith("data:"):
            value = copy(value)
            value.update(url=BASE_64_DATA_REMOVED)
    elif key == "input_audio" and isinstance(value, dict) and "data" in value:
        value = copy(value)
        value.update(data=BASE_64_DATA_REMOVED)
    return value


class OpenAIAsyncHttpxClient(httpx.AsyncClient):
    """Custom async client that deals better with long running Async requests.

    Based on Anthropic DefaultAsyncHttpClient implementation that they
    released along with Claude 3.7 as well as the OpenAI DefaultAsyncHttpxClient

    """

    def __init__(self, **kwargs: Any) -> None:
        # This is based on the openai DefaultAsyncHttpxClient:
        # https://github.com/openai/openai-python/commit/347363ed67a6a1611346427bb9ebe4becce53f7e
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        kwargs.setdefault("limits", DEFAULT_CONNECTION_LIMITS)
        kwargs.setdefault("follow_redirects", True)

        # This is based on the anthrpopic changes for claude 3.7:
        # https://github.com/anthropics/anthropic-sdk-python/commit/c5387e69e799f14e44006ea4e54fdf32f2f74393#diff-3acba71f89118b06b03f2ba9f782c49ceed5bb9f68d62727d929f1841b61d12bR1387-R1403

        # set socket options to deal with long running reasoning requests
        socket_options = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, True),
            (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 60),
            (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5),
        ]
        TCP_KEEPIDLE = getattr(socket, "TCP_KEEPIDLE", None)
        if TCP_KEEPIDLE is not None:
            socket_options.append((socket.IPPROTO_TCP, TCP_KEEPIDLE, 60))

        kwargs["transport"] = httpx.AsyncHTTPTransport(
            limits=DEFAULT_CONNECTION_LIMITS,
            socket_options=socket_options,
        )

        super().__init__(**kwargs)
