import json
from functools import reduce
from typing import TYPE_CHECKING, Sequence, TypeAlias, TypedDict, TypeGuard, cast

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
    ResponseOutputItem,
    ResponseOutputMessage,
    ResponseOutputMessageParam,
    ResponseOutputRefusal,
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
    ToolChoice as ResponsesToolChoice,
)
from openai.types.responses.response_function_web_search_param import (
    ActionFind,
    ActionOpenPage,
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
from openai.types.responses.response_reasoning_item import Summary
from openai.types.responses.response_reasoning_item_param import Summary as SummaryParam
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
)
from openai.types.responses.tool_param import Mcp
from pydantic import JsonValue
from shortuuid import uuid

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
from inspect_ai._util.url import is_http_url
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ChatCompletionChoice, ModelUsage, StopReason
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._mcp._remote import is_mcp_server_tool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams

from ._providers._openai_computer_use import (
    computer_call_output,
    computer_parmaeters,
    maybe_computer_use_preview_tool,
    tool_call_from_openai_computer_tool_call,
)
from ._providers._openai_web_search import maybe_web_search_tool

if TYPE_CHECKING:
    from ._providers.openai import OpenAIAPI


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


def openai_responses_extra_body_fields() -> list[str]:
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


class _AssistantInternal(TypedDict):
    tool_message_ids: dict[str, str]


AssistantMessageParam: TypeAlias = (
    ResponseOutputMessageParam
    | ResponseComputerToolCallParam
    | ResponseFunctionWebSearchParam
    | ResponseReasoningItemParam
    | McpListToolsParam
    | McpCallParam
)


def messages_from_responses_input(
    input: str | list[ResponseInputItemParam],
    tools: list[ToolInfo],
    model_name: str | None = None,
) -> list[ChatMessage]:
    # enture input is a list
    if isinstance(input, str):
        input = [
            Message(
                type="message",
                role="user",
                content=[ResponseInputTextParam(type="input_text", text=input)],
            )
        ]

    messages: list[ChatMessage] = []
    function_calls_by_id: dict[str, str] = {}
    pending_assistant_message_params: list[ResponseInputItemParam] = []

    def collect_pending_assistant_message() -> None:
        if len(pending_assistant_message_params) > 0:
            content: list[Content] = []
            tool_calls: list[ToolCall] = []
            for param in pending_assistant_message_params:
                if is_response_output_message(param):
                    for output in param["content"]:
                        if is_response_output_text(output):
                            content.append(
                                ContentText(
                                    text=output["text"],
                                    internal={"id": param["id"]},
                                    citations=(
                                        [
                                            _to_inspect_citation(annotation)
                                            for annotation in output["annotations"]
                                        ]
                                        if output["annotations"]
                                        else None
                                    ),
                                )
                            )
                        elif is_response_output_refusal(output):
                            content.append(
                                ContentText(
                                    text=output["refusal"],
                                    refusal=True,
                                    internal={"id": param["id"]},
                                )
                            )

                elif is_response_function_tool_call(param):
                    function_calls_by_id[param["call_id"]] = param["name"]
                    tool_calls.append(
                        parse_tool_call(
                            id=param["call_id"],
                            function=param["name"],
                            arguments=param["arguments"],
                            tools=tools,
                        )
                    )
                elif is_response_computer_tool_call(param):
                    computer_tool_call = ResponseComputerToolCall.model_validate(param)
                    tool_calls.append(
                        tool_call_from_openai_computer_tool_call(computer_tool_call)
                    )
                elif is_response_reasoning_item(param):
                    content.append(
                        ContentReasoning(
                            reasoning="\n".join([s["text"] for s in param["summary"]]),
                            signature=param["id"],
                        )
                    )
                elif is_response_mcp_list_tools(param):
                    content.append(
                        ContentToolUse(
                            tool_type="mcp_list_tools",
                            id=param["id"],
                            name="mcp_list_tools",
                            context=param["server_label"],
                            arguments="",
                            result=cast(list[JsonValue], param["tools"]),
                            error=param.get("error", None),
                        )
                    )
                elif is_response_mcp_call(param):
                    content.append(
                        ContentToolUse(
                            tool_type="mcp_call",
                            id=param["id"],
                            name=param["name"],
                            context=param["server_label"],
                            arguments=param["arguments"],
                            result=param.get("output", None),
                            error=param.get("error", None),
                        )
                    )
                else:
                    raise RuntimeError(
                        f"Unexpected assitant message type: {param['type']}"
                    )
            messages.append(
                ChatMessageAssistant(
                    content=content, tool_calls=tool_calls, model=model_name
                )
            )

            pending_assistant_message_params.clear()

    for item in input:
        # accumulate assistant message params until we clear the assistnat message
        if is_assistant_message_param(item):
            pending_assistant_message_params.append(item)
            continue

        # see if we need to collect a pending assistant message
        collect_pending_assistant_message()

        if is_response_input_message(item):
            # normalize item content
            item_content: list[
                ResponseInputTextParam
                | ResponseInputImageParam
                | ResponseInputFileParam
            ] = (
                [ResponseInputTextParam(type="input_text", text=item["content"])]
                if isinstance(item["content"], str)
                else item["content"]
                if isinstance(item["content"], list)
                else cast(
                    list[
                        ResponseInputTextParam
                        | ResponseInputImageParam
                        | ResponseInputFileParam
                    ],
                    [item["content"]],
                )
            )

            # create inspect content
            content = [
                _content_from_response_input_content_param(c) for c in item_content
            ]
            if item["role"] == "user":
                messages.append(ChatMessageUser(content=content))
            elif item["role"] == "assistant":
                messages.append(ChatMessageAssistant(content=content))
            else:
                messages.append(ChatMessageSystem(content=content))
        elif is_function_call_output(item):
            messages.append(
                ChatMessageTool(
                    tool_call_id=item["call_id"],
                    function=function_calls_by_id.get(item["call_id"]),
                    content=[ContentText(text=item["output"])],
                )
            )
        elif is_computer_call_output(item):
            messages.append(
                ChatMessageTool(
                    tool_call_id=item["call_id"],
                    function=function_calls_by_id.get(item["call_id"]),
                    content=[ContentImage(image=item["output"]["image_url"])],
                )
            )
        else:
            # ImageGenerationCall
            # ResponseCodeInterpreterToolCallParam
            # McpApprovalRequest
            # McpApprovalResponse
            # ResponseCustomToolCallOutputParam
            # ResponseCustomToolCallParam
            # LocalShellCall
            # LocalShellCallOutput
            # ResponseFileSearchToolCallParam
            # ItemReference
            raise RuntimeError(
                f"Type {item['type']} is not supported by the agent bridge"
            )

        # final collect of pending assistant message
        collect_pending_assistant_message()

    return messages


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
        and "status" in param
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


