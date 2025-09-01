import json
from logging import getLogger
from time import time
from typing import Any, Set, cast

from openai.types.responses import (
    Response,
    ResponseComputerToolCall,
    ResponseFunctionToolCall,
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
    WebSearchToolParam,
)
from openai.types.responses import (
    Tool as ResponsesTool,
)
from openai.types.responses.response import (
    IncompleteDetails,
)
from openai.types.responses.response import (
    ToolChoice as ResponsesToolChoice,
)
from openai.types.responses.response_create_params import (
    ToolChoice as ResponsesToolChoiceParam,
)
from openai.types.responses.response_function_web_search import (
    Action,
    ActionSearch,
)
from openai.types.responses.response_input_item_param import (
    Message,
)
from openai.types.responses.response_output_item import (
    McpCall,
    McpListTools,
    McpListToolsTool,
)
from pydantic import TypeAdapter, ValidationError
from shortuuid import uuid

from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
)
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import (
    GenerateConfig,
    ResponseSchema,
)
from inspect_ai.model._internal import (
    CONTENT_INTERNAL_TAG,
    content_internal_tag,
    parse_content_with_internal,
)
from inspect_ai.model._model_output import StopReason
from inspect_ai.model._openai_responses import (
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
    is_response_web_search_call,
    is_tool_choice_function_param,
    is_tool_choice_mcp_param,
    is_web_search_tool_param,
    mcp_call_to_tool_use,
    mcp_list_tools_to_tool_use,
    reasoning_from_responses_reasoning,
    responses_extra_body_fields,
    responses_model_usage,
    responses_reasoning_from_reasoning,
    to_inspect_citation,
    tool_use_to_mcp_call_param,
    tool_use_to_mcp_list_tools_param,
    web_search_to_tool_use,
)
from inspect_ai.model._providers._openai_computer_use import (
    tool_call_arguments_to_action,
    tool_call_from_openai_computer_tool_call,
)
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.tool._tool_util import tool_to_tool_info
from inspect_ai.tool._tools._computer._computer import computer
from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
    web_search,
)
from inspect_ai.util._json import JSONSchema

from .util import apply_message_ids, resolve_generate_config, resolve_inspect_model

logger = getLogger(__file__)


async def inspect_responses_api_request_impl(
    json_data: dict[str, Any],
    web_search: WebSearchProviders,
    bridge: AgentBridge,
) -> Response:
    # resolve model
    bridge_model_name = str(json_data["model"])
    model = resolve_inspect_model(bridge_model_name)
    model_name = model.api.model_name

    # record parallel tool calls
    parallel_tool_calls = json_data.get("parallel_tool_calls", True)

    # convert openai tools to inspect tools
    responses_tools: list[ToolParam] = json_data.get("tools", [])
    tools = [tool_from_responses_tool(tool, web_search) for tool in responses_tools]
    responses_tool_choice: ResponsesToolChoiceParam | None = json_data.get(
        "tool_choice", None
    )
    tool_choice = tool_choice_from_responses_tool_choice(responses_tool_choice)

    # convert to inspect messages
    input: list[ResponseInputItemParam] = json_data["input"]

    debug_log("SCAFFOLD INPUT", input)

    messages = messages_from_responses_input(input, tools, model_name)
    debug_log("INSPECT MESSAGES", messages)

    # extract generate config (hoist instructions into system_message)
    config = generate_config_from_openai_responses(json_data)
    if config.system_message is not None:
        messages.insert(0, ChatMessageSystem(content=config.system_message))
        config.system_message = None

    # try to maintain id stability
    apply_message_ids(bridge, messages)

    # give inspect-level config priority over agent default config
    config = resolve_generate_config(model, config)

    # run inference
    output = await model.generate(
        input=messages,
        tool_choice=tool_choice,
        tools=tools,
        config=config,
    )

    debug_log("INSPECT OUTPUT", output.message)

    # update state
    if bridge_model_name == "inspect":
        bridge.state.messages = messages + [output.message]
        bridge.state.output = output

    # return response
    response = Response(
        id=output.message.id or uuid(),
        created_at=int(time()),
        incomplete_details=responses_incomplete_details(output.stop_reason),
        model=model_name,
        object="response",
        output=responses_output_items_from_assistant_message(output.message),
        parallel_tool_calls=parallel_tool_calls,
        tool_choice=responses_tool_choice_param_to_tool_choice(responses_tool_choice),
        tools=responses_tool_params_to_tools(responses_tools),
        usage=responses_model_usage(output.usage),
    )
    debug_log("SCAFFOLD RESPONSE", response)

    return response


