import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import reduce
from typing import TYPE_CHECKING, Any, Sequence, TypeGuard, cast

from openai.types.responses import (
    ComputerToolParam,
    EasyInputMessageParam,
    FunctionToolParam,
    ResponseComputerToolCall,
    ResponseComputerToolCallParam,
    ResponseFunctionToolCall,
    ResponseFunctionToolCallParam,
    ResponseFunctionWebSearch,
    ResponseFunctionWebSearchParam,
    ResponseInputContentParam,
    ResponseInputFileParam,
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
    ResponseUsage,
    ToolChoiceFunctionParam,
    ToolChoiceMcpParam,
    ToolChoiceTypesParam,
    ToolParam,
    WebSearchToolParam,
)
from openai.types.responses import Response as OpenAIResponse
from openai.types.responses.response import IncompleteDetails
from openai.types.responses.response_create_params import (
    ToolChoice as ResponsesToolChoiceParam,
)
from openai.types.responses.response_function_web_search_param import (
    Action,
    ActionSearch,
)
from openai.types.responses.response_input_item_param import (
    ComputerCallOutput,
    FunctionCallOutput,
    Message,
)
from openai.types.responses.response_input_item_param import McpCall as McpCallParam
from openai.types.responses.response_input_item_param import (
    McpListTools as McpListToolsParam,
)
from openai.types.responses.response_input_item_param import (
    McpListToolsTool as McpListToolsToolParam,
)
from openai.types.responses.response_output_item import (
    McpCall,
    McpListTools,
)
from openai.types.responses.response_output_message_param import (
    Content as OutputContent,
)
from openai.types.responses.response_output_text import (
    Annotation,
    AnnotationFileCitation,
    AnnotationFilePath,
    AnnotationURLCitation,
)
from openai.types.responses.response_output_text_param import (
    Annotation as AnnotationParam,
)
from openai.types.responses.response_reasoning_item_param import Summary as SummaryParam
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
)
from openai.types.responses.tool_param import Mcp
from pydantic import JsonValue, TypeAdapter, ValidationError

from inspect_ai._util.citation import Citation, DocumentCitation, UrlCitation
from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
    ContentVideo,
)
from inspect_ai._util.images import file_as_data_uri
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.url import is_http_url
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ChatCompletionChoice, ModelUsage, StopReason
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._mcp._remote import is_mcp_server_tool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from ._providers._openai_computer_use import (
    computer_call_output,
    maybe_computer_use_preview_tool,
    tool_call_from_openai_computer_tool_call,
)
from ._providers._openai_web_search import maybe_web_search_tool

if TYPE_CHECKING:
    from ._providers.openai import OpenAIAPI


MESSAGE_ID = "message_id"


async def openai_responses_inputs(
    messages: list[ChatMessage], openai_api: "OpenAIAPI"
) -> list[ResponseInputItemParam]:
    return [
        item
        for message in messages
        for item in await _openai_input_item_from_chat_message(message, openai_api)
    ]