def _content_from_response_input_content_param(
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


def tool_from_responses_tool(tool_param: ToolParam) -> ToolInfo:
    if is_function_tool_param(tool_param):
        return ToolInfo(
            name=tool_param["name"],
            description=tool_param["description"] or tool_param["name"],
            parameters=ToolParams.model_validate(tool_param["parameters"]),
        )
    elif is_web_search_tool_param(tool_param):
        return ToolInfo(
            name="web_search", description="web_search", options={"openai": True}
        )
    elif is_computer_tool_param(tool_param):
        return ToolInfo(
            name="computer",
            description="computer",
            # this is a fake parameter def so that we match the check for the
            # computer tool in maybe_computer_use_preview_tool (openai will
            # provide its own parmeters internally)
            parameters=ToolParams(properties={k: k for k in computer_parmaeters()}),  # type: ignore[misc]
        )
    elif is_mcp_tool_param(tool_param):
        allowed_tools = tool_param["allowed_tools"]
        if isinstance(allowed_tools, dict):
            raise RuntimeError(
                "McpAllowedToolsMcpAllowedToolsFilter not supported by agent bridge"
            )
        config = MCPServerConfigHTTP(
            type="sse" if "sse" in tool_param["server_url"] else "http",
            name=tool_param["server_label"],
            tools=allowed_tools if isinstance(allowed_tools, list) else "all",
            url=tool_param["server_url"],
            headers=tool_param["headers"],
        )
        return ToolInfo(
            name=f"mcp_server_{config.name}",
            description=f"mcp_server_{config.name}",
            options=config.model_dump(),
        )
    else:
        raise RuntimeError(f"ToolParam of type {tool_param.get('type')} not supported.")


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


def tool_choice_from_responses_tool_choice(
    tool_choice: ResponsesToolChoice | None,
) -> ToolChoice | None:
    inspect_tool_choice: ToolChoice | None = None
    if tool_choice is not None:
        if tool_choice == "auto":
            inspect_tool_choice = tool_choice
        elif tool_choice == "none":
            inspect_tool_choice = tool_choice
        elif tool_choice == "required":
            inspect_tool_choice = "any"
        elif is_tool_choice_function_param(tool_choice):
            inspect_tool_choice = ToolFunction(name=tool_choice["name"])
        elif is_tool_choice_mcp_param(tool_choice):
            if tool_choice["name"] is None:
                raise RuntimeError(
                    "MCP server tool choice requires 'name' field for agent bridge"
                )
            inspect_tool_choice = ToolFunction(name=tool_choice["name"])
        elif tool_choice.get("type") == "allowed_tools":
            raise RuntimeError("ToolChoiceAllowedParam not supported by agent bridge")
        elif tool_choice.get("type") == "custom":
            raise RuntimeError("ToolChoiceCustomParam not supported by agent bridge")
        elif "type" in tool_choice:
            inspect_tool_choice = ToolFunction(name=str(tool_choice.get("type")))

    return inspect_tool_choice


def is_tool_choice_function_param(
    tool_choice: ResponsesToolChoice,
) -> TypeGuard[ToolChoiceFunctionParam]:
    if not isinstance(tool_choice, str):
        return tool_choice.get("type") == "function"
    else:
        return False


def is_tool_choice_mcp_param(
    tool_choice: ResponsesToolChoice,
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
            case ResponseFunctionToolCall():
                stop_reason = "tool_calls"
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
                stop_reason = "tool_calls"
                if output.id is not None:
                    internal["tool_message_ids"][output.call_id] = output.id
                tool_calls.append(tool_call_from_openai_computer_tool_call(output))

            case ResponseFunctionWebSearch():
                message_content.append(
                    ContentToolUse(
                        tool_type="web_search_call",
                        id=output.id,
                        name=output.action.type,
                        arguments=output.action.model_dump(),
                        result="",
                        error="failed" if output.status == "failed" else None,
                    )
                )
            case McpListTools():
                message_content.append(
                    ContentToolUse(
                        tool_type="mcp_list_tools",
                        id=output.id,
                        name="mcp_list_tools",
                        context=output.server_label,
                        arguments="",
                        result=[tool.model_dump() for tool in output.tools],
                        error=output.error,
                    )
                )
            case McpCall():
                message_content.append(
                    ContentToolUse(
                        tool_type="mcp_call",
                        id=output.id,
                        name=output.name,
                        context=output.server_label,
                        arguments=output.arguments,
                        result=output.output,
                        error=output.error,
                    )
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
    content_items: list[ContentText | ContentReasoning | ContentToolUse] = (
        [ContentText(text=message.content)]
        if isinstance(message.content, str)
        else [
            c
            for c in message.content
            if isinstance(c, ContentText | ContentReasoning | ContentToolUse)
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
                        summary=[SummaryParam(type="summary_text", text=reasoning)]
                        if reasoning
                        else [],
                    )
                )
            case ContentToolUse(
                tool_type=tool_type,
                id=id,
                name=name,
                context=context,
                arguments=arguments,
                result=result,
                error=error,
            ):
                if tool_type == "mcp_list_tools":
                    items.append(
                        McpListToolsParam(
                            id=id,
                            server_label=context or "",
                            tools=cast(list[McpListToolsToolParam], result),
                            type="mcp_list_tools",
                            error=error,
                        )
                    )
                elif tool_type == "mcp_call":
                    items.append(
                        McpCallParam(
                            id=id,
                            arguments=str(arguments),
                            name=name,
                            server_label=context or "",
                            type="mcp_call",
                            output=str(result),
                            error=error,
                        )
                    )
                elif tool_type == "web_search_call":
                    match arguments:
                        case {"type": "search"}:
                            action: ActionSearch | ActionOpenPage | ActionFind = cast(
                                ActionSearch, arguments
                            )
                        case {"type": "open_page"}:
                            action = cast(ActionOpenPage, arguments)
                        case {"type": "find"}:
                            action = cast(ActionFind, arguments)
                        case _:
                            raise ValueError(
                                f"Unexpected arguments for web_search_call: {arguments}"
                            )

                    items.append(
                        ResponseFunctionWebSearchParam(
                            id=id,
                            action=action,
                            status="failed" if error else "completed",
                            type="web_search_call",
                        )
                    )
                else:
                    raise ValueError(
                        f"OpenAI Responses: Unspected tool_type '{tool_type}'"
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
            or maybe_mcp_tool(tool)
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


def responses_output_items_from_assistant_message(
    message: ChatMessageAssistant,
) -> list[ResponseOutputItem]:
    content = (
        [ContentText(text=message.content)]
        if isinstance(message.content, str)
        else message.content
    )

    return [_response_output_item_from_content(c) for c in content]


def _response_output_item_from_content(content: Content) -> ResponseOutputItem:
    if isinstance(content, ContentText):
        if isinstance(content.internal, dict) and "id" in content.internal:
            id = str(content.internal["id"])
        else:
            id = uuid()
        message_content = (
            ResponseOutputRefusal(type="refusal", refusal=content.text)
            if content.refusal
            else ResponseOutputText(
                type="output_text", annotations=[], text=content.text
            )
        )
        return ResponseOutputMessage(
            type="message",
            role="assistant",
            id=id,
            content=[message_content],
            status="completed",
        )
    elif isinstance(content, ContentReasoning):
        return ResponseReasoningItem(
            type="reasoning",
            summary=[Summary(type="summary_text", text=content.reasoning)],
            id=content.signature or "",
        )
    else:
        raise RuntimeError(f"Unsupported content type: {type(content)}")


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


def _to_inspect_citation(input: Annotation | AnnotationParam) -> Citation:
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