def debug_log(caption: str, o: Any) -> None:
    # from inspect_ai._util.json import to_json_str_safe

    # print(caption)
    # print(to_json_str_safe(o))
    pass


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


def tool_from_responses_tool(
    tool_param: ToolParam, web_search_providers: WebSearchProviders
) -> ToolInfo | Tool:
    if is_function_tool_param(tool_param):
        return ToolInfo(
            name=tool_param["name"],
            description=tool_param["description"] or tool_param["name"],
            parameters=ToolParams.model_validate(tool_param["parameters"]),
        )
    elif is_web_search_tool_param(tool_param):
        return web_search(
            resolve_web_search_providers(tool_param, web_search_providers)
        )
    elif is_computer_tool_param(tool_param):
        return computer()
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


def resolve_web_search_providers(
    tool_param: WebSearchToolParam, web_search: WebSearchProviders
) -> WebSearchProviders:
    # pass through openai options if there is no special openai config
    openai_options = web_search.get("openai", False)
    if openai_options is True or (
        isinstance(openai_options, dict) and len(openai_options) == 0
    ):
        if "user_location" in tool_param or "search_context_size" in tool_param:
            # this came from the user in the external scaffold. we want
            # all the fields except the type as our 'web_search' config
            tool_param = tool_param.copy()
            del tool_param["type"]  # type: ignore[misc]

            # this came from the inspect agent_bridge() call. we want
            # to replace it with whatever the user specified in the scaffold.
            web_search = web_search.copy()
            web_search["openai"] = tool_param  # type: ignore[typeddict-item]

    return web_search


tool_list_adapter = TypeAdapter(list[ResponsesTool])