async def _openai_input_item_from_chat_message(
    message: ChatMessage, openai_api: "OpenAIAPI"
) -> list[ResponseInputItemParam]:
    if message.role == "system":
        content = await _openai_responses_content_list_param(message.content)
        return (
            [Message(type="message", role="developer", content=content)]
            if openai_api.is_o_series() or openai_api.is_gpt_5()
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
        # see if we need to recover the call id for the computer tool calls
        responses_tool_call = assistant_internal().tool_calls.get(
            message.tool_call_id or str(message.function)
        )
        if (
            responses_tool_call is not None
            and responses_tool_call["type"] == "computer_call"
        ):
            return [computer_call_output(message, responses_tool_call["call_id"])]

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
    elif isinstance(content, ContentAudio | ContentVideo | ContentDocument):
        match content:
            case ContentAudio():
                contents = content.audio
                filename = f"audio.{content.format}"
            case ContentVideo():
                contents = content.video
                filename = f"video.{content.format}"
            case ContentDocument():
                contents = content.document
                filename = content.filename
            case _:
                raise TypeError(f"Unexpected content type: {type(content)}")

        file_data_uri = await file_as_data_uri(contents)

        return ResponseInputFileParam(
            type="input_file", file_data=file_data_uri, filename=filename
        )
    else:
        raise ValueError("Unsupported content type.")


def responses_extra_body_fields() -> list[str]:
    return [
        "service_tier",
        "max_tool_calls",
        "metadata",
        "previous_response_id",
        "prompt_cache_key",
        "safety_identifier",
        "truncation",
    ]


def openai_responses_tool_choice(
    tool_choice: ToolChoice, tools: list[ToolParam]
) -> ResponsesToolChoiceParam:
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
                else ToolChoiceTypesParam(type="web_search_preview")
                if tool_choice.name == "web_search"
                and any(tool["type"] == "web_search_preview" for tool in tools)
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


@dataclass
class _AssistantInternal:
    tool_calls: dict[
        str, ResponseFunctionToolCallParam | ResponseComputerToolCallParam
    ] = field(default_factory=dict)
    server_tool_uses: dict[str, ResponseInputItemParam] = field(default_factory=dict)


def assistant_internal() -> _AssistantInternal:
    return _openai_assistant_internal.get()


def init_sample_openai_assistant_internal() -> None:
    _openai_assistant_internal.set(_AssistantInternal())


_openai_assistant_internal: ContextVar[_AssistantInternal] = ContextVar(
    "opanai_assistant_internal", default=_AssistantInternal()
)


def content_from_response_input_content_param(
    input: ResponseInputContentParam,
) -> Content:
    if is_input_text(input):
        return ContentText(text=input["text"])
    elif is_input_image(input):
        assert input["image_url"]
        return ContentImage(image=input["image_url"], detail=input["detail"])
    elif is_input_file(input):
        return ContentDocument(document=input["file_data"], filename=input["filename"])
    else:
        raise RuntimeError(f"Unexpected input from responses API: {input}")


def is_tool_choice_function_param(
    tool_choice: ResponsesToolChoiceParam,
) -> TypeGuard[ToolChoiceFunctionParam]:
    if not isinstance(tool_choice, str):
        return tool_choice.get("type") == "function"
    else:
        return False


def is_tool_choice_mcp_param(
    tool_choice: ResponsesToolChoiceParam,
) -> TypeGuard[ToolChoiceMcpParam]:
    if not isinstance(tool_choice, str):
        return tool_choice.get("type") == "mcp"
    else:
        return False


def responses_model_usage(usage: ModelUsage | None) -> ResponseUsage | None:
    if usage is not None:
        return ResponseUsage(
            input_tokens=usage.input_tokens,
            input_tokens_details=InputTokensDetails(
                cached_tokens=usage.input_tokens_cache_read or 0
            ),
            output_tokens=usage.output_tokens,
            output_tokens_details=OutputTokensDetails(
                reasoning_tokens=usage.reasoning_tokens or 0
            ),
            total_tokens=usage.total_tokens,
        )
    else:
        return None


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
    for output in response.output:
        match output:
            case ResponseOutputMessage(content=content, id=id):
                message_content.extend(
                    [
                        ContentText(
                            text=c.text,
                            internal={MESSAGE_ID: id},
                            citations=(
                                [
                                    to_inspect_citation(annotation)
                                    for annotation in c.annotations
                                ]
                                if c.annotations
                                else None
                            ),
                        )
                        if isinstance(c, ResponseOutputText)
                        else ContentText(
                            text=c.refusal, refusal=True, internal={MESSAGE_ID: id}
                        )
                        for c in content
                    ]
                )
            case ResponseReasoningItem():
                message_content.append(reasoning_from_responses_reasoning(output))

            case ResponseFunctionToolCall():
                stop_reason = "tool_calls"
                if output.id is not None:
                    assistant_internal().tool_calls[output.call_id] = cast(
                        ResponseFunctionToolCallParam, output.model_dump()
                    )

                tool_calls.append(
                    parse_tool_call(
                        output.call_id,
                        _from_responses_tool_alias(output.name),
                        output.arguments,
                        tools,
                    )
                )
            case ResponseComputerToolCall():
                stop_reason = "tool_calls"
                if output.id is not None:
                    assistant_internal().tool_calls[output.call_id] = cast(
                        ResponseComputerToolCallParam, output.model_dump()
                    )

                tool_calls.append(tool_call_from_openai_computer_tool_call(output))

            case ResponseFunctionWebSearch():
                assistant_internal().server_tool_uses[output.id] = cast(
                    ResponseFunctionWebSearchParam, output.model_dump()
                )
                message_content.append(web_search_to_tool_use(output))
            case McpListTools():
                assistant_internal().server_tool_uses[output.id] = cast(
                    McpListToolsParam, output.model_dump()
                )
                message_content.append(mcp_list_tools_to_tool_use(output))
            case McpCall():
                assistant_internal().server_tool_uses[output.id] = cast(
                    McpCallParam, output.model_dump()
                )
                message_content.append(mcp_call_to_tool_use(output))
            case _:
                raise ValueError(f"Unexpected output type: {output.__class__}")

    return (
        ChatMessageAssistant(
            content=message_content,
            tool_calls=tool_calls if len(tool_calls) > 0 else None,
            model=model,
            source="generate",
        ),
        stop_reason,
    )


def reasoning_from_responses_reasoning(
    item: ResponseReasoningItem | ResponseReasoningItemParam,
) -> ContentReasoning:
    if not isinstance(item, ResponseReasoningItem):
        item = ResponseReasoningItem.model_validate(item)

    if item.encrypted_content is not None:
        reasoning = item.encrypted_content
        redacted = True
    else:
        reasoning = "\n".join([s.text for s in item.summary])
        if item.content is not None:
            reasoning = f"{reasoning}\n" + "\n".join([s.text for s in item.content])
        redacted = False

    return ContentReasoning(reasoning=reasoning, signature=item.id, redacted=redacted)


def responses_reasoning_from_reasoning(
    content: ContentReasoning,
) -> ResponseReasoningItemParam:
    assert content.signature is not None, "reasoning_id must be saved in signature"

    summary: list[SummaryParam] = []
    if content.redacted:
        encrypted_content: str | None = content.reasoning
    else:
        encrypted_content = None
        if content.reasoning:
            summary.append(SummaryParam(type="summary_text", text=content.reasoning))

    return ResponseReasoningItemParam(
        type="reasoning",
        id=content.signature,
        summary=summary,
        encrypted_content=encrypted_content,
    )


mcp_tool_adapter = TypeAdapter(list[McpListToolsToolParam])


def web_search_to_tool_use(output: ResponseFunctionWebSearch) -> ContentToolUse:
    return ContentToolUse(
        tool_type="web_search",
        id=output.id,
        name=output.action.type,
        arguments=output.action.to_json(),
        result="",
        error="failed" if output.status == "failed" else None,
    )


def mcp_list_tools_to_tool_use(output: McpListTools) -> ContentToolUse:
    return ContentToolUse(
        tool_type="mcp_call",
        id=output.id,
        name="mcp_list_tools",
        arguments="",
        result=to_json_str_safe([tool.model_dump() for tool in output.tools]),
        error=output.error,
    )


def mcp_call_to_tool_use(output: McpCall) -> ContentToolUse:
    return ContentToolUse(
        tool_type="mcp_call",
        id=output.id,
        name=output.name,
        context=output.server_label,
        arguments=output.arguments,
        result=output.output or "",
        error=output.error,
    )


def tool_use_to_mcp_list_tools_param(content: ContentToolUse) -> McpListToolsParam:
    return McpListToolsParam(
        type="mcp_list_tools",
        id=content.id,
        server_label=content.context or "",
        tools=mcp_tool_adapter.validate_json(content.result),
        error=content.error,
    )


def tool_use_to_mcp_call_param(content: ContentToolUse) -> McpCallParam:
    return McpCallParam(
        type="mcp_call",
        id=content.id,
        name=content.name,
        arguments=content.arguments,
        server_label=content.context or "",
        output=content.result,
        error=content.error,
    )


action_adapter = TypeAdapter[Action](Action)


def tool_use_to_web_search_param(
    content: ContentToolUse,
) -> ResponseFunctionWebSearchParam:
    try:
        action = action_adapter.validate_json(content.arguments)
    except ValidationError:
        action = ActionSearch(type="search", query=content.arguments)

    return ResponseFunctionWebSearchParam(
        type="web_search_call",
        id=content.id,
        action=action,
        status="failed" if content.error else "completed",
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
    # we want to prevent yielding output messages in the case where we have an
    # 'internal' field (so the message came from the model API as opposed to
    # being user synthesized) AND there are no ContentText items with message IDs
    # (indicating that when reading the message from the server we didn't find output).
    # this could happen e.g. when a react() agent sets the output.completion in response
    # to a submit() tool call
    content_items: list[ContentText | ContentReasoning | ContentToolUse] = (
        [ContentText(text=message.content)]
        if isinstance(message.content, str)
        else [
            c
            for c in message.content
            if isinstance(c, ContentText | ContentReasoning | ContentToolUse)
        ]
    )

    # items to return
    items: list[ResponseInputItemParam] = []
    pending_response_output_id: str | None = None
    pending_response_output: list[
        ResponseOutputRefusalParam | ResponseOutputTextParam
    ] = []

    def flush_pending_context_text() -> None:
        nonlocal pending_response_output_id
        if len(pending_response_output) > 0:
            items.append(
                ResponseOutputMessageParam(
                    type="message",
                    role="assistant",
                    # this actually can be `None`, and it will in fact be `None` when the
                    # assistant message is synthesized by the scaffold as opposed to being
                    # replayed from the model
                    # Is it okay to dynamically generate this here? We need this in
                    # order to read this back into the equivalent BaseModel for the bridge
                    id=pending_response_output_id,  # type: ignore[typeddict-item]
                    content=pending_response_output,
                    status="completed",
                )
            )
        pending_response_output_id = None
        pending_response_output.clear()

    for content in _filter_consecutive_reasoning_blocks(content_items):
        # flush if we aren't ContentText
        if not isinstance(content, ContentText):
            flush_pending_context_text()

        match content:
            case ContentReasoning():
                items.append(responses_reasoning_from_reasoning(content))
            case ContentToolUse(
                id=id,
                tool_type=tool_type,
            ):
                if id in assistant_internal().server_tool_uses:
                    items.append(assistant_internal().server_tool_uses[id])
                elif tool_type == "mcp_call":
                    if content.name == "mcp_list_tools":
                        items.append(tool_use_to_mcp_list_tools_param(content))
                    else:
                        items.append(tool_use_to_mcp_call_param(content))
                elif tool_type == "web_search":
                    items.append(tool_use_to_web_search_param(content))

                else:
                    raise ValueError(
                        f"OpenAI Responses: Unspected tool_type '{tool_type}'"
                    )
            case ContentText(text=text, refusal=refusal):
                # see if we have a message id
                message_id: str | None = None
                if (
                    isinstance(content.internal, dict)
                    and MESSAGE_ID in content.internal
                ):
                    id_value = content.internal[MESSAGE_ID]
                    message_id = id_value if isinstance(id_value, str) else None
                else:
                    message_id = None

                # see if we need to flush
                if message_id is not pending_response_output_id:
                    flush_pending_context_text()

                # register pending output
                pending_response_output_id = message_id
                pending_response_output.append(
                    ResponseOutputRefusalParam(type="refusal", refusal=text)
                    if refusal
                    else ResponseOutputTextParam(
                        type="output_text", text=text, annotations=[]
                    )
                )

    # final flush if necessary
    flush_pending_context_text()

    return items + _tool_call_items_from_assistant_message(message)


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
            or maybe_mcp_tool(tool)
            # or self.text_editor_tool_param(tool)
            # or self.bash_tool_param(tool)
        )
        if config.internal_tools or True
        else None
    )


