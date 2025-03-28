from itertools import chain
from typing import TypedDict, cast

from openai.types.responses import (
    FunctionToolParam,
    ResponseComputerToolCall,
    ResponseComputerToolCallParam,
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
from openai.types.responses import Response as OpenAIResponse
from openai.types.responses.response import IncompleteDetails
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
from inspect_ai.model._chat_message import ChatMessage, ChatMessageAssistant
from inspect_ai.model._model_output import ChatCompletionChoice, StopReason
from inspect_ai.model._openai import is_o_series
from inspect_ai.model._openai_computer_use import (
    maybe_computer_call_output,
    maybe_computer_use_tool_param,
    tool_call_for_openai_computer_tool_call,
)
from inspect_ai.model._openai_internal_tools import ResponseToolCallInternal
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo


async def openai_responses_inputs(
    messages: list[ChatMessage], model: str
) -> list[ResponseInputItemParam]:
    responses_inputs: list[ResponseInputItemParam] = []
    for message in messages:
        responses_inputs.extend(await _openai_responses_input(message, model))
    return responses_inputs


async def _openai_responses_input(
    message: ChatMessage, model: str
) -> list[ResponseInputItemParam]:
    if message.role == "system":
        content = await _openai_responses_content_list_param(message.content)
        if is_o_series(model):
            return [Message(type="message", role="developer", content=content)]
        else:
            return [Message(type="message", role="system", content=content)]
    elif message.role == "user":
        return [
            Message(
                type="message",
                role="user",
                content=await _openai_responses_content_list_param(message.content),
            )
        ]
    elif message.role == "assistant":
        return _openai_input_items_from_chat_message_assistant(message)
    elif message.role == "tool":
        # TODO: Return ouptut types for internal tools e.g. computer, web_search
        if message.error is not None:
            output = message.error.message
        else:
            output = message.text

        internal = _model_tool_call_for_internal(message.internal)

        if internal.type == "computer_call":
            res = maybe_computer_call_output(message, internal)
            # TODO: Currently, we can't necessarily map this to a proper
            # `ComputerCallOutput`. This happens, for example, when we don't
            # have an image_url because of redacting old images. I wonder how
            # the model handles getting "function_call_output" for a
            # "computer_call"? In that case, the list will be empty.
            if res := maybe_computer_call_output(message, internal):
                return [res]

        return [
            FunctionCallOutput(
                type="function_call_output",
                call_id=message.tool_call_id or str(message.function),
                output=output,
            )
        ]
    else:
        raise ValueError(f"Unexpected message role '{message.role}'")


async def _openai_responses_content_list_param(
    content: str | list[Content],
) -> ResponseInputMessageContentListParam:
    if isinstance(content, str):
        content = [ContentText(text=content)]
    return [await _openai_responses_content_param(c) for c in content]


async def _openai_responses_content_param(
    content: Content,
) -> ResponseInputContentParam:  # type: ignore[return]
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
    return [_tool_param_for_tool_info(tool) for tool in tools]


def openai_responses_chat_choices(
    response: OpenAIResponse, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    message, stop_reason = _chat_message_assistant_from_openai_response(response, tools)
    return [ChatCompletionChoice(message=message, stop_reason=stop_reason)]


# The next two function perform transformations between OpenAI types an Inspect
# ChatMessageAssistant. Here is a diagram that helps visualize the transforms.
# ┌───────────────────────────┐    ┌───────────────────────────┐    ┌───────────────────────────┐
# │     OpenAI Response       │    │   ChatMessageAssistant    │    │      OpenAI Request       │
# │ id: resp_aaaaa            │    │ id: resp_aaaaa            │    │ id: rs_bbbbbb             │
# │ ┌───────────────────────┐ │    │ ┌───────────────────────┐ │    │ ┌───────────────────────┐ │
# │ │ output                │ │    │ │ content               │ │    │ │ input                 │ │
# │ │ ┌───────────────────┐ │ │    │ │ ┌───────────────────┐ │ │    │ │ ┌───────────────────┐ │ │
# │ │ │ type: "reasoning" │ │ │    │ │ │ ContentText       │ │ │    │ │ │ type: "reasoning" │ │ │
# │ │ │ id: "rs_bbbbbb"   │ │ │    │ │ │ text: ""          │ │ │    │ │ │ id: "rs_bbbbbb"   │ │ │
# │ │ │ summary: []       │ │ │    │ │ └───────────────────┘ │ │    │ │ │ summary: []       │ │ │
# │ │ └───────────────────┘ │ │    │ │ ┌───────────────────┐ │ │    │ │ └───────────────────┘ │ │
# │ │ ┌───────────────────┐ │ │    │ │ │ ContentText       │ │ │    │ │ ┌───────────────────┐ │ │
# │ │ │ type: "message"   │ │ │    │ │ │ text: "text1"     │ │ │    │ │ │ type: "message"   │ │ │
# │ │ │ id: "msg_ccccccc" │ │ │    │ │ └───────────────────┘ │ │    │ │ │ id: "msg_ccccccc" │ │ │
# │ │ │ role: "assistant" │ │ │--->│ │ ┌───────────────────┐ │ │--->│ │ │ role: "assistant" │ │ │
# │ │ │ ┌───────────────┐ │ │ │    │ │ │ ContentText       │ │ │    │ │ │ ┌───────────────┐ │ │ │
# │ │ │ │ Content       │ │ │ │    │ │ │ text: "text2"     │ │ │    │ │ │ │ Content       │ │ │ │
# │ │ │ │ ┌───────────┐ │ │ │ │    │ │ └───────────────────┘ │ │    │ │ │ │ ┌───────────┐ │ │ │ │
# │ │ │ │ │"text1"    │ │ │ │ │    │ └───────────────────────┘ │    │ │ │ │ │"text1"    │ │ │ │ │
# │ │ │ │ └───────────┘ │ │ │ │    │ ┌───────────────────────┐ │    │ │ │ │ └───────────┘ │ │ │ │
# │ │ │ │ ┌───────────┐ │ │ │ │    │ │ internal              │ │    │ │ │ │ ┌───────────┐ │ │ │ │
# │ │ │ │ │ "text2"   │ │ │ │ │    │ │ ┌───────────────────┐ │ │    │ │ │ │ │ "text2"   │ │ │ │ │
# │ │ │ │ └───────────┘ │ │ │ │    │ │ │ reasoning_id:     │ │ │    │ │ │ │ └───────────┘ │ │ │ │
# │ │ │ └───────────────┘ │ │ │    │ │ │ "rs_bbbbbb"       │ │ │    │ │ │ └───────────────┘ │ │ │
# │ │ └───────────────────┘ │ │    │ │ └───────────────────┘ │ │    │ │ └───────────────────┘ │ │
# │ └───────────────────────┘ │    │ │ ┌───────────────────┐ │ │    │ └───────────────────────┘ │
# └───────────────────────────┘    │ │ │ output_msg_id:    │ │ │    └───────────────────────────┘
#                                  │ │ │ "msg_ccccccc"     │ │ │
#                                  │ │ └───────────────────┘ │ │
#                                  │ └───────────────────────┘ │
#                                  └───────────────────────────┘


class _AssistantInternal(TypedDict):
    output_message_id: str | None
    reasoning_id: str | None


def _chat_message_assistant_from_openai_response(
    response: OpenAIResponse, tools: list[ToolInfo]
) -> tuple[ChatMessageAssistant, StopReason]:
    """
    Transform OpenAI `Response` into an Inspect `ChatMessageAssistant` and `StopReason`.

    It maps each `ResponseOutputItem` in `output` to a `Content` in the
    `content` field of the `ChatMessageAssistant`.

    It also keeps track of the OpenAI id's for each of the items in `.output`.
    The way we're doing it assumes that there won't be multiple items of the
    same type in the output. This seems ok, but who knows.
    """
    # determine the StopReason
    stop_reason: StopReason
    match response.incomplete_details:
        case IncompleteDetails(reason="max_output_tokens"):
            stop_reason = "max_tokens"
        case IncompleteDetails(reason="content_filter"):
            stop_reason = "content_filter"
        case _:
            stop_reason = "stop"

    # collect output and tool calls
    message_content: list[Content] = []
    tool_calls: list[ToolCall] = []
    internal = _AssistantInternal(output_message_id=None, reasoning_id=None)
    for output in response.output:
        match output:
            case ResponseOutputMessage(content=content, id=id):
                assert internal["output_message_id"] is None, "Multiple message outputs"
                internal["output_message_id"] = id
                message_content.extend(
                    [
                        ContentText(text=c.text)
                        if isinstance(c, ResponseOutputText)
                        else ContentText(text=c.refusal, refusal=True)
                        for c in content
                    ]
                )
            case ResponseReasoningItem(summary=summary, id=id):
                assert internal["reasoning_id"] is None, "Multiple reasoning items"
                internal["reasoning_id"] = id
                message_content.append(
                    ContentReasoning(
                        signature=output.id,
                        reasoning="\n".join([s.text for s in summary]),
                    )
                )
            case _:
                stop_reason = "tool_calls"
                match output:
                    case ResponseFunctionToolCall():
                        tool_calls.append(
                            parse_tool_call(
                                output.call_id,
                                output.name,
                                output.arguments,
                                tools,
                            )
                        )
                    case ResponseComputerToolCall():
                        tool_calls.append(
                            tool_call_for_openai_computer_tool_call(output)
                        )
                    case _:
                        raise ValueError(f"Unexpected output type: {output.__class__}")

    return (
        ChatMessageAssistant(
            id=response.id,
            content=message_content,
            internal=internal,
            tool_calls=tool_calls if len(tool_calls) > 0 else None,
            source="generate",
        ),
        stop_reason,
    )


def _openai_input_items_from_chat_message_assistant(
    message: ChatMessageAssistant,
) -> list[ResponseInputItemParam]:
    """
    Transform a `ChatMessageAssistant` into OpenAI `ResponseInputItem`'s for playback to the model.

    This is essentially the inverse transform of
    `_chat_message_assistant_from_openai_response`. It relies on the `internal`
    field of the `ChatMessageAssistant` to help it provide the proper id's the
    items in the returned list.
    """
    # As currently coded, this code only supports a single OutputMessage and
    # a single ReasoningItem for each Response/ChatMessageAssistant.
    assert isinstance(message.internal, dict), (
        "OpenAI ChatMessageAssistant internal must be an _AssistantInternal"
    )
    internal = cast(_AssistantInternal, message.internal)
    internal_output_message_id = internal["output_message_id"]
    internal_reasoning_id = internal["reasoning_id"]

    reasoning_item: ResponseReasoningItemParam | None = None
    output_message: ResponseOutputMessageParam | None = None

    for content in (
        list[ContentText | ContentReasoning]([ContentText(text=message.content)])
        if isinstance(message.content, str)
        else [
            c for c in message.content if isinstance(c, ContentText | ContentReasoning)
        ]
    ):
        match content:
            case ContentReasoning(reasoning=reasoning, signature=signature):
                assert reasoning_item is None, "Multiple reasoning items"
                # TODO: Review use of signature
                assert internal_reasoning_id == str(signature), (
                    "Mismatched reasoning id"
                )
                reasoning_item = ResponseReasoningItemParam(
                    type="reasoning",
                    id=str(signature),
                    summary=[Summary(type="summary_text", text=reasoning)],
                )
            case ContentText(text=text, refusal=refusal):
                new_content = (
                    ResponseOutputRefusalParam(type="refusal", refusal=text)
                    if refusal
                    else ResponseOutputTextParam(
                        type="output_text", text=text, annotations=[]
                    )
                )
                if output_message is None:
                    assert internal_output_message_id is not None, (
                        "Missing output message id"
                    )
                    output_message = ResponseOutputMessageParam(
                        type="message",
                        role="assistant",
                        id=internal_output_message_id,
                        # id=str(message.id).replace("resp_", "msg_", 1),
                        content=[new_content],
                        status="completed",
                    )
                else:
                    output_message["content"] = chain(
                        output_message["content"], [new_content]
                    )

    return [
        item for item in (reasoning_item, output_message) if item
    ] + _tool_call_items_from_assistant_message(message)


def _model_tool_call_for_internal(internal: object | None) -> ResponseToolCallInternal:
    assert isinstance(internal, dict), "OpenAI internal must be a dict"
    # TODO: Stop runtime validating these over and over once the code is stable
    match internal.get("type"):
        case "function_call":
            return ResponseFunctionToolCall.model_validate(internal)
        case "computer_call":
            return ResponseComputerToolCall.model_validate(internal)
        case _ as x:
            # TODO: Add support for other types
            raise NotImplementedError(f"Unsupported tool call type: {x}")


def _maybe_native_tool_param(tool: ToolInfo) -> ToolParam | None:
    # TODO: Is it worth plumbing this option?
    config_internal_tools = None
    return (
        (
            maybe_computer_use_tool_param(tool)
            # or self.text_editor_tool_param(tool)
            # or self.bash_tool_param(tool)
        )
        if config_internal_tools is not False
        else None
    )


def _tool_call_items_from_assistant_message(
    message: ChatMessageAssistant,
) -> list[ResponseInputItemParam]:
    return [
        cast(
            _ResponseToolCallParam,
            _model_tool_call_for_internal(call.internal).model_dump(),
        )
        for call in message.tool_calls or []
    ]


_ResponseToolCallParam = (
    ResponseFunctionToolCallParam | ResponseComputerToolCallParam
    # | ResponseFileSearchToolCallParam
    # | ResponseFunctionToolCallParam
    # | ResponseFunctionWebSearchParam
)


def _tool_param_for_tool_info(tool: ToolInfo) -> ToolParam:
    # Use a native tool implementation when available. Otherwise, use the
    # standard tool implementation
    return _maybe_native_tool_param(tool) or FunctionToolParam(
        type="function",
        name=tool.name,
        description=tool.description,
        parameters=tool.parameters.model_dump(exclude_none=True),
        strict=False,  # default parameters don't work in strict mode
    )
