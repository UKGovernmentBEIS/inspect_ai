import json
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
    ToolChoiceTypesParam,
    ToolParam,
)
from openai.types.responses import Response as OpenAIResponse
from openai.types.responses.response import IncompleteDetails
from openai.types.responses.response_create_params import (
    ToolChoice as ResponsesToolChoice,
)
from openai.types.responses.response_input_item_param import FunctionCallOutput, Message
from openai.types.responses.response_reasoning_item_param import Summary
from pydantic import JsonValue

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
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ChatCompletionChoice, StopReason
from inspect_ai.model._openai import is_o_series
from inspect_ai.model._openai_computer_use import (
    computer_call_output,
    maybe_computer_use_preview_tool,
    tool_call_from_openai_computer_tool_call,
)
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo


async def openai_responses_inputs(
    messages: list[ChatMessage], model: str, store: bool
) -> list[ResponseInputItemParam]:
    return [
        item
        for message in messages
        for item in await _openai_input_item_from_chat_message(message, model, store)
    ]


async def _openai_input_item_from_chat_message(
    message: ChatMessage, model: str, store: bool
) -> list[ResponseInputItemParam]:
    if message.role == "system":
        content = await _openai_responses_content_list_param(message.content)
        return (
            [Message(type="message", role="developer", content=content)]
            if is_o_series(model)
            else [Message(type="message", role="system", content=content)]
        )
    elif message.role == "user":
        return [
            Message(
                type="message",
                role="user",
                content=await _openai_responses_content_list_param(message.content),
            )
        ]
    elif message.role == "assistant":
        return _openai_input_items_from_chat_message_assistant(message, store)
    elif message.role == "tool":
        if message.internal:
            internal = _model_tool_call_for_internal(message.internal)
            if internal.type == "computer_call":
                return [computer_call_output(message, internal)]

        return [
            FunctionCallOutput(
                type="function_call_output",
                call_id=message.tool_call_id or str(message.function),
                output=message.error.message
                if message.error is not None
                else message.text,
            )
        ]

    else:
        raise ValueError(f"Unexpected message role '{message.role}'")


async def _openai_responses_content_list_param(
    content: str | list[Content],
) -> ResponseInputMessageContentListParam:
    return [
        await _openai_responses_content_param(c)
        for c in ([ContentText(text=content)] if isinstance(content, str) else content)
    ]


async def _openai_responses_content_param(
    content: Content,
) -> ResponseInputContentParam:  # type: ignore[return]
    if isinstance(content, ContentText):
        return ResponseInputTextParam(type="input_text", text=content.text)
    elif isinstance(content, ContentImage):
        return ResponseInputImageParam(
            type="input_image",
            detail=content.detail,
            image_url=(
                content.image
                if is_http_url(content.image)
                else await file_as_data_uri(content.image)
            ),
        )
    else:
        # TODO: support for files (PDFs) and audio and video whenever
        # that is supported by the responses API (was not on initial release)

        # TODO: note that when doing this we should ensure that the
        # openai_media_filter is properly screening out base64 encoded
        # audio and video (if it exists, looks like it may all be done
        # w/ file uploads in the responses API)

        raise ValueError("Unsupported content type.")


def openai_responses_tool_choice(
    tool_choice: ToolChoice, tools: list[ToolParam]
) -> ResponsesToolChoice:
    match tool_choice:
        case "none" | "auto":
            return tool_choice
        case "any":
            return "required"
        case _:
            return (
                ToolChoiceTypesParam(type="computer_use_preview")
                if tool_choice.name == "computer"
                and any(tool["type"] == "computer_use_preview" for tool in tools)
                else ToolChoiceFunctionParam(type="function", name=tool_choice.name)
            )


def openai_responses_tools(
    tools: list[ToolInfo], config: GenerateConfig
) -> list[ToolParam]:
    return [_tool_param_for_tool_info(tool, config) for tool in tools]


