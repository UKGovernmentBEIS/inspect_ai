import json

from openai.types.responses import (
    FunctionToolParam,
    Response,
    ResponseFunctionToolCall,
    ResponseFunctionToolCallParam,
    ResponseInputContentParam,
    ResponseInputImageParam,
    ResponseInputItemParam,
    ResponseInputMessageContentListParam,
    ResponseInputTextParam,
    ResponseOutputMessage,
    ResponseOutputMessageParam,
    ResponseOutputRefusalParam,
    ResponseOutputText,
    ResponseOutputTextParam,
    ResponseReasoningItem,
    ResponseReasoningItemParam,
    ToolChoiceFunctionParam,
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
from inspect_ai._util.images import file_as_data_uri
from inspect_ai._util.url import is_http_url
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._model_output import ChatCompletionChoice, StopReason
from inspect_ai.model._openai import is_o_series
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from ._chat_message import ChatMessage, ChatMessageAssistant


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
        reasoning_content = openai_responses_reasponing_content_params(message.content)
        if message.content:
            formatted_id = str(message.id).replace("resp_", "msg_", 1)
            if not formatted_id.startswith("msg_"):
                # These messages MUST start with `msg_`.
                # As `store=False` for this provider, OpenAI doesn't validate the IDs.
                # This will keep them consistent across calls though.
                formatted_id = f"msg_{formatted_id}"
            text_content = [
                ResponseOutputMessageParam(
                    type="message",
                    role="assistant",
                    id=formatted_id,
                    content=openai_responses_text_content_params(message.content),
                    status="completed",
                )
            ]
        else:
            text_content = []
        tools_content = openai_responses_tools_content_params(message.tool_calls)
        return reasoning_content + text_content + tools_content
    elif message.role == "tool":
        # TODO: Return ouptut types for internal tools e.g. computer, web_search
        if message.error is not None:
            output = message.error.message
        else:
            output = message.text
        return [
            FunctionCallOutput(
                type="function_call_output",
                call_id=message.tool_call_id or str(message.function),
                output=output,
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
        image_url = content.image
        if not is_http_url(image_url):
            image_url = await file_as_data_uri(image_url)

        return ResponseInputImageParam(
            type="input_image", detail=content.detail, image_url=image_url
        )
    else:
        # TODO: support for files (PDFs) and audio and video whenever
        # that is supported by the responses API (was not on initial release)

        # TODO: note that when doing this we should ensure that the
        # openai_media_filter is properly screening out base64 encoded
        # audio and video (if it exists, looks like it may all be done
        # w/ file uploads in the responses API)

        raise ValueError("Unsupported content type.")


def openai_responses_reasponing_content_params(
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


def openai_responses_text_content_params(
    content: str | list[Content],
) -> list[ResponseOutputTextParam | ResponseOutputRefusalParam]:
    if isinstance(content, str):
        content = [ContentText(text=content)]

    params: list[ResponseOutputTextParam | ResponseOutputRefusalParam] = []

    for c in content:
        if isinstance(c, ContentText):
            if c.refusal:
                params.append(
                    ResponseOutputRefusalParam(type="refusal", refusal=c.text)
                )
            else:
                params.append(
                    ResponseOutputTextParam(
                        type="output_text", text=c.text, annotations=[]
                    )
                )

    return params


def openai_responses_tools_content_params(
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
    match tool_choice:
        case "none" | "auto":
            return tool_choice
        case "any":
            return "required"
        # TODO: internal tools need to be converted to ToolChoiceTypesParam
        case _:
            return ToolChoiceFunctionParam(type="function", name=tool_choice.name)


def openai_responses_tools(tools: list[ToolInfo]) -> list[ToolParam]:
    # TODO: return special types for internal tools
    return [
        FunctionToolParam(
            type="function",
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters.model_dump(exclude_none=True),
            strict=False,  # default parameters don't work in strict mode
        )
        for tool in tools
    ]


def openai_responses_chat_choices(
    response: Response, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    # determine the StopReason
    stop_reason: StopReason = "stop"
    if response.incomplete_details is not None:
        if response.incomplete_details.reason == "max_output_tokens":
            stop_reason = "max_tokens"
        elif response.incomplete_details.reason == "content_filter":
            stop_reason = "content_filter"

    # collect output and tool calls
    message_content: list[Content] = []
    tool_calls: list[ToolCall] = []
    for output in response.output:
        if isinstance(output, ResponseOutputMessage):
            for content in output.content:
                if isinstance(content, ResponseOutputText):
                    message_content.append(ContentText(text=content.text))
                else:
                    message_content.append(
                        ContentText(text=content.refusal, refusal=True)
                    )
        elif isinstance(output, ResponseReasoningItem):
            reasoning = "\n".join([summary.text for summary in output.summary])
            if reasoning:
                message_content.append(
                    ContentReasoning(signature=output.id, reasoning=reasoning)
                )
        else:
            stop_reason = "tool_calls"
            if isinstance(output, ResponseFunctionToolCall):
                tool_calls.append(
                    parse_tool_call(
                        output.call_id,
                        output.name,
                        output.arguments,
                        tools,
                    )
                )
                pass
            else:
                ## TODO: implement support for internal tools
                raise ValueError(f"Unexpected output type: {output.__class__}")

    # return choice
    return [
        ChatCompletionChoice(
            message=ChatMessageAssistant(
                id=response.id,
                content=message_content,
                tool_calls=tool_calls if len(tool_calls) > 0 else None,
                source="generate",
            ),
            stop_reason=stop_reason,
        )
    ]
