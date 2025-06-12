import json
from typing import Sequence, TypedDict, cast

from openai.types.responses import (
    FunctionToolParam,
    ResponseComputerToolCall,
    ResponseComputerToolCallParam,
    ResponseFunctionToolCall,
    ResponseFunctionToolCallParam,
    ResponseFunctionWebSearch,
    ResponseFunctionWebSearchParam,
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
from openai.types.responses.response_output_text import (
    Annotation,
    AnnotationFileCitation,
    AnnotationFilePath,
    AnnotationURLCitation,
)
from openai.types.responses.response_reasoning_item_param import Summary
from pydantic import JsonValue

from inspect_ai._util.citation import Citation, DocumentCitation, UrlCitation
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
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from ._providers._openai_computer_use import (
    computer_call_output,
    maybe_computer_use_preview_tool,
    tool_call_from_openai_computer_tool_call,
)
from ._providers._openai_web_search import maybe_web_search_tool


async def openai_responses_inputs(
    messages: list[ChatMessage], model: str
) -> list[ResponseInputItemParam]:
    return [
        item
        for message in messages
        for item in await _openai_input_item_from_chat_message(message, model)
    ]


async def _openai_input_item_from_chat_message(
    message: ChatMessage, model: str
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
        return _openai_input_items_from_chat_message_assistant(message)
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
    tools: list[ToolInfo], model_name: str, config: GenerateConfig
) -> list[ToolParam]:
    return [_tool_param_for_tool_info(tool, model_name, config) for tool in tools]


def openai_responses_chat_choices(
    model: str, response: OpenAIResponse, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    message, stop_reason = _chat_message_assistant_from_openai_response(
        model, response, tools
    )
    return [ChatCompletionChoice(message=message, stop_reason=stop_reason)]


def is_native_tool_configured(
    tools: Sequence[ToolInfo], model_name: str, config: GenerateConfig
) -> bool:
    return any(
        _maybe_native_tool_param(tool, model_name, config) is not None for tool in tools
    )


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
    internal = _AssistantInternal(tool_message_ids={})
    for output in response.output:
        match output:
            case ResponseOutputMessage(content=content, id=id):
                message_content.extend(
                    [
                        ContentText(
                            text=c.text,
                            internal={"id": id},
                            citations=(
                                [
                                    _to_inspect_citation(annotation)
                                    for annotation in c.annotations
                                ]
                                if c.annotations
                                else None
                            ),
                        )
                        if isinstance(c, ResponseOutputText)
                        else ContentText(
                            text=c.refusal, refusal=True, internal={"id": id}
                        )
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
                    case ResponseFunctionWebSearch():
                        # We don't currently capture this since the model did the
                        # "tool call" internally. It's conceivable that could be
                        # forced to include it in `.internal` in the future, but
                        # for now we just ignore it.
                        # {"id":"ws_682cdcec3fa88198bc10b38fafefbd5e077e89e31fd4a3d5","status":"completed","type":"web_search_call"}
                        pass
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
    message: ChatMessageAssistant,
) -> list[ResponseInputItemParam]:
    """
    Transform a `ChatMessageAssistant` into OpenAI `ResponseInputItem`'s for playback to the model.

    This is essentially the inverse transform of
    `_chat_message_assistant_from_openai_response`. It relies on the `internal`
    field of the `ChatMessageAssistant` to help it provide the proper id's the
    items in the returned list.
    """
    tool_message_ids = _ids_from_assistant_internal(message)

    # we want to prevent yielding output messages in the case where we have an
    # 'internal' field (so the message came from the model API as opposed to
    # being user synthesized) AND there are no ContentText items with message IDs
    # (indicating that when reading the message from the server we didn't find output).
    # this could happen e.g. when a react() agent sets the output.completion in response
    # to a submit() tool call
    content_items: list[ContentText | ContentReasoning] = (
        [ContentText(text=message.content)]
        if isinstance(message.content, str)
        else [
            c for c in message.content if isinstance(c, ContentText | ContentReasoning)
        ]
    )
    has_content_with_ids = any(
        isinstance(c, ContentText)
        and isinstance(c.internal, dict)
        and "id" in c.internal
        for c in content_items
    )
    suppress_output_message = message.internal is not None and not has_content_with_ids

    # items to return
    items: list[ResponseInputItemParam] = []
    # group content by message ID
    messages_by_id: dict[
        str | None, list[ResponseOutputTextParam | ResponseOutputRefusalParam]
    ] = {}

    for content in _filter_consecutive_reasoning_blocks(content_items):
        match content:
            case ContentReasoning(reasoning=reasoning):
                assert content.signature is not None, (
                    "reasoning_id must be saved in signature"
                )
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

                # get the message ID from ContentText.modelJson
                content_message_id: str | None = None
                if isinstance(content.internal, dict) and "id" in content.internal:
                    id_value = content.internal["id"]
                    content_message_id = id_value if isinstance(id_value, str) else None
                else:
                    content_message_id = None

                new_content = (
                    ResponseOutputRefusalParam(type="refusal", refusal=text)
                    if refusal
                    else ResponseOutputTextParam(
                        type="output_text", text=text, annotations=[]
                    )
                )

                if content_message_id not in messages_by_id:
                    messages_by_id[content_message_id] = []
                messages_by_id[content_message_id].append(new_content)

    # create ResponseOutputMessage for each unique ID
    for msg_id, content_list in messages_by_id.items():
        output_message = ResponseOutputMessageParam(
            type="message",
            role="assistant",
            # this actually can be `None`, and it will in fact be `None` when the
            # assistant message is synthesized by the scaffold as opposed to being
            # replayed from the model
            id=msg_id,  # type: ignore[typeddict-item]
            content=content_list,
            status="completed",
        )
        items.append(output_message)

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
    model_name: str,
    config: GenerateConfig,
) -> ToolParam | None:
    return (
        (
            maybe_computer_use_preview_tool(tool)
            or maybe_web_search_tool(model_name, tool)
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
) -> dict[str, str]:
    if message.internal is not None:
        assert isinstance(message.internal, dict), (
            "OpenAI ChatMessageAssistant internal must be an _AssistantInternal"
        )
        internal = cast(_AssistantInternal, message.internal)
        return internal["tool_message_ids"]
    else:
        return {}


_ResponseToolCallParam = (
    ResponseFunctionToolCallParam
    | ResponseComputerToolCallParam
    | ResponseFunctionWebSearchParam
    # | ResponseFileSearchToolCallParam
    # | ResponseFunctionToolCallParam
)


def _tool_param_for_tool_info(
    tool: ToolInfo,
    model_name: str,
    config: GenerateConfig,
) -> ToolParam:
    # Use a native tool implementation when available. Otherwise, use the
    # standard tool implementation
    return _maybe_native_tool_param(tool, model_name, config) or FunctionToolParam(
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


def _to_inspect_citation(input: Annotation) -> Citation:
    match input:
        case AnnotationURLCitation(
            end_index=end_index, start_index=start_index, title=title, url=url
        ):
            return UrlCitation(
                cited_text=(start_index, end_index), title=title, url=url
            )

        case (
            AnnotationFileCitation(file_id=file_id, index=index)
            | AnnotationFilePath(file_id=file_id, index=index)
        ):
            return DocumentCitation(internal={"file_id": file_id, "index": index})
    assert False, f"Unexpected citation type: {input.type}"


def _filter_consecutive_reasoning_blocks(
    content_list: list[ContentText | ContentReasoning],
) -> list[ContentText | ContentReasoning]:
    return [
        content
        for i, content in enumerate(content_list)
        if _should_keep_content(i, content, content_list)
    ]


def _should_keep_content(
    i: int,
    content: ContentText | ContentReasoning,
    content_list: list[ContentText | ContentReasoning],
) -> bool:
    return (
        True
        if not isinstance(content, ContentReasoning)
        else i == len(content_list) - 1
        or not isinstance(content_list[i + 1], ContentReasoning)
    )