def openai_responses_chat_choices(
    model: str, response: OpenAIResponse, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    message, stop_reason = _chat_message_assistant_from_openai_response(
        model, response, tools
    )
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
# │ │ │ summary: []       │ │ │    │ │ ├───────────────────┤ │ │    │ │ │ summary: []       │ │ │
# │ │ ├───────────────────┤ │ │    │ │ │ ContentText       │ │ │    │ │ ├───────────────────┤ │ │
# │ │ │ type: "message"   │ │ │    │ │ │ text: "text1"     │ │ │    │ │ │ type: "message"   │ │ │
# │ │ │ id: "msg_ccccccc" │ │ │    │ │ ├───────────────────┤ │ │    │ │ │ id: "msg_ccccccc" │ │ │
# │ │ │ role: "assistant" │ │ │    │ │ │ ContentText       │ │ │    │ │ │ role: "assistant" │ │ │
# │ │ │ ┌───────────────┐ │ │ │ -> │ │ │ text: "text2"     │ │ │ -> │ │ │ ┌───────────────┐ │ │ │
# │ │ │ │ Content       │ │ │ │    │ │ └───────────────────┘ │ │    │ │ │ │ Content       │ │ │ │
# │ │ │ │ ┌───────────┐ │ │ │ │    │ └───────────────────────┘ │    │ │ │ │ ┌───────────┐ │ │ │ │
# │ │ │ │ │"text1"    │ │ │ │ │    │ ┌───────────────────────┐ │    │ │ │ │ │"text1"    │ │ │ │ │
# │ │ │ │ ├───────────┤ │ │ │ │    │ │ internal              │ │    │ │ │ │ ├───────────┤ │ │ │ │
# │ │ │ │ │"text2"    │ │ │ │ │    │ │ ┌───────────────────┐ │ │    │ │ │ │ │"text2"    │ │ │ │ │
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
    tool_message_ids: dict[str, str]


def _chat_message_assistant_from_openai_response(
    model: str, response: OpenAIResponse, tools: list[ToolInfo]
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
    internal = _AssistantInternal(output_message_id=None, tool_message_ids={})
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
                message_content.append(
                    ContentReasoning(
                        reasoning="\n".join([s.text for s in summary]), signature=id
                    )
                )
            case _:
                stop_reason = "tool_calls"
                match output:
                    case ResponseFunctionToolCall():
                        if output.id is not None:
                            internal["tool_message_ids"][output.call_id] = output.id
                        tool_calls.append(
                            parse_tool_call(
                                output.call_id,
                                _from_responses_tool_alias(output.name),
                                output.arguments,
                                tools,
                            )
                        )
                    case ResponseComputerToolCall():
                        if output.id is not None:
                            internal["tool_message_ids"][output.call_id] = output.id
                        tool_calls.append(
                            tool_call_from_openai_computer_tool_call(output)
                        )
                    case _:
                        raise ValueError(f"Unexpected output type: {output.__class__}")

    return (
        ChatMessageAssistant(
            id=response.id,
            content=message_content,
            internal=cast(JsonValue, internal),
            tool_calls=tool_calls if len(tool_calls) > 0 else None,
            model=model,
            source="generate",
        ),
        stop_reason,
    )


def _openai_input_items_from_chat_message_assistant(
    message: ChatMessageAssistant, store: bool
) -> list[ResponseInputItemParam]:
    """
    Transform a `ChatMessageAssistant` into OpenAI `ResponseInputItem`'s for playback to the model.

    This is essentially the inverse transform of
    `_chat_message_assistant_from_openai_response`. It relies on the `internal`
    field of the `ChatMessageAssistant` to help it provide the proper id's the
    items in the returned list.
    """
    (output_message_id, tool_message_ids) = _ids_from_assistant_internal(message)

    # we want to prevent yielding output messages in the case where we have an
    # 'internal' field (so the message came from the model API as opposed to
    # being user synthesized) AND there is no output_message_id (indicating that
    # when reading the message from the server we didn't find output). this could
    # happen e.g. when a react() agent sets the output.completion in response
    # to a submit() tool call
    suppress_output_message = message.internal is not None and output_message_id is None

    # if we are not storing messages on the server then blank these out
    if not store:
        output_message_id = None
        tool_message_ids = {}

    # items to return -- ensure we use a single output message (and just chain
    # additional content on to it)
    items: list[ResponseInputItemParam] = []
    output_message: ResponseOutputMessageParam | None = None

    for content in (
        list[ContentText | ContentReasoning]([ContentText(text=message.content)])
        if isinstance(message.content, str)
        else [
            c for c in message.content if isinstance(c, ContentText | ContentReasoning)
        ]
    ):
        match content:
            case ContentReasoning(reasoning=reasoning):
                assert content.signature is not None, (
                    "reasoning_id must be saved in signature"
                )
                # if items are not stored on the server then there is no
                # sense appending the reasoning item as its just a pointer
                if store:
                    items.append(
                        ResponseReasoningItemParam(
                            type="reasoning",
                            id=content.signature,
                            summary=[Summary(type="summary_text", text=reasoning)]
                            if reasoning
                            else [],
                        )
                    )
            case ContentText(text=text, refusal=refusal):
                if suppress_output_message:
                    continue

                new_content = (
                    ResponseOutputRefusalParam(type="refusal", refusal=text)
                    if refusal
                    else ResponseOutputTextParam(
                        type="output_text", text=text, annotations=[]
                    )
                )
                if output_message is None:
                    output_message = ResponseOutputMessageParam(
                        type="message",
                        role="assistant",
                        # this actually can be `None`, and it will in fact be `None` when the
                        # assistant message is synthesized by the scaffold as opposed to being
                        # replayed from the model (or when store=False)
                        id=output_message_id,  # type: ignore[typeddict-item]
                        content=[new_content],
                        status="completed",
                    )
                    items.append(output_message)
                else:
                    output_message["content"] = chain(
                        output_message["content"], [new_content]
                    )

    return items + _tool_call_items_from_assistant_message(message, tool_message_ids)


def _model_tool_call_for_internal(
    internal: JsonValue | None,
) -> ResponseFunctionToolCall | ResponseComputerToolCall:
    assert isinstance(internal, dict), "OpenAI internal must be a dict"
    # TODO: Stop runtime validating these over and over once the code is stable
    match internal.get("type"):
        case "function_call":
            return ResponseFunctionToolCall.model_validate(internal)
        case "computer_call":
            return ResponseComputerToolCall.model_validate(internal)
        case _ as x:
            raise NotImplementedError(f"Unsupported tool call type: {x}")


def _maybe_native_tool_param(
    tool: ToolInfo,
    config: GenerateConfig,
) -> ToolParam | None:
    return (
        (
            maybe_computer_use_preview_tool(tool)
            # or self.text_editor_tool_param(tool)
            # or self.bash_tool_param(tool)
        )
        if config.internal_tools or True
        else None
    )


def _tool_call_items_from_assistant_message(
    message: ChatMessageAssistant, tool_message_ids: dict[str, str]
) -> list[ResponseInputItemParam]:
    tool_calls: list[ResponseInputItemParam] = []
    for call in message.tool_calls or []:
        if isinstance(call.internal, dict):
            tool_calls.append(
                cast(
                    _ResponseToolCallParam,
                    _model_tool_call_for_internal(call.internal).model_dump(),
                )
            )
        else:
            # create param
            tool_call_param: ResponseFunctionToolCallParam = dict(
                type="function_call",
                call_id=call.id,
                name=_responses_tool_alias(call.function),
                arguments=json.dumps(call.arguments),
            )

            # add id if available
            tool_message_id = tool_message_ids.get(call.id, None)
            if tool_message_id is not None:
                tool_call_param["id"] = tool_message_id

            # append the param
            tool_calls.append(tool_call_param)

    return tool_calls


def _ids_from_assistant_internal(
    message: ChatMessageAssistant,
) -> tuple[str | None, dict[str, str]]:
    if message.internal is not None:
        assert isinstance(message.internal, dict), (
            "OpenAI ChatMessageAssistant internal must be an _AssistantInternal"
        )
        internal = cast(_AssistantInternal, message.internal)
        return (internal["output_message_id"], internal["tool_message_ids"])
    else:
        return None, {}


_ResponseToolCallParam = (
    ResponseFunctionToolCallParam | ResponseComputerToolCallParam
    # | ResponseFileSearchToolCallParam
    # | ResponseFunctionToolCallParam
    # | ResponseFunctionWebSearchParam
)


def _tool_param_for_tool_info(
    tool: ToolInfo,
    config: GenerateConfig,
) -> ToolParam:
    # Use a native tool implementation when available. Otherwise, use the
    # standard tool implementation
    return _maybe_native_tool_param(tool, config) or FunctionToolParam(
        type="function",
        name=_responses_tool_alias(tool.name),
        description=tool.description,
        parameters=tool.parameters.model_dump(exclude_none=True),
        strict=False,  # default parameters don't work in strict mode
    )


# these functions enables us to 'escape' built in tool names like 'python'

_responses_tool_aliases = {"python": "python_exec"}


def _responses_tool_alias(name: str) -> str:
    return _responses_tool_aliases.get(name, name)


def _from_responses_tool_alias(name: str) -> str:
    return next((k for k, v in _responses_tool_aliases.items() if v == name), name)
