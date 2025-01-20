import json

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartInputAudioParam,
    ChatCompletionContentPartParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionDeveloperMessageParam,
    ChatCompletionMessage,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionNamedToolChoiceParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolChoiceOptionParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolParam,
    ChatCompletionUserMessageParam,
)
from openai.types.shared_params.function_definition import FunctionDefinition

from inspect_ai._util.content import Content
from inspect_ai._util.images import file_as_data_uri
from inspect_ai._util.url import is_http_url
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._model_output import ChatCompletionChoice, Logprobs
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo

from ._chat_message import ChatMessage, ChatMessageAssistant
from ._model_output import as_stop_reason


def openai_chat_tool_call(tool_call: ToolCall) -> ChatCompletionMessageToolCallParam:
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
    message: ChatMessage, o1_full: bool
) -> ChatCompletionMessageParam:
    if message.role == "system":
        if o1_full:
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
                tool_calls=[openai_chat_tool_call(call) for call in message.tool_calls],
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
    messages: list[ChatMessage], o1_full: bool
) -> list[ChatCompletionMessageParam]:
    return [await openai_chat_message(message, o1_full) for message in messages]


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


def chat_message_assistant_from_openai(
    message: ChatCompletionMessage, tools: list[ToolInfo]
) -> ChatMessageAssistant:
    return ChatMessageAssistant(
        content=message.content or "",
        source="generate",
        tool_calls=chat_tool_calls_from_openai(message, tools),
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
