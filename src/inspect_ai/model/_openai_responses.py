import json

from openai.types.responses import (
    Response,
    ResponseFunctionToolCallParam,
    ResponseInputContentParam,
    ResponseInputImageParam,
    ResponseInputItemParam,
    ResponseInputMessageContentListParam,
    ResponseInputTextParam,
    ResponseOutputMessageParam,
    ResponseOutputRefusalParam,
    ResponseOutputTextParam,
    ResponseReasoningItemParam,
    ToolParam,
)
from openai.types.responses.response_create_params import (
    ToolChoice as ResponsesToolChoice,
)
from openai.types.responses.response_input_item_param import FunctionCallOutput, Message
from openai.types.responses.response_reasoning_item_param import Summary

from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.model._openai import is_o_series
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from ._chat_message import ChatMessage


async def openai_responses_inputs(
    messages: list[ChatMessage], model: str
) -> list[ResponseInputItemParam]:
    responses_inputs: list[ResponseInputItemParam] = []
    for message in messages:
        responses_inputs.extend(await openai_responses_input(message, model))
    return responses_inputs


async def openai_responses_input(
    message: ChatMessage, model: str
) -> list[ResponseInputItemParam]:
    if message.role == "system":
        content = await openai_responses_content_list_param(message.content)
        if is_o_series(model):
            return [Message(type="message", role="developer", content=content)]
        else:
            return [Message(type="message", role="system", content=content)]
    elif message.role == "user":
        return [
            Message(
                type="message",
                role="user",
                content=await openai_responses_content_list_param(message.content),
            )
        ]
    elif message.role == "assistant":
        reasoning_content = await openai_responses_reasponing_content_params(
            message.content
        )
        text_content = [
            ResponseOutputMessageParam(
                type="message",
                role="assistant",
                id=str(message.id),
                content=await openai_responses_text_content_params(message.content),
                status="completed",
            )
        ]
        tools_content = await openai_responses_tools_content_params(message.tool_calls)
        return reasoning_content + text_content + tools_content
    elif message.role == "tool":
        if message.error is not None:
            output = message.error.message
        else:
            output = message.text
        return [
            FunctionCallOutput(
                type="function_call_output",
                call_id=message.tool_call_id or str(message.function),
                output=output,
                id=str(message.id),
            )
        ]
    else:
        raise ValueError(f"Unexpected message role '{message.role}'")


async def openai_responses_content_list_param(
    content: str | list[Content],
) -> ResponseInputMessageContentListParam:
    if isinstance(content, str):
        content = [ContentText(text=content)]
    return [await openai_responses_content_param(c) for c in content]


async def openai_responses_content_param(content: Content) -> ResponseInputContentParam:  # type: ignore[return]
    if isinstance(content, ContentText):
        return ResponseInputTextParam(type="input_text", text=content.text)
    elif isinstance(content, ContentImage):
        return ResponseInputImageParam(
            type="input_image", detail=content.detail, image_url=content.image
        )
    else:
        # ResponseInputFileParam
        raise ValueError("Unsupported content type.")


async def openai_responses_reasponing_content_params(
    content: str | list[Content],
) -> list[ResponseInputItemParam]:
    if isinstance(content, list):
        return [
            ResponseReasoningItemParam(
                type="reasoning",
                id=str(c.signature),
                summary=[Summary(type="summary_text", text=c.reasoning)],
            )
            for c in content
            if isinstance(c, ContentReasoning)
        ]
    else:
        return []


async def openai_responses_text_content_params(
    content: str | list[Content],
) -> list[ResponseOutputTextParam | ResponseOutputRefusalParam]:
    if isinstance(content, str):
        content = [ContentText(text=content)]

    return [
        ResponseOutputTextParam(type="output_text", text=c.text, annotations=[])
        for c in content
        if c.type == "text"
    ]


async def openai_responses_tools_content_params(
    tool_calls: list[ToolCall] | None,
) -> list[ResponseInputItemParam]:
    if tool_calls is not None:
        return [
            ResponseFunctionToolCallParam(
                type="function_call",
                call_id=call.id,
                name=call.function,
                arguments=json.dumps(call.arguments),
                status="completed",
            )
            for call in tool_calls
        ]
    else:
        return []


def openai_responses_tool_choice(tool_choice: ToolChoice) -> ResponsesToolChoice:
    return "auto"


def openai_responses_tools(tools: list[ToolInfo]) -> list[ToolParam]:
    return []


def openai_responses_chat_choices(
    response: Response, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    return []
