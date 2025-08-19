from logging import getLogger
from time import time
from typing import Any, cast

from openai.types.responses import (
    Response,
    ResponseFunctionWebSearch,
    ResponseInputFileParam,
    ResponseInputImageParam,
    ResponseInputItemParam,
    ResponseInputTextParam,
    ResponseOutputItem,
    ResponseOutputMessage,
    ResponseOutputRefusal,
    ResponseOutputText,
    ResponseReasoningItem,
    ToolParam,
)
from openai.types.responses import (
    Tool as ResponsesTool,
)
from openai.types.responses.response import ToolChoice as ResponsesToolChoice
from openai.types.responses.response_create_params import (
    ToolChoice as ResponsesToolChoiceParam,
)
from openai.types.responses.response_input_item_param import (
    Message,
)
from openai.types.responses.response_output_item import McpCall, McpListTools
from pydantic import JsonValue, TypeAdapter
from shortuuid import uuid

from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
)
from inspect_ai._util.logger import warn_once
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig, ResponseSchema
from inspect_ai.model._openai import (
    content_internal_tag,
    message_internal_tag,
)
from inspect_ai.model._openai_responses import (
    MESSAGE_ID,
    content_from_response_input_content_param,
    is_assistant_message_param,
    is_computer_call_output,
    is_computer_tool_param,
    is_function_call_output,
    is_function_tool_param,
    is_mcp_tool_param,
    is_response_computer_tool_call,
    is_response_function_tool_call,
    is_response_input_message,
    is_response_mcp_call,
    is_response_mcp_list_tools,
    is_response_output_message,
    is_response_output_refusal,
    is_response_output_text,
    is_response_reasoning_item,
    is_tool_choice_function_param,
    is_tool_choice_mcp_param,
    is_web_search_tool_param,
    reasoning_from_responses_reasoning,
    responses_extra_body_fields,
    responses_model_usage,
    responses_reasoning_from_reasoning,
    to_inspect_citation,
    tool_use_to_mcp_call_param,
    tool_use_to_mcp_list_tools_param,
    tool_use_to_web_search_param,
)
from inspect_ai.model._providers._openai_computer_use import computer_parmaeters
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.util._json import JSONSchema

from .util import resolve_inspect_model

logger = getLogger(__file__)


async def inspect_responses_api_request(json_data: dict[str, Any]) -> Response:
    # resolve model
    model = resolve_inspect_model(str(json_data["model"]))
    model_name = model.api.model_name

    # convert openai tools to inspect tools
    responses_tools: list[ToolParam] = json_data.get("tools", [])
    tools = [tool_from_responses_tool(tool) for tool in responses_tools]
    responses_tool_choice: ResponsesToolChoiceParam | None = json_data.get(
        "tool_choice", None
    )
    tool_choice = tool_choice_from_responses_tool_choice(responses_tool_choice)

    # convert to inspect messages
    input: list[ResponseInputItemParam] = json_data["input"]
    messages = messages_from_responses_input(input, tools, model_name)

    # run inference
    output = await model.generate(
        input=messages,
        tool_choice=tool_choice,
        tools=tools,
        config=generate_config_from_openai_responses(json_data),
    )

    # return response
    return Response(
        id=output.message.id or uuid(),
        created_at=int(time()),
        model=model_name,
        object="response",
        output=responses_output_items_from_assistant_message(output.message),
        parallel_tool_calls=False,
        tool_choice=responses_tool_choice_param_to_tool_choice(responses_tool_choice),
        tools=responses_tool_params_to_tools(responses_tools),
        usage=responses_model_usage(output.usage),
    )


