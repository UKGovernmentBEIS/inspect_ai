import json
from typing import Literal

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

from inspect_ai._util.content import Content, ContentAudio, ContentImage, ContentText
from inspect_ai._util.images import file_as_data_uri
from inspect_ai._util.url import is_http_url
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._model_output import ChatCompletionChoice, Logprobs
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo

from ._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from ._model_output import ModelUsage, StopReason, as_stop_reason


def is_o_series(name: str) -> bool:
    return is_o1(name) or is_o3(name)


def is_o1(name: str) -> bool:
    return name.startswith("o1")


def is_o3(name: str) -> bool:
    return name.startswith("o3")


def is_o1_full(name: str) -> bool:
    return is_o1(name) and not is_o1_mini(name) and not is_o1_preview(name)


def is_o1_mini(name: str) -> bool:
    return name.startswith("o1-mini")


def is_o3_mini(name: str) -> bool:
    return name.startswith("o3-mini")


def is_o1_preview(name: str) -> bool:
    return name.startswith("o1-preview")


def is_gpt(name: str) -> bool:
    return name.startswith("gpt")


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
        type=tool_call.type,
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
        audio_data = await file_as_data_uri(content.audio)

        return ChatCompletionContentPartInputAudioParam(
            type="input_audio", input_audio=dict(data=audio_data, format=content.format)
        )

    else:
        raise RuntimeError(
            "Video content is not currently supported by Open AI chat models."
        )


async def openai_chat_message(
    message: ChatMessage, model: str
) -> ChatCompletionMessageParam:
    if message.role == "system":
        if is_o1(model):
            return ChatCompletionDeveloperMessageParam(
                role="developer", content=message.text
            )
        else:
            return ChatCompletionSystemMessageParam(
                role=message.role, content=message.text
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
                content=message.text,
                tool_calls=[
                    openai_chat_tool_call_param(call) for call in message.tool_calls
                ],
            )
        else:
            return ChatCompletionAssistantMessageParam(
                role=message.role, content=message.text
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
    messages: list[ChatMessage], model: str
) -> list[ChatCompletionMessageParam]:
    return [await openai_chat_message(message, model) for message in messages]


def openai_chat_choices(choices: list[ChatCompletionChoice]) -> list[Choice]:
    oai_choices: list[Choice] = []

    for index, choice in enumerate(choices):
        if isinstance(choice.message.content, str):
            content = choice.message.content
        else:
            content = "\n".join(
                [c.text for c in choice.message.content if c.type == "text"]
            )
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
    messages: list[ChatCompletionMessageParam],
) -> list[ChatMessage]:
    # track tool names by id
    tool_names: dict[str, str] = {}

    chat_messages: list[ChatMessage] = []

    for message in messages:
        if message["role"] == "system" or message["role"] == "developer":
            sys_content = message["content"]
            if isinstance(sys_content, str):
                chat_messages.append(ChatMessageSystem(content=sys_content))
            else:
                chat_messages.append(
                    ChatMessageSystem(
                        content=[content_from_openai(c) for c in sys_content]
                    )
                )
        elif message["role"] == "user":
            user_content = message["content"]
            if isinstance(user_content, str):
                chat_messages.append(ChatMessageUser(content=user_content))
            else:
                chat_messages.append(
                    ChatMessageUser(
                        content=[content_from_openai(c) for c in user_content]
                    )
                )
        elif message["role"] == "assistant":
            # resolve content
            asst_content = message["content"]
            if isinstance(asst_content, str):
                content: str | list[Content] = asst_content
            elif asst_content is None:
                content = message.get("refusal", None) or ""
            else:
                content = [content_from_openai(c) for c in asst_content]

            # resolve reasoning (OpenAI doesn't suport this however OpenAI-compatible
            # interfaces e.g. DeepSeek do include this field so we pluck it out)
            reasoning = message.get("reasoning_content", None) or message.get(
                "reasoning", None
            )
            if reasoning is not None:
                reasoning = str(reasoning)

            # return message
            if "tool_calls" in message:
                tool_calls: list[ToolCall] = []
                for tc in message["tool_calls"]:
                    tool_calls.append(tool_call_from_openai(tc))
                    tool_names[tc["id"]] = tc["function"]["name"]

            else:
                tool_calls = []
            chat_messages.append(
                ChatMessageAssistant(
                    content=content,
                    tool_calls=tool_calls or None,
                    reasoning=reasoning,
                )
            )
        elif message["role"] == "tool":
            tool_content = message.get("content", None) or ""
            if isinstance(tool_content, str):
                content = tool_content
            else:
                content = [content_from_openai(c) for c in tool_content]
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
) -> Content:
    if content["type"] == "text":
        return ContentText(text=content["text"])
    elif content["type"] == "image_url":
        return ContentImage(
            image=content["image_url"]["url"], detail=content["image_url"]["detail"]
        )
    elif content["type"] == "input_audio":
        return ContentAudio(
            audio=content["input_audio"]["data"],
            format=content["input_audio"]["format"],
        )
    elif content["type"] == "refusal":
        return ContentText(text=content["refusal"])


def chat_message_assistant_from_openai(
    message: ChatCompletionMessage, tools: list[ToolInfo]
) -> ChatMessageAssistant:
    refusal = getattr(message, "refusal", None)
    reasoning = getattr(message, "reasoning_content", None) or getattr(
        message, "reasoning", None
    )
    return ChatMessageAssistant(
        content=refusal or message.content or "",
        source="generate",
        tool_calls=chat_tool_calls_from_openai(message, tools),
        reasoning=reasoning,
    )


def chat_choices_from_openai(
    response: ChatCompletion, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    choices = list(response.choices)
    choices.sort(key=lambda c: c.index)
    return [
        ChatCompletionChoice(
            message=chat_message_assistant_from_openai(choice.message, tools),
            stop_reason=as_stop_reason(choice.finish_reason),
            logprobs=(
                Logprobs(**choice.logprobs.model_dump())
                if choice.logprobs is not None
                else None
            ),
        )
        for choice in choices
    ]