def _tool_call_items_from_assistant_message(
    message: ChatMessageAssistant,
) -> list[ResponseInputItemParam]:
    tool_calls: list[ResponseInputItemParam] = []

    # now standard tool calls
    for call in message.tool_calls or []:
        # see if we have it in assistant_internal
        assistant_internal_call = assistant_internal().tool_calls.get(call.id, None)
        if assistant_internal_call is not None:
            tool_calls.append(assistant_internal_call)
        else:
            # create param
            tool_call_param: ResponseFunctionToolCallParam = dict(
                type="function_call",
                call_id=call.id,
                name=_responses_tool_alias(call.function),
                arguments=json.dumps(call.arguments),
            )

            # append the param
            tool_calls.append(tool_call_param)

    return tool_calls


_ResponseToolCallParam = (
    ResponseFunctionToolCallParam
    | ResponseComputerToolCallParam
    | ResponseFunctionWebSearchParam
    # | ResponseFileSearchToolCallParam
)


def maybe_mcp_tool(tool: ToolInfo) -> Mcp | None:
    if is_mcp_server_tool(tool):
        mcp_server = MCPServerConfigHTTP.model_validate(tool.options)
        return Mcp(
            type="mcp",
            server_label=mcp_server.name,
            server_url=mcp_server.url,
            headers=mcp_server.headers,
            allowed_tools=mcp_server.tools
            if isinstance(mcp_server.tools, list)
            else None,
            require_approval="never",
        )
    else:
        return None


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


