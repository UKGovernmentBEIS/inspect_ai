import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import reduce
from typing import Any, Iterable, Protocol, Sequence, TypeGuard, cast

from openai.types.responses import (
    CompactedResponse,
    ComputerToolParam,
    CustomToolParam,
    EasyInputMessageParam,
    FunctionToolParam,
    ResponseCodeInterpreterToolCall,
    ResponseCodeInterpreterToolCallParam,
    ResponseCompactionItem,
    ResponseComputerToolCall,
    ResponseComputerToolCallParam,
    ResponseCustomToolCall,
    ResponseCustomToolCallOutputParam,
    ResponseCustomToolCallParam,
    ResponseFunctionCallOutputItemListParam,
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
    ResponseToolSearchCall,
    ResponseUsage,
    ToolChoiceFunctionParam,
    ToolChoiceMcpParam,
    ToolChoiceTypesParam,
    ToolParam,
    ToolSearchToolParam,
    WebSearchToolParam,
)
from openai.types.responses import Response as OpenAIResponse
from openai.types.responses.namespace_tool_param import NamespaceToolParam
from openai.types.responses.response import IncompleteDetails
from openai.types.responses.response_code_interpreter_tool_call import (
    OutputImage,
    OutputLogs,
)
from openai.types.responses.response_code_interpreter_tool_call_param import (
    OutputLogs as OutputLogsParam,
)
from openai.types.responses.response_compaction_item_param_param import (
    ResponseCompactionItemParamParam,
)
from openai.types.responses.response_create_params import (
    ToolChoice as ResponsesToolChoiceParam,
)
from openai.types.responses.response_custom_tool_call_output_param import (
    OutputOutputContentList,
)
from openai.types.responses.response_function_web_search_param import (
    Action,
)
from openai.types.responses.response_input_image_content_param import (
    ResponseInputImageContentParam,
)
from openai.types.responses.response_input_item_param import (
    ComputerCallOutput,
    FunctionCallOutput,
    Message,
    ToolSearchCall,
)
from openai.types.responses.response_input_item_param import McpCall as McpCallParam
from openai.types.responses.response_input_item_param import (
    McpListTools as McpListToolsParam,
)
from openai.types.responses.response_input_item_param import (
    McpListToolsTool as McpListToolsToolParam,
)
from openai.types.responses.response_input_text_content_param import (
    ResponseInputTextContentParam,
)
from openai.types.responses.response_output_item import (
    ImageGenerationCall,
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
from openai.types.responses.response_output_text import (
    Logprob as LogprobResponses,
)
from openai.types.responses.response_output_text_param import (
    Annotation as AnnotationParam,
)
from openai.types.responses.response_reasoning_item_param import Content as ContentParam
from openai.types.responses.response_reasoning_item_param import Summary as SummaryParam
from openai.types.responses.response_tool_search_output_item_param_param import (
    ResponseToolSearchOutputItemParamParam,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
)
from openai.types.responses.tool_param import (
    CodeInterpreter,
    CodeInterpreterContainerCodeInterpreterToolAuto,
    ImageGeneration,
    Mcp,
)
from pydantic import JsonValue, TypeAdapter, ValidationError

from inspect_ai._util.citation import Citation, DocumentCitation, UrlCitation
from inspect_ai._util.constants import NO_CONTENT
from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentData,
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
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._compaction.edit import (
    MCP_LIST_TOOLS_NAME,
    TOOL_RESULT_REMOVED,
    is_result_cleared,
)
from inspect_ai.model._generate_config import (
    GenerateConfig,
    image_output_config,
)
from inspect_ai.model._model_output import (
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    ModelUsage,
    StopReason,
    TopLogprob,
)
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._mcp._remote import is_mcp_server_tool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._json import json_schema_dump

from ._providers._openai_computer_use import (
    computer_call_output,
    maybe_computer_use_tool,
    tool_call_from_openai_computer_tool_call,
)
from ._providers._openai_web_search import maybe_web_search_tool

MESSAGE_ID = "message_id"
MESSAGE_PHASE = "message_phase"
REASONING_ENCRYPTED_CONTENT = "reasoning_encrypted_content"


class ResponsesModelInfo(Protocol):
    def has_reasoning_options(self) -> bool: ...
    def reasoning_only_fallback(self) -> bool: ...
    def is_latest(self) -> bool: ...
    def is_gpt(self) -> bool: ...
    def is_gpt_5(self) -> bool: ...
    def is_gpt_5_plus(self) -> bool: ...
    def is_gpt_5_pro(self) -> bool: ...
    def is_gpt_5_chat(self) -> bool: ...
    def is_o_series(self) -> bool: ...
    def is_o1(self) -> bool: ...
    def is_o3_mini(self) -> bool: ...
    def is_deep_research(self) -> bool: ...
    def is_codex(self) -> bool: ...


def _extract_compaction_from_content_data(
    content: str | list[Content],
) -> ResponseCompactionItemParamParam | None:
    """Extract compaction metadata from ContentData if present.

    Args:
        content: Message content (string or list of Content objects)

    Returns:
        ResponseCompactionItemParamParam if compaction metadata found, else None
    """
    if not isinstance(content, list):
        return None

    for item in content:
        if isinstance(item, ContentData) and isinstance(item.data, dict):
            metadata = item.data.get("compaction_metadata")
            if (
                metadata
                and isinstance(metadata, dict)
                and metadata.get("type") == "openai_compact"
            ):
                return ResponseCompactionItemParamParam(
                    type="compaction",
                    id=str(metadata.get("id")) if metadata.get("id") else None,
                    encrypted_content=str(metadata["encrypted_content"]),
                )
    return None


async def openai_responses_inputs(
    messages: list[ChatMessage],
    model_info: ResponsesModelInfo | None = None,
    synthesize_phase: bool = False,
    swap_todo_write: bool = False,
) -> list[ResponseInputItemParam]:
    return [
        item
        for message in messages
        for item in await _openai_input_item_from_chat_message(
            message, model_info, synthesize_phase, swap_todo_write
        )
    ]


async def _openai_input_item_from_chat_message(
    message: ChatMessage,
    model_info: ResponsesModelInfo | None = None,
    synthesize_phase: bool = False,
    swap_todo_write: bool = False,
) -> list[ResponseInputItemParam]:
    if message.role == "system":
        content = await _openai_responses_content_list_param(message.content)
        return [Message(type="message", role="developer", content=content)]
    elif message.role == "user":
        # Check if this is a compaction marker message
        compaction_param = _extract_compaction_from_content_data(message.content)
        if compaction_param:
            # This is a compaction marker - return compaction item
            return [compaction_param]

        # Regular user message handling
        return [
            Message(
                type="message",
                role="user",
                content=await _openai_responses_content_list_param(message.content),
            )
        ]
    elif message.role == "assistant":
        return _openai_input_items_from_chat_message_assistant(
            message, model_info, synthesize_phase, swap_todo_write
        )
    elif message.role == "tool":
        # recover the original call (by call_id) to replay the matching output item
        responses_tool_call = assistant_internal().tool_calls.get(
            message.tool_call_id or str(message.function)
        )
        if (
            responses_tool_call is not None
            and responses_tool_call["type"] == "tool_search_call"
        ):
            # client-resolved tool_search: replay the discovered tools (carried as
            # JSON in the tool message content) as a native tool_search_output item
            return [_tool_search_output_param_from_tool_message(message)]
        elif (
            responses_tool_call is not None
            and responses_tool_call["type"] == "computer_call"
        ):
            return [
                computer_call_output(
                    message,
                    responses_tool_call["call_id"],
                    responses_tool_call.get("pending_safety_checks"),
                )
            ]
        elif (
            responses_tool_call is not None
            and responses_tool_call["type"] == "custom_tool_call"
        ):
            return [
                ResponseCustomToolCallOutputParam(
                    type="custom_tool_call_output",
                    call_id=message.tool_call_id or str(message.function),
                    output=message.error.message
                    if message.error is not None
                    else await _openai_responses_custom_tool_call_output(message),
                )
            ]
        else:
            return [
                FunctionCallOutput(
                    type="function_call_output",
                    call_id=message.tool_call_id or str(message.function),
                    output=message.error.message
                    if message.error is not None
                    else await _openai_responses_function_call_output(message),
                )
            ]

    else:
        raise ValueError(f"Unexpected message role '{message.role}'")


def _tool_search_output_param_from_tool_message(
    message: ChatMessageTool,
) -> ResponseToolSearchOutputItemParamParam:
    # tools were carried as JSON in the tool message content; parse them back
    content = message.content
    tools_json = (
        content
        if isinstance(content, str)
        else "".join(c.text for c in content if isinstance(c, ContentText))
    )
    try:
        validated = tool_search_tools_adapter.validate_json(tools_json)
        # validate_json yields lazy `ValidatorIterator`s for namespace tools
        # (NamespaceToolParam.tools is typed `Iterable`). Such an iterator is
        # single-consumption: inspect serializes the request for the transcript
        # before the OpenAI client serializes it for the wire, so the iterator is
        # exhausted on the first pass and the wire body carries an empty `tools`
        # array (OpenAI then rejects it as "empty array"). dump_python
        # materializes the iterators into plain lists that survive re-serialization.
        tools = tool_search_tools_adapter.dump_python(validated, mode="json")
    except (ValidationError, ValueError):
        # e.g. content cleared by compaction; fall back to an empty tool list
        tools = []
    return ResponseToolSearchOutputItemParamParam(
        type="tool_search_output",
        call_id=message.tool_call_id or str(message.function),
        tools=tools,
        execution="client",
        status="completed",
    )


async def _openai_responses_function_call_output(
    message: ChatMessageTool,
) -> str | ResponseFunctionCallOutputItemListParam:
    if isinstance(message.content, str):
        return message.content
    else:
        outputs: ResponseFunctionCallOutputItemListParam = []
        for c in message.content:
            if isinstance(c, ContentText):
                outputs.append(
                    ResponseInputTextContentParam(type="input_text", text=c.text)
                )
            elif isinstance(c, ContentImage):
                outputs.append(
                    ResponseInputImageContentParam(
                        type="input_image",
                        detail=c.detail,
                        image_url=(
                            c.image
                            if is_http_url(c.image)
                            else await file_as_data_uri(c.image)
                        ),
                    )
                )
        return outputs


async def _openai_responses_custom_tool_call_output(
    message: ChatMessageTool,
) -> str | Iterable[OutputOutputContentList]:
    if isinstance(message.content, str):
        return message.content
    else:
        outputs: list[OutputOutputContentList] = []
        for c in message.content:
            if isinstance(c, ContentText):
                outputs.append(ResponseInputTextParam(type="input_text", text=c.text))
            elif isinstance(c, ContentImage):
                outputs.append(
                    ResponseInputImageParam(
                        type="input_image",
                        detail=c.detail,
                        image_url=(
                            c.image
                            if is_http_url(c.image)
                            else await file_as_data_uri(c.image)
                        ),
                    )
                )
        return outputs


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
        "prompt_cache_retention",
        "safety_identifier",
        "truncation",
        "store",
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
                ToolChoiceTypesParam(type="computer")
                if tool_choice.name == "computer"
                and any(tool["type"] == "computer" for tool in tools)
                else ToolChoiceTypesParam(type="web_search_preview")
                if tool_choice.name == "web_search"
                and any(tool["type"] == "web_search" for tool in tools)
                else ToolChoiceFunctionParam(
                    type="function",
                    name=_responses_tool_choice_name(tool_choice.name, tools),
                )
            )