def responses_incomplete_details(stop_reason: StopReason) -> IncompleteDetails | None:
    match stop_reason:
        case "content_filter":
            return IncompleteDetails(reason="content_filter")
        case "max_tokens":
            return IncompleteDetails(reason="max_output_tokens")
        case _:
            return None


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
    tools: list[ToolInfo | Tool],
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

    # resolve tools to tool info
    tools_info = [
        tool_to_tool_info(tool) if not isinstance(tool, ToolInfo) else tool
        for tool in tools
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
                        text = str(output.get("text", output.get("refusal", "")))

                        asst_content, content_internal = parse_content_with_internal(
                            text, CONTENT_INTERNAL_TAG
                        )

                        if is_response_output_text(output):
                            content.append(
                                ContentText(
                                    text=asst_content,
                                    internal=content_internal,
                                    citations=(
                                        [
                                            to_inspect_citation(annotation)
                                            for annotation in output["annotations"]
                                        ]
                                        if output.get("annotations", None)
                                        else None
                                    ),
                                )
                            )
                        elif is_response_output_refusal(output):
                            content.append(
                                ContentText(
                                    text=output["refusal"],
                                    refusal=True,
                                    internal=content_internal,
                                )
                            )

                elif is_response_function_tool_call(param):
                    function_calls_by_id[param["call_id"]] = param["name"]
                    tool_calls.append(
                        parse_tool_call(
                            id=param["call_id"],
                            function=param["name"],
                            arguments=param["arguments"],
                            tools=tools_info,
                        )
                    )
                elif is_response_computer_tool_call(param):
                    computer_call = ResponseComputerToolCall.model_validate(param)
                    tool_calls.append(
                        tool_call_from_openai_computer_tool_call(computer_call)
                    )

                elif is_response_reasoning_item(param):
                    content.append(reasoning_from_responses_reasoning(param))
                elif is_response_web_search_call(param):
                    web_search = ResponseFunctionWebSearch.model_validate(param)
                    content.append(web_search_to_tool_use(web_search))
                elif is_response_mcp_list_tools(param):
                    mcp_list_tools = McpListTools.model_validate(param)
                    content.append(mcp_list_tools_to_tool_use(mcp_list_tools))
                elif is_response_mcp_call(param):
                    mcp_call = McpCall.model_validate(param)
                    content.append(mcp_call_to_tool_use(mcp_call))
                else:
                    raise RuntimeError(
                        f"Unexpected assitant message type: {param['type']}"
                    )

            # some scaffolds (e.g. codex) can present duplicate assistant content
            content = filter_duplicate_assistant_content(content)

            messages.append(
                ChatMessageAssistant(
                    content=content,
                    tool_calls=tool_calls,
                    model=model_name,
                )
            )

            pending_assistant_message_params.clear()

    for item in input:
        # accumulate assistant message params until we clear the assistant message
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


# some scaffolds (e.g. codex) can present duplciate assistant messages
def filter_duplicate_assistant_content(
    input: list[Content],
) -> list[Content]:
    filtered_input: list[Content] = []
    messages_ids: Set[str] = set()
    for c in reversed(input):
        if c.type == "text" and c.internal:
            internal = to_json_str_safe(c.internal)
            if internal not in messages_ids:
                filtered_input.append(c)
                messages_ids.add(internal)
        else:
            filtered_input.append(c)
    return list(reversed(filtered_input))


output_item_adapter = TypeAdapter(list[ResponseOutputItem])

action_adapter = TypeAdapter[Action](Action)

mcp_tool_adapter = TypeAdapter(list[McpListToolsTool])


def responses_output_items_from_assistant_message(
    message: ChatMessageAssistant,
) -> list[ResponseOutputItem]:
    output: list[ResponseOutputItem] = []
    for content in message.content:
        if isinstance(content, ContentText):
            # check for content.internal
            if content.internal:
                internal: str = f"\n{content_internal_tag(content.internal)}\n"
            else:
                internal = ""

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
            if content.tool_type == "web_search":
                # if this originated from responses then the action will validate as
                # a native OpenAI action -- otherwise just provide a plausible stand-in
                # (the native model provider e.g. anthropic will have saved its call
                # keyed by id so that it can replay with the correct fidelity)
                try:
                    action = action_adapter.validate_json(content.arguments)
                except ValidationError:
                    action = ActionSearch(type="search", query=content.arguments)

                output.append(
                    ResponseFunctionWebSearch(
                        type="web_search_call",
                        id=content.id,
                        action=action,
                        status="failed" if content.error else "completed",
                    )
                )
            elif content.name == "mcp_list_tools":
                # currently this is only ever done by OpenAI Responses so
                # it is safe to read in a validated way (unlike web search)
                mcp_list_tools = tool_use_to_mcp_list_tools_param(content)
                output.append(McpListTools.model_validate(mcp_list_tools))
            else:
                mcp_call = tool_use_to_mcp_call_param(content)
                output.append(McpCall.model_validate(mcp_call))

    for tool_call in message.tool_calls or []:
        if tool_call.function == "computer":
            output.append(
                ResponseComputerToolCall(
                    id=uuid(),
                    type="computer_call",
                    action=tool_call_arguments_to_action(tool_call.arguments),
                    call_id=tool_call.id,
                    pending_safety_checks=[],
                    status="completed",
                )
            )
        else:
            output.append(
                ResponseFunctionToolCall(
                    type="function_call",
                    call_id=tool_call.id,
                    name=tool_call.function,
                    arguments=json.dumps(tool_call.arguments),
                )
            )

    return output