def to_inspect_citation(input: Annotation | AnnotationParam) -> Citation:
    if isinstance(input, dict):
        if input["type"] == "url_citation":
            input = AnnotationURLCitation.model_validate(input)
        elif input["type"] == "file_path":
            input = AnnotationFilePath.model_validate(input)
        elif input["type"] == "file_citation":
            input = AnnotationFileCitation.model_validate(input)
        else:
            assert False, f"Unexpected citation type: {input['type']}"

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

        case _:
            assert False, f"Unexpected citation type: {input.type}"


def _filter_consecutive_reasoning_blocks(
    content_list: list[ContentText | ContentReasoning | ContentToolUse],
) -> list[ContentText | ContentReasoning | ContentToolUse]:
    return reduce(_reasoning_reducer, content_list, [])


def _reasoning_reducer(
    acc: list[ContentText | ContentReasoning | ContentToolUse],
    curr: ContentText | ContentReasoning | ContentToolUse,
) -> list[ContentText | ContentReasoning | ContentToolUse]:
    # Keep only the last ContentReasoning in each consecutive run
    if not acc:
        acc = [curr]

    # Replace previous with current if they're both ContentReasoning's
    elif isinstance(acc[-1], ContentReasoning) and isinstance(curr, ContentReasoning):
        acc[-1] = curr

    else:
        acc.append(curr)

    return acc