def openai_responses_tools(
    tools: list[ToolInfo],
    model_name: str,
    config: GenerateConfig,
    is_latest: bool = False,
) -> list[ToolParam]:
    result = [
        _tool_param_for_tool_info(tool, model_name, config, is_latest) for tool in tools
    ]

    # Add at most one image_generation tool if image output modality requested
    img_config = image_output_config(config.modalities)
    if img_config is not None:
        tool_def = ImageGeneration(type="image_generation")
        if img_config.options:
            for key, value in img_config.options.get("openai", {}).items():
                tool_def[key] = value  # type: ignore[literal-required]
        result.append(tool_def)

    return result


def openai_responses_chat_choices(
    model: str | None, response: OpenAIResponse, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    model = model or response.model
    message, stop_reason, logprobs = _chat_message_assistant_from_openai_response(
        model, response, tools
    )
    return [
        ChatCompletionChoice(
            message=message, stop_reason=stop_reason, logprobs=logprobs
        )
    ]


def is_native_tool_configured(
    tools: Sequence[ToolInfo],
    model_name: str,
    config: GenerateConfig,
    is_latest: bool = False,
) -> bool:
    return any(
        _maybe_native_tool_param(tool, model_name, config, is_latest) is not None
        for tool in tools
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
        str,
        ResponseFunctionToolCallParam
        | ResponseCustomToolCallParam
        | ResponseComputerToolCallParam
        | ResponseFunctionWebSearchParam
        | ResponseCodeInterpreterToolCallParam
        | ToolSearchCall,
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
        return ContentImage(
            image=input.get("image_url", "") or "", detail=input.get("detail", "auto")
        )
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


def _process_response_output_items(
    outputs: Iterable[Any],
    tools: list[ToolInfo],
) -> tuple[list[Content], list[ToolCall], Logprobs | None, bool]:
    """Process response output items into content, tool calls, and logprobs.

    This helper extracts the core logic for processing OpenAI response output items,
    making it reusable for both regular Response and CompactedResponse.

    Args:
        outputs: Iterable of response output items (ResponseOutputMessage,
            ResponseReasoningItem, ResponseFunctionToolCall, etc.)
        tools: List of available tools for parsing tool calls.

    Returns:
        A tuple of (message_content, tool_calls, logprobs, has_tool_calls) where:
        - message_content: List of Content items extracted from output
        - tool_calls: List of ToolCall items extracted from output
        - logprobs: Logprobs if available, None otherwise
        - has_tool_calls: True if any tool calls were found
    """
    logprobs: Logprobs | None = None
    message_content: list[Content] = []
    tool_calls: list[ToolCall] = []
    has_tool_calls = False

    for output in outputs:
        match output:
            case ResponseOutputMessage(content=content, id=id):
                # extract phase if present (extra field from API)
                phase: str | None = getattr(output, "phase", None)

                # find logprobs in content if available
                logprobs_content = next(
                    (
                        c
                        for c in content
                        if isinstance(c, ResponseOutputText) and c.logprobs is not None
                    ),
                    None,
                )
                if logprobs_content is not None:
                    logprobs = _logprobs_from_responses_logprobs(
                        logprobs_content.logprobs
                    )

                internal: dict[str, JsonValue] = {MESSAGE_ID: id}
                if phase is not None:
                    internal[MESSAGE_PHASE] = phase

                message_content.extend(
                    [
                        ContentText(
                            text=c.text,
                            internal=dict(internal),
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
                            text=c.refusal, refusal=True, internal=dict(internal)
                        )
                        for c in content
                    ]
                )
            case ResponseReasoningItem():
                message_content.append(reasoning_from_responses_reasoning(output))

            case ResponseFunctionToolCall():
                has_tool_calls = True
                if output.id is not None:
                    assistant_internal().tool_calls[output.call_id] = cast(
                        ResponseFunctionToolCallParam,
                        output.model_dump(exclude_none=True),
                    )

                call_name, call_arguments = _responses_call_to_inspect(
                    output.name, output.arguments, tools
                )
                tool_calls.append(
                    parse_tool_call(
                        output.call_id,
                        call_name,
                        call_arguments,
                        tools,
                    )
                )
            case ResponseCustomToolCall():
                has_tool_calls = True
                if output.id is not None:
                    assistant_internal().tool_calls[output.call_id] = cast(
                        ResponseCustomToolCallParam,
                        output.model_dump(exclude_none=True),
                    )
                tool_call = ToolCall(
                    id=output.call_id,
                    function=output.name,
                    arguments={"input": output.input},
                    type="custom",
                )
                tool_calls.append(tool_call)

            case ResponseComputerToolCall():
                has_tool_calls = True
                if output.id is not None:
                    assistant_internal().tool_calls[output.call_id] = cast(
                        ResponseComputerToolCallParam,
                        output.model_dump(exclude_none=True),
                    )

                if output.pending_safety_checks:
                    from inspect_ai.log._transcript import transcript

                    for check in output.pending_safety_checks:
                        transcript().info(
                            f"Safety check acknowledged: {check.code or 'unknown code'} - {check.message or 'unknown message'}"
                        )

                tool_calls.append(tool_call_from_openai_computer_tool_call(output))

            case ResponseFunctionWebSearch():
                # Use warnings=False to suppress Pydantic serialization warnings for
                # action types the SDK may not yet support.
                # See: https://github.com/pydantic/pydantic-ai/issues/3653
                assistant_internal().server_tool_uses[output.id] = cast(
                    ResponseFunctionWebSearchParam,
                    output.model_dump(exclude_none=True, warnings=False),
                )
                message_content.append(web_search_to_tool_use(output))
            case ResponseCodeInterpreterToolCall():
                message_content.append(code_interpreter_to_tool_use(output))
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
            case ResponseCompactionItem():
                # Skip compaction items - handled separately by caller
                pass
            case ImageGenerationCall():
                if output.status == "completed" and output.result is not None:
                    data_uri = f"data:image/png;base64,{output.result}"
                    message_content.append(ContentImage(image=data_uri))
            case ResponseToolSearchCall():
                # client-resolved built-in tool (like computer): represent as a
                # standard ToolCall the scaffold will resolve. Cache the raw param
                # (keyed by call_id) for verbatim replay within the sample.
                has_tool_calls = True
                tool_call = tool_call_from_openai_tool_search_call(output)
                assistant_internal().tool_calls[tool_call.id] = cast(
                    ToolSearchCall, output.model_dump(exclude_none=True)
                )
                tool_calls.append(tool_call)
            case _:
                raise ValueError(f"Unexpected output type: {output.__class__}")

    return message_content, tool_calls, logprobs, has_tool_calls


def _chat_message_assistant_from_openai_response(
    model: str, response: OpenAIResponse, tools: list[ToolInfo]
) -> tuple[ChatMessageAssistant, StopReason, Logprobs | None]:
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

    # process output items
    message_content, tool_calls, logprobs, has_tool_calls = (
        _process_response_output_items(response.output, tools)
    )

    if has_tool_calls:
        stop_reason = "tool_calls"

    return (
        ChatMessageAssistant(
            content=message_content,
            tool_calls=tool_calls if len(tool_calls) > 0 else None,
            model=model,
            source="generate",
        ),
        stop_reason,
        logprobs,
    )


def _logprobs_from_responses_logprobs(
    logprobs: list[LogprobResponses] | None,
) -> Logprobs | None:
    if logprobs is not None and len(logprobs) > 0:
        return Logprobs(
            content=[
                Logprob(
                    token=lp.token,
                    logprob=lp.logprob,
                    bytes=lp.bytes,
                    top_logprobs=[
                        TopLogprob(
                            token=tlp.token, logprob=tlp.logprob, bytes=tlp.bytes
                        )
                        for tlp in lp.top_logprobs
                    ],
                )
                for lp in logprobs
            ]
        )
    else:
        return None


def reasoning_from_responses_reasoning(
    item: ResponseReasoningItem | ResponseReasoningItemParam,
) -> ContentReasoning:
    if not isinstance(item, ResponseReasoningItem):
        item = read_reasoning_item_param(item)

    if item.content:
        readable = "\n".join([s.text for s in item.content])
    else:
        readable = None

    if item.summary:
        summary_text: str | None = "\n\n".join([s.text for s in item.summary])
    else:
        summary_text = None

    if (
        readable is not None
        and item.encrypted_content is not None
        and summary_text is None
    ):
        return ContentReasoning(
            reasoning=item.encrypted_content,
            summary=readable,
            signature=item.id,
            redacted=True,
        )
    reasoning = readable if readable is not None else (item.encrypted_content or "")
    # When content, encrypted_content, and summary all exist, stash the
    # encrypted blob in `internal` so it survives a round-trip back to a
    # ResponseReasoningItem for replay.
    internal: dict[str, JsonValue] | None = None
    if (
        readable is not None
        and summary_text is not None
        and item.encrypted_content is not None
    ):
        internal = {REASONING_ENCRYPTED_CONTENT: item.encrypted_content}
    return ContentReasoning(
        reasoning=reasoning,
        summary=summary_text,
        signature=item.id,
        redacted=readable is None and item.encrypted_content is not None,
        internal=internal,
    )


# two issues addressed here:
#   - ResponseReasoningItem requires an 'id' but OpenAI doesn't return an 'id' when store=False
#   - Some clients (e.g. codex cli) do not provide the id even when it has been passed back to them (this is likely b/c they know they are passing store=False)
def read_reasoning_item_param(
    param: ResponseReasoningItemParam,
) -> ResponseReasoningItem:
    no_id = param.get("id", None) is None
    if no_id:
        param = param.copy()
        param["id"] = "dummy-id"
    item = ResponseReasoningItem.model_validate(param)
    if no_id:
        item.id = None  # type: ignore[assignment]
    return item


def responses_reasoning_from_reasoning(
    content: ContentReasoning,
) -> ResponseReasoningItemParam:
    encrypted_content: str | None = content.reasoning if content.redacted else None

    # If non-redacted, look for an encrypted blob stashed in `internal`
    # (set when OpenAI returned content + encrypted_content + summary together).
    if not content.redacted and isinstance(content.internal, dict):
        stashed = content.internal.get(REASONING_ENCRYPTED_CONTENT)
        if isinstance(stashed, str):
            encrypted_content = stashed

    content_params: list[ContentParam] = []
    if not content.redacted and content.reasoning:
        content_params.append(
            ContentParam(type="reasoning_text", text=content.reasoning)
        )

    summary_params: list[SummaryParam] = []
    if not content.redacted and content.summary:
        summary_params.append(SummaryParam(type="summary_text", text=content.summary))

    return ResponseReasoningItemParam(
        type="reasoning",
        # OpenAI returns 'None' when store=False even though the schema requires the id
        id=content.signature,  # type: ignore[typeddict-item]
        content=content_params,
        summary=summary_params,
        encrypted_content=encrypted_content,
    )


mcp_tool_adapter = TypeAdapter(list[McpListToolsToolParam])


def tool_call_from_openai_tool_search_call(output: ResponseToolSearchCall) -> ToolCall:
    # arguments may arrive as a dict (typed `object`) or a JSON string
    arguments = output.arguments
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {"query": arguments}
    return ToolCall(
        id=output.call_id or output.id,
        function=TOOL_SEARCH_NAME,
        arguments=arguments,
    )


def web_search_to_tool_use(output: ResponseFunctionWebSearch) -> ContentToolUse:
    if output.action is None:
        # Preserve web_search_call items that omit action.
        action_name = "search"
        action_arguments = to_json_str_safe({"type": "search", "query": ""})
    else:
        action_name = output.action.type
        action_arguments = output.action.to_json(exclude_none=True)

    return ContentToolUse(
        tool_type="web_search",
        id=output.id,
        name=action_name,
        arguments=action_arguments,
        result="",
        error="failed" if output.status == "failed" else None,
    )


def mcp_list_tools_to_tool_use(output: McpListTools) -> ContentToolUse:
    return ContentToolUse(
        tool_type="mcp_call",
        id=output.id,
        name=MCP_LIST_TOOLS_NAME,
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
    # Handle cleared results gracefully
    if content.result == TOOL_RESULT_REMOVED:
        tools: list[McpListToolsToolParam] = []
    else:
        try:
            tools = mcp_tool_adapter.validate_json(content.result)
        except ValidationError:
            tools = []

    return McpListToolsParam(
        type="mcp_list_tools",
        id=content.id,
        server_label=content.context or "",
        tools=tools,
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


def _is_valid_openai_web_search_action(action: dict[str, Any]) -> bool:
    """Check if a dict represents a valid OpenAI web search action.

    Validates both the type field and the required fields for each action type.
    This ensures we don't accidentally pass through malformed actions or actions
    from other providers that happen to have a 'type' field.
    """
    action_type = action.get("type")

    if action_type == "search":
        # ActionSearch requires 'query' (deprecated) or 'queries'
        return "query" in action or "queries" in action
    elif action_type == "open_page":
        # ActionOpenPage requires 'url'
        return "url" in action
    elif action_type in ("find", "find_in_page"):
        # ActionFind / ActionFindInPage require 'pattern' and 'url'
        return "pattern" in action or "url" in action

    return False


def parse_web_search_action(arguments: str) -> dict[str, Any]:
    """Parse web search action from JSON arguments.

    Parses action as raw dict and filters None values to avoid Pydantic validation
    issues with action types the SDK may not yet support.
    See: https://github.com/pydantic/pydantic-ai/issues/3653

    If the parsed dict doesn't represent a valid OpenAI action, creates a conforming
    search action. This handles web search results from other providers (e.g., Anthropic)
    that have different formats.

    Returns a dict that can be cast to the appropriate Action type by the caller.
    """
    try:
        action_dict = json.loads(arguments)
        filtered = {k: v for k, v in action_dict.items() if v is not None}

        # Check if this is a valid OpenAI action (correct type + required fields)
        if _is_valid_openai_web_search_action(filtered):
            # Newer search responses omit the deprecated singular `query`
            # and only populate `queries`. The SDK still declares `query`
            # as required, so backfill from `queries[0]` to keep strict
            # construction (e.g. `ResponseFunctionWebSearch(...)`) happy.
            # `queries` is preserved alongside so no parallel-search data
            # is lost.
            if filtered.get("type") == "search" and "query" not in filtered:
                queries = filtered.get("queries") or []
                filtered["query"] = queries[0] if queries else ""
            return filtered

        # Not an OpenAI-formatted action - create a conforming search action
        # This handles web search from other providers (e.g., Anthropic)
        query = filtered.get("query", arguments)
        return {"type": "search", "query": query}
    except (json.JSONDecodeError, TypeError):
        return {"type": "search", "query": arguments}


def tool_use_to_web_search_param(
    content: ContentToolUse,
) -> ResponseFunctionWebSearchParam:
    return ResponseFunctionWebSearchParam(
        type="web_search_call",
        id=content.id,
        action=cast(Action, parse_web_search_action(content.arguments)),
        status="failed" if content.error else "completed",
    )


def _openai_input_items_from_chat_message_assistant(
    message: ChatMessageAssistant,
    model_info: ResponsesModelInfo | None = None,
    synthesize_phase: bool = False,
    swap_todo_write: bool = False,
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
    content_items: list[
        ContentText | ContentReasoning | ContentToolUse | ContentImage
    ] = (
        [ContentText(text=message.content)]
        if isinstance(message.content, str)
        else [
            c
            for c in message.content
            if isinstance(
                c, ContentText | ContentReasoning | ContentToolUse | ContentImage
            )
        ]
    )

    # If all content is reasoning-only (no text, no tool calls), inject a
    # NO_CONTENT fallback to prevent the Responses API from rejecting the
    # next request. This matches the pattern used by other providers
    # (Anthropic, Google, Mistral, Bedrock) for empty assistant content.
    if (
        model_info is not None
        and model_info.reasoning_only_fallback()
        and content_items
        and all(isinstance(c, ContentReasoning) for c in content_items)
        and len(message.tool_calls or []) == 0
    ):
        content_items.append(ContentText(text=NO_CONTENT))

    # items to return
    items: list[ResponseInputItemParam] = []
    pending_response_output_id: str | None = None
    pending_response_phase: str | None = None
    pending_response_output: list[
        ResponseOutputRefusalParam | ResponseOutputTextParam
    ] = []

    synthetic_phase = (
        _synthetic_phase_for_assistant_message(message, content_items)
        if synthesize_phase
        else None
    )

    def flush_pending_context_text() -> None:
        nonlocal pending_response_output_id, pending_response_phase
        if len(pending_response_output) > 0:
            msg_param = ResponseOutputMessageParam(
                type="message",
                role="assistant",
                # this actually can be `None`, and it will in fact be `None` when the
                # assistant message is synthesized by the scaffold as opposed to being
                # replayed from the model
                # Is it okay to dynamically generate this here? We need this in
                # order to read this back into the equivalent BaseModel for the bridge
                id=pending_response_output_id,  # type: ignore[typeddict-item]
                content=pending_response_output.copy(),
                status="completed",
            )
            if pending_response_phase is not None:
                msg_param["phase"] = pending_response_phase  # type: ignore[typeddict-item]
            items.append(msg_param)
        pending_response_output_id = None
        pending_response_phase = None
        pending_response_output.clear()

    for content in content_items:
        # flush if we aren't ContentText
        if not isinstance(content, ContentText):
            flush_pending_context_text()

        match content:
            case ContentImage():
                # Replay generated images as user input_image messages
                # (replaying as image_generation_call requires store=true)
                items.append(
                    cast(
                        ResponseInputItemParam,
                        {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_image",
                                    "image_url": content.image,
                                    "detail": content.detail,
                                }
                            ],
                        },
                    )
                )
            case ContentReasoning():
                items.append(responses_reasoning_from_reasoning(content))
            case ContentToolUse(
                id=id,
                tool_type=tool_type,
            ):
                # Check if result was cleared during compaction
                result_cleared = is_result_cleared(content)

                # Try to use cached blocks, modifying them if result was cleared
                if id in assistant_internal().server_tool_uses:
                    cached_item = assistant_internal().server_tool_uses[id]
                    if result_cleared:
                        # Modify cached item in place based on type
                        cached_dict = dict(cast(dict[str, Any], cached_item))
                        if cached_dict.get("type") == "mcp_call":
                            cached_dict["output"] = TOOL_RESULT_REMOVED
                        # mcp_list_tools provides tool context, not cleared
                        # web_search doesn't have result in cached item
                        items.append(cast(ResponseInputItemParam, cached_dict))
                    else:
                        items.append(cached_item)
                elif tool_type == "mcp_call":
                    if content.name == MCP_LIST_TOOLS_NAME:
                        items.append(tool_use_to_mcp_list_tools_param(content))
                    else:
                        items.append(tool_use_to_mcp_call_param(content))
                elif tool_type == "web_search":
                    items.append(tool_use_to_web_search_param(content))
                elif tool_type == "code_execution":
                    # openai raises an error if we try to replay code_interpreter
                    # message params when store=False so we just do it as text
                    pending_response_output.append(
                        ResponseOutputTextParam(
                            type="output_text",
                            text=f"code_interpreter: {content.arguments}\n\n{content.error or content.result}",
                            annotations=[],
                            logprobs=[],
                        )
                    )
                else:
                    raise ValueError(
                        f"OpenAI Responses: Unspected tool_type '{tool_type}'"
                    )
            case ContentText(text=text, refusal=refusal):
                # see if we have a message id and phase
                message_id: str | None = None
                message_phase: str | None = None
                if isinstance(content.internal, dict):
                    if MESSAGE_ID in content.internal:
                        id_value = content.internal[MESSAGE_ID]
                        message_id = id_value if isinstance(id_value, str) else None
                    if MESSAGE_PHASE in content.internal:
                        phase_value = content.internal[MESSAGE_PHASE]
                        message_phase = (
                            phase_value if isinstance(phase_value, str) else None
                        )
                if message_phase is None:
                    message_phase = synthetic_phase

                # see if we need to flush d
                if (
                    message_id != pending_response_output_id
                    or message_phase != pending_response_phase
                ):
                    flush_pending_context_text()

                # register pending output
                pending_response_output_id = message_id
                pending_response_phase = message_phase
                pending_response_output.append(
                    ResponseOutputRefusalParam(type="refusal", refusal=text)
                    if refusal
                    else ResponseOutputTextParam(
                        type="output_text", text=text, annotations=[], logprobs=[]
                    )
                )

    # final flush if necessary
    flush_pending_context_text()

    return items + _tool_call_items_from_assistant_message(message, swap_todo_write)


def _synthetic_phase_for_assistant_message(
    message: ChatMessageAssistant,
    content_items: list[ContentText | ContentReasoning | ContentToolUse | ContentImage],
) -> str:
    # OpenAI recommends preserving `phase` when replaying Responses API
    # assistant messages; see:
    # https://developers.openai.com/api/docs/guides/reasoning#phase-parameter
    # https://developers.openai.com/api/reference/responses
    #
    # Inspect always preserves OpenAI-returned MESSAGE_PHASE metadata. This
    # helper is intentionally opt-in (`responses_phase=True`) because the docs
    # are explicit about preservation but less explicit about client synthesis
    # for arbitrary histories constructed outside the OpenAI Responses API.
    has_tool_activity = bool(message.tool_calls) or any(
        isinstance(content, ContentToolUse) for content in content_items
    )
    return "commentary" if has_tool_activity else "final_answer"


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


# tool_search is a native Responses tool used by scaffolds (e.g. codex-cli) to do
# client-side tool discovery. It is represented in inspect as a built-in tool the
# scaffold resolves (like `computer`): the model emits a `tool_search_call`, the
# scaffold returns a `tool_search_output` carrying the discovered tool defs.
TOOL_SEARCH_NAME = "tool_search"
TOOL_SEARCH_OUTPUT_NAME = "tool_search_output"
# options-bag marker so we can recognize the synthesized tool_search ToolInfo
TOOL_SEARCH_OPTIONS_MARKER = "tool_search"

tool_search_tools_adapter = TypeAdapter(list[ToolParam])


def is_tool_search_server_tool(tool: ToolInfo) -> bool:
    return (
        tool.name == TOOL_SEARCH_NAME
        and tool.options is not None
        and tool.options.get(TOOL_SEARCH_OPTIONS_MARKER) is True
    )


def maybe_tool_search_tool(tool: ToolInfo) -> ToolSearchToolParam | None:
    if is_tool_search_server_tool(tool):
        options = tool.options or {}
        param: ToolSearchToolParam = {"type": "tool_search"}
        description = options.get("description")
        if description is not None:
            param["description"] = description
        execution = options.get("execution")
        if execution is not None:
            param["execution"] = execution
        parameters = options.get("parameters")
        if parameters is not None:
            param["parameters"] = parameters
        return param
    else:
        return None


def _maybe_native_tool_param(
    tool: ToolInfo,
    model_name: str,
    config: GenerateConfig,
    is_latest: bool = False,
) -> ToolParam | None:
    return (
        (
            maybe_computer_use_tool(model_name, tool, is_latest)
            or maybe_web_search_tool(model_name, tool)
            or maybe_mcp_tool(tool)
            or maybe_code_interpreter_tool(model_name, tool)
            or maybe_tool_search_tool(tool)
            # or self.text_editor_tool_param(tool)
            # or self.bash_tool_param(tool)
        )
        if config.internal_tools is not False
        else None
    )


def _tool_call_items_from_assistant_message(
    message: ChatMessageAssistant,
    swap_todo_write: bool = False,
) -> list[ResponseInputItemParam]:
    tool_calls: list[ResponseInputItemParam] = []

    # now standard tool calls
    for call in message.tool_calls or []:
        # see if we have it in assistant_internal (computer/custom/tool_search are
        # cached at parse time, and the bridge seeds tool_search calls on replay)
        assistant_internal_call = assistant_internal().tool_calls.get(call.id, None)
        if assistant_internal_call is not None:
            tool_calls.append(assistant_internal_call)
        else:
            # create param (rendering todo_write -> update_plan when swapping, else
            # the name-only alias)
            if swap_todo_write and call.function == TODO_WRITE_NAME:
                name = UPDATE_PLAN_NAME
                arguments = json.dumps(_update_plan_args_from_inspect(call.arguments))
            else:
                name = _responses_tool_alias(call.function)
                arguments = json.dumps(call.arguments)
            tool_call_param: ResponseFunctionToolCallParam = dict(
                type="function_call",
                call_id=call.id,
                name=name,
                arguments=arguments,
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
    is_latest: bool = False,
) -> ToolParam:
    # Use a native tool implementation when available.
    tool_param = _maybe_native_tool_param(tool, model_name, config, is_latest)
    if tool_param is not None:
        return tool_param

    if tool.options is not None and "custom_format" in tool.options:
        return CustomToolParam(
            type="custom",
            name=tool.name,
            description=tool.description,
            format=tool.options["custom_format"],
        )
    else:
        return FunctionToolParam(
            type="function",
            name=_responses_tool_alias(tool.name),
            description=tool.description,
            parameters=json_schema_dump(tool.parameters),
            strict=False,  # default parameters don't work in strict mode
        )


# these functions enables us to 'escape' built in tool names like 'python'

_responses_tool_aliases = {"python": "python_exec"}


def _responses_tool_alias(name: str) -> str:
    return _responses_tool_aliases.get(name, name)


def _from_responses_tool_alias(name: str) -> str:
    return next((k for k, v in _responses_tool_aliases.items() if v == name), name)


# Present inspect's canonical `todo_write` planning tool to the Responses API under the
# name and schema that GPT-5 / Codex / o-series models are post-trained on: OpenAI's
# `update_plan`. We do this by substituting the first-party `update_plan()` tool's
# definition on the wire (reusing its native plan/step schema and description), then mapping
# calls back to `todo_write` on the way out — `todo_write` remains the tool that is actually
# registered, executed, and recorded in the transcript. The arg field names differ
# (`todos`<->`plan`, per-step `content`<->`step`; `status`/`explanation` pass through), so
# we also remap arguments. This mirrors how the Anthropic provider renders `text_editor` as
# Claude's native `str_replace_editor`.

TODO_WRITE_NAME = "todo_write"
UPDATE_PLAN_NAME = "update_plan"

_update_plan_tool_info_cache: ToolInfo | None = None


def _update_plan_tool_info() -> ToolInfo:
    """ToolInfo for the first-party update_plan() tool (built once)."""
    global _update_plan_tool_info_cache
    if _update_plan_tool_info_cache is None:
        from inspect_ai.tool._tool_def import ToolDef
        from inspect_ai.tool._tools._update_plan import update_plan

        td = ToolDef(update_plan())
        _update_plan_tool_info_cache = ToolInfo(
            name=td.name, description=td.description, parameters=td.parameters
        )
    return _update_plan_tool_info_cache


# JSON Schema keywords whose values map arbitrary *names* (e.g. parameter names) to
# subschemas. Names under these must be preserved verbatim during description stripping —
# a key named "description" here is a parameter, not schema metadata.
_SCHEMA_NAME_MAPS = ("properties", "$defs", "definitions")


def _schema_without_descriptions(value: Any) -> Any:
    """Recursively drop schema-metadata `description` so comparison ignores prose-only diffs.

    Crucially, this only strips `description` as schema metadata — not a parameter literally
    named `description` inside a `properties`/`$defs` map, whose keys are preserved verbatim.
    """
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for k, v in value.items():
            if k == "description":
                continue  # schema metadata
            if k in _SCHEMA_NAME_MAPS and isinstance(v, dict):
                # map of name -> subschema: keep every name, strip within each subschema
                result[k] = {
                    name: _schema_without_descriptions(subschema)
                    for name, subschema in v.items()
                }
            else:
                result[k] = _schema_without_descriptions(v)
        return result
    if isinstance(value, list):
        return [_schema_without_descriptions(v) for v in value]
    return value


_canonical_todo_write_schema_cache: Any = None


def _canonical_todo_write_schema() -> Any:
    """The canonical todo_write() parameter schema, descriptions stripped (built once)."""
    global _canonical_todo_write_schema_cache
    if _canonical_todo_write_schema_cache is None:
        from inspect_ai.tool._tool_def import ToolDef
        from inspect_ai.tool._tools._todo_write import todo_write

        td = ToolDef(todo_write())
        _canonical_todo_write_schema_cache = _schema_without_descriptions(
            json_schema_dump(td.parameters)
        )
    return _canonical_todo_write_schema_cache


def _is_canonical_todo_write(tool: ToolInfo) -> bool:
    """Whether `tool` is inspect's planning todo_write (not just a tool sharing the name).

    Guards the update_plan swap against a user-defined or bridged tool that merely reuses
    the `todo_write` name with a different (or superset) schema — such a tool must NOT be
    silently advertised/parsed as update_plan and have its schema dropped. We require the
    parameter schema to match canonical `todo_write()` exactly, ignoring descriptions so a
    re-described but structurally identical planning tool still qualifies.
    """
    if tool.name != TODO_WRITE_NAME:
        return False
    return bool(
        _schema_without_descriptions(json_schema_dump(tool.parameters))
        == _canonical_todo_write_schema()
    )


def _tools_swap_todo_write(tools: list[ToolInfo]) -> bool:
    """Tool-list condition for the swap: a canonical todo_write present, no update_plan.

    Shared by the outbound gate and the inbound parser so they agree. (The opt-out
    `internal_tools` check is layered on top in `should_swap_todo_write`.)
    """
    return any(_is_canonical_todo_write(t) for t in tools) and not any(
        t.name == UPDATE_PLAN_NAME for t in tools
    )


def should_swap_todo_write(tools: list[ToolInfo], config: GenerateConfig) -> bool:
    """Whether to render `todo_write` as the native `update_plan` tool for this request.

    Active only when not opted out (`internal_tools` is not False), a canonical
    `todo_write` tool is present, and there is no first-party `update_plan` tool to collide
    with.
    """
    return config.internal_tools is not False and _tools_swap_todo_write(tools)


def substitute_update_plan_tools(
    tools: list[ToolInfo], swap_todo_write: bool
) -> list[ToolInfo]:
    """Replace the canonical `todo_write` ToolInfo with the native `update_plan` one."""
    if not swap_todo_write:
        return tools
    update_plan_info = _update_plan_tool_info()
    return [update_plan_info if _is_canonical_todo_write(t) else t for t in tools]


def _tools_contain_function(tools: list[ToolParam], name: str) -> bool:
    return any(
        isinstance(tool, dict)
        and tool.get("type") == "function"
        and tool.get("name") == name
        for tool in tools
    )


def _responses_tool_choice_name(name: str, tools: list[ToolParam]) -> str:
    """Wire name for a forced tool_choice, accounting for the todo_write->update_plan swap.

    Keys off the tools actually sent: only rewrite when `update_plan` was sent in place of
    `todo_write` (update_plan present, todo_write absent).
    """
    if (
        name == TODO_WRITE_NAME
        and _tools_contain_function(tools, UPDATE_PLAN_NAME)
        and not _tools_contain_function(tools, TODO_WRITE_NAME)
    ):
        return UPDATE_PLAN_NAME
    return name


def _responses_call_to_inspect(
    name: str, arguments: str, tools: list[ToolInfo]
) -> tuple[str, str]:
    """Map a Responses function call's name/arguments back to inspect's.

    Reverses the todo_write->update_plan swap (only when a todo_write tool is present and no
    first-party update_plan tool is — so we never hijack a user's own update_plan), then
    falls back to the name-only alias mechanism. Malformed arguments are passed through with
    the mapped name so parse_tool_call() reports the parse error rather than silently
    producing an empty plan.
    """
    if name == UPDATE_PLAN_NAME and _tools_swap_todo_write(tools):
        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            args = None
        if isinstance(args, dict):
            return TODO_WRITE_NAME, json.dumps(_update_plan_args_to_inspect(args))
        return TODO_WRITE_NAME, arguments
    return _from_responses_tool_alias(name), arguments


def _update_plan_args_to_inspect(args: dict[str, Any]) -> dict[str, Any]:
    """Map update_plan call arguments back to todo_write's shape (plan->todos, step->content)."""
    steps = args.get("plan", args.get("todos")) or []
    result: dict[str, Any] = {
        "todos": [
            {
                "content": step.get("step", step.get("content")),
                "status": step.get("status"),
            }
            if isinstance(step, dict)
            else step
            for step in steps
        ]
    }
    if "explanation" in args:
        result["explanation"] = args["explanation"]
    return result


def _update_plan_args_from_inspect(args: dict[str, Any]) -> dict[str, Any]:
    """Map todo_write call arguments to update_plan's shape (todos->plan, content->step)."""
    steps = args.get("todos", args.get("plan")) or []
    result: dict[str, Any] = {
        "plan": [
            {
                "step": step.get("content", step.get("step")),
                "status": step.get("status"),
            }
            if isinstance(step, dict)
            else step
            for step in steps
        ]
    }
    if "explanation" in args:
        result["explanation"] = args["explanation"]
    return result


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
    return (
        "role" in param and "content" in param and not is_response_output_message(param)
    )


def is_function_call_output(
    param: ResponseInputItemParam,
) -> TypeGuard[FunctionCallOutput]:
    return param["type"] == "function_call_output"


def is_custom_tool_call_output(
    param: ResponseInputItemParam,
) -> TypeGuard[ResponseCustomToolCallOutputParam]:
    return param["type"] == "custom_tool_call_output"


def is_computer_call_output(
    param: ResponseInputItemParam,
) -> TypeGuard[ComputerCallOutput]:
    return param["type"] == "computer_call_output"


def is_assistant_message_param(
    param: ResponseInputItemParam,
) -> bool:
    # simple format w/o 'type' used by some scaffolds (e.g. Pydantic AI)
    if is_simple_assistant_message(param):
        return True

    return "type" in param and (
        is_response_output_message(param)
        or is_response_computer_tool_call(param)
        or is_response_web_search_call(param)
        or is_response_function_tool_call(param)
        or is_response_custom_tool_call(param)
        or is_response_reasoning_item(param)
        or is_response_mcp_list_tools(param)
        or is_response_mcp_call(param)
        or is_response_tool_search_call(param)
    )


def is_simple_assistant_message(
    param: ResponseInputItemParam,
) -> TypeGuard[EasyInputMessageParam | Message]:
    # EasyInputMessageParam has optional type: "message", so we check "type" not in param
    # to distinguish simple assistant messages (e.g. from Pydantic-AI) from full message params
    return (
        param.get("role") == "assistant" and "content" in param and "type" not in param
    )


def is_response_output_message(
    param: ResponseInputItemParam,
) -> TypeGuard[ResponseOutputMessageParam]:
    return (
        "type" in param
        and param["type"] == "message"
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


def is_response_code_interpreter_call(
    param: ResponseInputItemParam,
) -> TypeGuard[ResponseCodeInterpreterToolCallParam]:
    return param["type"] == "code_interpreter_call"


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


def is_response_custom_tool_call(
    param: ResponseInputItemParam,
) -> TypeGuard[ResponseCustomToolCallParam]:
    return param["type"] == "custom_tool_call"


def is_response_tool_search_call(
    param: ResponseInputItemParam,
) -> TypeGuard[ToolSearchCall]:
    return param["type"] == "tool_search_call"


def is_tool_search_output(
    param: ResponseInputItemParam,
) -> TypeGuard[ResponseToolSearchOutputItemParamParam]:
    # tolerate items without a "type" key (e.g. simple user messages) since this
    # is scanned over raw input items, some of which omit "type"
    return param.get("type") == "tool_search_output"


def is_function_tool_param(tool_param: ToolParam) -> TypeGuard[FunctionToolParam]:
    return tool_param.get("type") == "function"


def is_web_search_tool_param(tool_param: ToolParam) -> TypeGuard[WebSearchToolParam]:
    return tool_param.get("type") in ["web_search", "web_search_2025_08_26"]


def is_code_interpreter_tool_param(
    tool_param: ToolParam,
) -> TypeGuard[CodeInterpreter]:
    return tool_param.get("type") == "code_interpreter"


def is_tool_search_tool_param(
    tool_param: ToolParam,
) -> TypeGuard[ToolSearchToolParam]:
    return tool_param.get("type") == "tool_search"


def is_mcp_tool_param(tool_param: ToolParam) -> TypeGuard[Mcp]:
    return tool_param.get("type") == "mcp"


def is_computer_tool_param(tool_param: ToolParam) -> TypeGuard[ComputerToolParam]:
    return tool_param.get("type") == "computer"


def is_custom_tool_param(tool_param: ToolParam) -> TypeGuard[CustomToolParam]:
    return tool_param.get("type") == "custom"


def is_namespace_tool_param(tool_param: ToolParam) -> TypeGuard[NamespaceToolParam]:
    return tool_param.get("type") == "namespace"


def maybe_code_interpreter_tool(
    model_name: str, tool: ToolInfo
) -> CodeInterpreter | None:
    COMPATIBLE_MODELS = ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "o3", "o4-mini", "gpt-5"]
    if (
        tool.name == "code_execution"
        and tool.options
        and any(model_name.startswith(model) for model in COMPATIBLE_MODELS)
    ):
        providers: dict[str, Any] = tool.options.get("providers", {})
        options: dict[str, Any] | bool = providers.get("openai", False)
        if options is False:
            return None
        if options is True:
            return CodeInterpreter(
                type="code_interpreter",
                container=CodeInterpreterContainerCodeInterpreterToolAuto(type="auto"),
            )
        else:
            container = options.get(
                "container",
                CodeInterpreterContainerCodeInterpreterToolAuto(type="auto"),
            )

            return CodeInterpreter(
                type="code_interpreter",
                container=container,
            )

    else:
        return None


def code_interpreter_to_tool_use(
    code_interpreter: ResponseCodeInterpreterToolCall,
) -> ContentToolUse:
    return ContentToolUse(
        type="tool_use",
        tool_type="code_execution",
        id=code_interpreter.id,
        name=code_interpreter.type,
        arguments=code_interpreter.code or "",
        result=_outputs_to_result(code_interpreter.outputs),
        error="failed" if code_interpreter.status == "failed" else None,
    )


def tool_use_to_code_interpreter_param(
    content: ContentToolUse,
) -> ResponseCodeInterpreterToolCallParam:
    return ResponseCodeInterpreterToolCallParam(
        type="code_interpreter_call",
        id=content.id,
        code=content.arguments,
        container_id="",
        outputs=[OutputLogsParam(type="logs", logs=content.result)],
        status="failed" if content.error else "completed",
    )


def _outputs_to_result(outputs: list[OutputLogs | OutputImage] | None) -> str:
    if outputs is not None:
        return "\n\n".join(
            output.logs if isinstance(output, OutputLogs) else f"image: {output.url}"
            for output in outputs
        )
    else:
        return ""


def _output_message_role(item: ResponseOutputMessage) -> str:
    """Get the role of a ResponseOutputMessage as a string.

    The SDK types restrict role to Literal["assistant"], but the compact
    endpoint returns messages with role="developer" and role="user".
    Using getattr avoids mypy's non-overlapping comparison check.
    """
    return str(getattr(item, "role", "assistant"))


def chat_messages_from_compact_response(
    response: CompactedResponse,
    model: str | None = None,
) -> list[ChatMessage]:
    """Convert CompactedResponse to a list of ChatMessages.

    The compact endpoint returns the complete new context window, which may include:
    - ResponseCompactionItem: encrypted compressed representation of earlier messages
    - Other items (ResponseOutputMessage, ResponseReasoningItem, tool calls, etc.):
      recent items that weren't compacted

    The order of items is preserved. Items are processed in order:
    - ResponseCompactionItem becomes a ChatMessageUser with compaction metadata
    - ResponseOutputMessage with role="developer" is stripped (orchestrator handles system messages)
    - ResponseOutputMessage with role="user" becomes a ChatMessageUser
    - Other items (role="assistant", reasoning, tool calls) are grouped into ChatMessageAssistant

    The compaction metadata is stored in a ContentData object within a ChatMessageUser.
    When replayed, _extract_compaction_from_content_data() will extract this metadata
    and convert it back to a ResponseCompactionItemParamParam.

    Args:
        response: The CompactedResponse from client.responses.compact()
        model: Optional model name to set on ChatMessageAssistant messages.

    Returns:
        A list of ChatMessages representing the new context window, preserving
        the order of items from the response.

    Raises:
        ValueError: If no ResponseCompactionItem is found in the response output.
    """
    messages: list[ChatMessage] = []
    found_compaction = False
    pending_items: list[Any] = []

    def flush_pending_items() -> None:
        """Process accumulated non-compaction items into a ChatMessageAssistant."""
        nonlocal pending_items
        if pending_items:
            # Pass empty tools list - tool calls in compaction responses don't need parsing
            message_content, tool_calls, _, _ = _process_response_output_items(
                pending_items, []
            )
            if message_content or tool_calls:
                messages.append(
                    ChatMessageAssistant(
                        content=message_content,
                        tool_calls=tool_calls if tool_calls else None,
                        model=model,
                        source="generate",
                    )
                )
            pending_items = []

    # Process items in order
    for item in response.output:
        if isinstance(item, ResponseCompactionItem):
            # Flush any pending assistant items first
            flush_pending_items()

            found_compaction = True
            # Add the compaction item as a ChatMessageUser with ContentData
            messages.append(
                ChatMessageUser(
                    content=[
                        ContentData(
                            data={
                                "compaction_metadata": {
                                    "type": "openai_compact",
                                    "id": item.id,
                                    "encrypted_content": item.encrypted_content,
                                }
                            }
                        )
                    ],
                    source="generate",
                )
            )
        elif (
            isinstance(item, ResponseOutputMessage)
            and _output_message_role(item) == "developer"
        ):
            # Skip developer messages - the orchestrator's prefix handling
            # is the authoritative source for system messages
            pass
        elif (
            isinstance(item, ResponseOutputMessage)
            and _output_message_role(item) == "user"
        ):
            # Flush any pending assistant items first
            flush_pending_items()
            # Convert user message content to ChatMessageUser
            # Content items are ResponseOutputText or ResponseOutputRefusal
            user_content: list[Content] = [
                ContentText(text=c.text)
                if isinstance(c, ResponseOutputText)
                else ContentText(text=c.refusal, refusal=True)
                for c in item.content
            ]
            if user_content:
                messages.append(
                    ChatMessageUser(content=user_content, source="generate")
                )
        else:
            # Accumulate assistant items (ResponseOutputMessage with role="assistant",
            # ResponseReasoningItem, ResponseFunctionToolCall, etc.)
            pending_items.append(item)

    # Flush any remaining pending items
    flush_pending_items()

    if not found_compaction:
        raise ValueError("No ResponseCompactionItem found in CompactedResponse output")

    return messages


def model_usage_from_compact_response(
    response: CompactedResponse,
) -> ModelUsage | None:
    """Extract ModelUsage from CompactedResponse.

    Args:
        response: The CompactedResponse from client.responses.compact()

    Returns:
        ModelUsage if usage information is available, None otherwise.
    """
    if response.usage:
        return ModelUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.total_tokens,
        )
    return None


def pad_tool_messages_for_token_counting(
    messages: list[ResponseInputItemParam],
) -> list[ResponseInputItemParam]:
    """Pad tool messages to satisfy OpenAI's API validation for token counting.

    OpenAI's input_tokens API validates message structure and requires:
    - Every function_call block must have a corresponding function_call_output
    - Every function_call_output block must have a corresponding function_call

    When counting tokens for individual messages (e.g., for caching in compaction),
    we may have orphaned function_call or function_call_output blocks. This function
    pads with minimal fake paired items to satisfy API validation.

    This slightly overcounts tokens but that's acceptable for compaction triggering.

    Args:
        messages: List of OpenAI ResponseInputItemParam messages.

    Returns:
        List of messages with padding added for orphaned tool calls/outputs.
    """
    if not messages:
        return messages

    result: list[ResponseInputItemParam] = []

    for i, msg in enumerate(messages):
        # Forward scan: Check for function_call_output without preceding function_call
        if is_function_call_output(msg):
            call_id = msg.get("call_id", "")
            has_matching_call = (
                result
                and is_response_function_tool_call(result[-1])
                and result[-1].get("call_id") == call_id
            )

            # Add fake function_call for orphaned output
            if not has_matching_call:
                fake_call: ResponseFunctionToolCallParam = {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": "placeholder",
                    "arguments": "{}",
                }
                result.append(fake_call)

        result.append(msg)

        # Reverse scan: Check for function_call without following function_call_output
        if is_response_function_tool_call(msg):
            call_id = msg.get("call_id", "")
            next_msg = messages[i + 1] if i + 1 < len(messages) else None
            has_matching_output = (
                next_msg is not None
                and is_function_call_output(next_msg)
                and next_msg.get("call_id") == call_id
            )

            # Add fake function_call_output for orphaned call
            if not has_matching_output:
                fake_output: FunctionCallOutput = {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": "",
                }
                result.append(fake_output)

    return result