def tool_choice_from_responses_tool_choice(
    tool_choice: ResponsesToolChoiceParam | None,
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


tool_choice_adapter = TypeAdapter[ResponsesToolChoice](ResponsesToolChoice)


def responses_tool_choice_param_to_tool_choice(
    tool_choice: ResponsesToolChoiceParam | None,
) -> ResponsesToolChoice:
    if tool_choice is None:
        return "auto"
    else:
        return tool_choice_adapter.validate_python(tool_choice)


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


tool_list_adapter = TypeAdapter(list[ResponsesTool])


def responses_tool_params_to_tools(tool_params: list[ToolParam]) -> list[ResponsesTool]:
    return tool_list_adapter.validate_python(tool_params)


def generate_config_from_openai_responses(json_data: dict[str, Any]) -> GenerateConfig:
    # warn for unsupported params
    def warn_unsupported(param: str) -> None:
        if param in json_data:
            warn_once(logger, f"'{param}' option not supported for agent bridge")

    warn_unsupported("background")  # we don't proxy background polling requests
    warn_unsupported("prompt")  # prompt template
    warn_unsupported("top_logprobs")  # don't have this yet for responses

    config = GenerateConfig()
    config.system_message = json_data.get("instructions", None)
    config.max_tokens = json_data.get("max_output_tokens", None)
    config.parallel_tool_calls = json_data.get("parallel_tool_calls", None)
    reasoning = json_data.get("reasoning", None)
    if reasoning:
        if "effort" in reasoning:
            config.reasoning_effort = reasoning["effort"]
        if "summary" in reasoning:
            config.reasoning_summary = reasoning["summary"]
    config.temperature = json_data.get("temperature", None)
    config.top_p = json_data.get("top_p", None)

    # response format
    text: dict[str, Any] | None = json_data.get("text", None)
    if text is not None:
        format: dict[str, Any] | None = text.get("format", None)
        if format is not None:
            if format.get("type", None) == "json_schema":
                config.response_schema = ResponseSchema(
                    name=format.get("name", "schema"),
                    description=format.get("description", None),
                    json_schema=JSONSchema.model_validate(format.get("schema", {})),
                    strict=format.get("strict", None),
                )

    # extra_body params (i.e. passthrough for native responses)
    extra_body: dict[str, Any] = {}
    for field in responses_extra_body_fields():
        if field in json_data:
            extra_body[field] = json_data[field]
    if len(extra_body) > 0:
        config.extra_body = extra_body

    # return config
    return config


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
                                    internal={MESSAGE_ID: param["id"]},
                                    citations=(
                                        [
                                            to_inspect_citation(annotation)
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
                                    internal={MESSAGE_ID: param["id"]},
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
                    # TODO: this needs to come from _AssistantInternal
                    # Raise or assert that this can't happen b/c it is in internal
                    pass

                elif is_response_reasoning_item(param):
                    content.append(reasoning_from_responses_reasoning(param))
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
                content_from_response_input_content_param(c) for c in item_content
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


output_item_adapter = TypeAdapter(list[ResponseOutputItem])


def responses_output_items_from_assistant_message(
    message: ChatMessageAssistant,
) -> list[ResponseOutputItem]:
    # set aside message internal if we have it
    if message.internal:
        message_internal: str | None = f"\n{message_internal_tag(message.internal)}\n"
    else:
        message_internal = None

    output: list[ResponseOutputItem] = []
    for content in message.content:
        if isinstance(content, ContentText):
            # check for content.internal
            if content.internal:
                internal: str = f"\n{content_internal_tag(content.internal)}\n"
            else:
                internal = ""
            # collect and append message internal (we only send it once)
            if message_internal is not None:
                internal = f"{internal}{message_internal}"
                message_internal = None

            # apply internal to content
            content_text = f"{content.text}{internal}"

            output.append(
                ResponseOutputMessage(
                    type="message",
                    id=uuid(),
                    role="assistant",
                    content=[
                        ResponseOutputRefusal(type="refusal", refusal=content_text)
                        if content.refusal
                        else ResponseOutputText(
                            type="output_text", text=content_text, annotations=[]
                        )
                    ],
                    status="completed",
                )
            )
        elif isinstance(content, ContentReasoning):
            reasoning = responses_reasoning_from_reasoning(content)
            output.append(ResponseReasoningItem.model_validate(reasoning))

        elif isinstance(content, ContentToolUse):
            if content.tool_type == "mcp_list_tools":
                mcp_list_tools_param = tool_use_to_mcp_list_tools_param(content)
                output.append(McpListTools.model_validate(mcp_list_tools_param))

            elif content.tool_type == "mcp_call":
                mcp_call_param = tool_use_to_mcp_call_param(content)
                output.append(McpCall.model_validate(mcp_call_param))

            elif content.tool_type == "web_search_call":
                tool_pweb_search_param = tool_use_to_web_search_param(content)
                output.append(
                    ResponseFunctionWebSearch.model_validate(tool_pweb_search_param)
                )

    # for tool_call in message.tool_calls:
    #     pass
    # TODO: grab the standard tool calls and add them

    return output

    # input_items = _openai_input_items_from_chat_message_assistant(message)
    # return output_item_adapter.validate_python(input_items)