def is_input_text(
    input: ResponseInputContentParam,
) -> TypeGuard[ResponseInputTextParam]:
    return input.get("type") == "input_text"


def is_input_image(
    input: ResponseInputContentParam,
) -> TypeGuard[ResponseInputImageParam]:
    return input.get("type") == "input_image"


def is_input_file(
    input: ResponseInputContentParam,
) -> TypeGuard[ResponseInputFileParam]:
    return input.get("type") == "input_file"


def is_response_input_message(
    param: ResponseInputItemParam,
) -> TypeGuard[Message | EasyInputMessageParam]:
    return param["type"] == "message" and not is_response_output_message(param)


def is_function_call_output(
    param: ResponseInputItemParam,
) -> TypeGuard[FunctionCallOutput]:
    return param["type"] == "function_call_output"


def is_computer_call_output(
    param: ResponseInputItemParam,
) -> TypeGuard[ComputerCallOutput]:
    return param["type"] == "computer_call_output"


def is_assistant_message_param(
    param: ResponseInputItemParam,
) -> bool:
    return (
        is_response_output_message(param)
        or is_response_computer_tool_call(param)
        or is_response_web_search_call(param)
        or is_response_function_tool_call(param)
        or is_response_reasoning_item(param)
        or is_response_mcp_list_tools(param)
        or is_response_mcp_call(param)
    )


def is_response_output_message(
    param: ResponseInputItemParam,
) -> TypeGuard[ResponseOutputMessageParam]:
    return (
        param["type"] == "message"
        and param["role"] == "assistant"
        and isinstance(param.get("content", None), list)
        and any(
            c.get("type", "") in ["output_text", "refusal"]
            for c in cast(list[dict[str, Any]], param["content"])
        )
    )


def is_response_output_text(
    output: OutputContent,
) -> TypeGuard[ResponseOutputTextParam]:
    return output["type"] == "output_text"


def is_response_output_refusal(
    output: OutputContent,
) -> TypeGuard[ResponseOutputRefusalParam]:
    return output["type"] == "refusal"


def is_response_computer_tool_call(
    param: ResponseInputItemParam,
) -> TypeGuard[ResponseComputerToolCallParam]:
    return param["type"] == "computer_call"


def is_response_web_search_call(
    param: ResponseInputItemParam,
) -> TypeGuard[ResponseFunctionWebSearchParam]:
    return param["type"] == "web_search_call"


def is_response_function_tool_call(
    param: ResponseInputItemParam,
) -> TypeGuard[ResponseFunctionToolCallParam]:
    return param["type"] == "function_call"


def is_response_reasoning_item(
    param: ResponseInputItemParam,
) -> TypeGuard[ResponseReasoningItemParam]:
    return param["type"] == "reasoning"


def is_response_mcp_list_tools(
    param: ResponseInputItemParam,
) -> TypeGuard[McpListToolsParam]:
    return param["type"] == "mcp_list_tools"


def is_response_mcp_call(
    param: ResponseInputItemParam,
) -> TypeGuard[McpCallParam]:
    return param["type"] == "mcp_call"


def is_function_tool_param(tool_param: ToolParam) -> TypeGuard[FunctionToolParam]:
    return tool_param.get("type") == "function"


def is_web_search_tool_param(tool_param: ToolParam) -> TypeGuard[WebSearchToolParam]:
    return tool_param.get("type") in [
        "web_search_preview",
        "web_search_preview_2025_03_11",
    ]


def is_mcp_tool_param(tool_param: ToolParam) -> TypeGuard[Mcp]:
    return tool_param.get("type") == "mcp"


def is_computer_tool_param(tool_param: ToolParam) -> TypeGuard[ComputerToolParam]:
    return tool_param.get("type") == "computer_use_preview"
