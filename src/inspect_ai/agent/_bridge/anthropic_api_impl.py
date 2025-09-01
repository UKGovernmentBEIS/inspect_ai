from __future__ import annotations

import base64
import io
from logging import getLogger
from os import PathLike
from typing import IO, Any, Literal, cast

from anthropic.types import (
    ContentBlock,
    ContentBlockParam,
    DocumentBlockParam,
    ImageBlockParam,
    Message,
    MessageParam,
    SearchResultBlockParam,
    TextBlockParam,
    ToolChoiceParam,
    Usage,
    WebSearchTool20250305Param,
)
from anthropic.types import StopReason as AnthropicStopReason
from anthropic.types.beta import BetaRequestMCPServerURLDefinitionParam
from shortuuid import uuid

from inspect_ai._util.content import Content, ContentDocument, ContentImage, ContentText
from inspect_ai._util.images import as_data_uri
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._internal import CONTENT_INTERNAL_TAG, parse_content_with_internal
from inspect_ai.model._model_output import ModelUsage, StopReason
from inspect_ai.model._providers._anthropic_citations import to_inspect_citation
from inspect_ai.model._providers.anthropic import (
    ToolParamDef,
    anthropic_extra_body_fields,
    assistant_message_blocks,
    content_and_tool_calls_from_assistant_content_blocks,
    is_computer_tool,
    is_text_editor_tool,
    is_tool_param,
    is_web_search_tool,
)
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_call import ToolCallError
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.tool._tool_util import tool_to_tool_info
from inspect_ai.tool._tools._computer._computer import computer
from inspect_ai.tool._tools._text_editor import text_editor
from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
    web_search,
)

from .types import AgentBridge
from .util import apply_message_ids, resolve_generate_config, resolve_inspect_model

logger = getLogger(__file__)


async def inspect_anthropic_api_request_impl(
    json_data: dict[str, Any],
    web_search: WebSearchProviders,
    bridge: AgentBridge,
) -> Message:
    # resolve model
    bridge_model_name = str(json_data["model"])
    model = resolve_inspect_model(bridge_model_name)

    # tools
    anthropic_tools: list[ToolParamDef] | None = json_data.get("tools", None)
    anthropic_mcp_servers: list[BetaRequestMCPServerURLDefinitionParam] | None = (
        json_data.get("mcp_servers", None)
    )
    tools = tools_from_anthropic_tools(
        anthropic_tools, anthropic_mcp_servers, web_search
    )

    # tool choice
    anthropic_tool_choice: ToolChoiceParam | None = json_data.get("tool_choice", None)
    tool_choice = tool_choice_from_anthropic_tool_choice(anthropic_tool_choice)

    # convert to inspect messages
    input: list[MessageParam] = json_data["messages"]
    debug_log("SCAFFOLD INPUT", input)

    messages = await messages_from_anthropic_input(input, tools)
    debug_log("INSPECT MESSAGES", messages)

    # extract generate config (hoist instructions into system_message)
    config = generate_config_from_anthropic(json_data)
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
        tools=tools,
        tool_choice=tool_choice,
        config=config,
    )

    debug_log("INSPECT OUTPUT", output.message)

    # update state
    if bridge_model_name == "inspect":
        bridge.state.messages = messages + [output.message]
        bridge.state.output = output

    # return message
    message = Message(
        id=output.message.id or uuid(),
        content=await assistant_message_blocks(output.message),  # type: ignore[arg-type]
        model=output.model,
        role="assistant",
        stop_reason=anthropic_stop_reason(output.stop_reason),
        type="message",
        usage=anthropic_usage(output.usage or ModelUsage()),
    )
    debug_log("SCAFFOLD RESPONSE", message)

    return message


def debug_log(caption: str, o: Any) -> None:
    # from inspect_ai._util.json import to_json_str_safe

    # print(caption)
    # print(to_json_str_safe(o))
    pass


def generate_config_from_anthropic(json_data: dict[str, Any]) -> GenerateConfig:
    config = GenerateConfig()
    config.max_tokens = json_data.get("max_tokens", None)
    config.stop_seqs = json_data.get("stop_sequences", None) or None
    config.system_message = json_data.get("system", None)
    config.temperature = json_data.get("temperature", None)
    config.top_k = json_data.get("top_k", None)
    config.top_p = json_data.get("top_p", None)

    thinking = json_data.get("thinking", None)
    if thinking:
        if thinking.get("type", None) == "enabled":
            config.reasoning_tokens = thinking.get("budget_tokens", None)

    tool_choice = json_data.get("tool_choice", {})
    if tool_choice.get("disable_parallel_tool_use", None) is True:
        config.parallel_tool_calls = False

    # extra_body params (i.e. passthrough for native responses)
    extra_body: dict[str, Any] = {}
    for field in anthropic_extra_body_fields():
        if field in json_data:
            extra_body[field] = json_data[field]
    if len(extra_body) > 0:
        config.extra_body = extra_body

    return config


def tools_from_anthropic_tools(
    anthropic_tools: list[ToolParamDef] | None,
    anthropic_mcp_servers: list[BetaRequestMCPServerURLDefinitionParam] | None,
    web_search_providers: WebSearchProviders,
) -> list[ToolInfo | Tool]:
    tools: list[ToolInfo | Tool] = []

    for anthropic_tool in anthropic_tools or []:
        if is_tool_param(anthropic_tool):
            tools.append(
                ToolInfo(
                    name=anthropic_tool["name"],
                    description=anthropic_tool["description"],
                    parameters=ToolParams.model_validate(
                        anthropic_tool["input_schema"]
                    ),
                )
            )
        elif is_text_editor_tool(anthropic_tool):
            tools.append(text_editor())
        elif is_computer_tool(anthropic_tool):
            tools.append(computer())
        elif is_web_search_tool(anthropic_tool):
            tools.append(
                web_search(
                    resolve_web_search_providers(anthropic_tool, web_search_providers)
                )
            )
        else:
            raise RuntimeError(
                f"ToolParam of type {anthropic_tool['type']} not supported by agent bridge."
            )

    for mcp_server in anthropic_mcp_servers or []:
        # allowed tools (default is 'all')
        tool_configuration = mcp_server.get("tool_configuration", {}) or {}
        if tool_configuration.get("enabled", False) is True:
            allowed_tools = cast(
                list[str] | Literal["all"],
                tool_configuration.get("allowed_tools", "all"),
            )
        else:
            allowed_tools = "all"

        # authorization header
        if "authorization_token" in mcp_server:
            headers: dict[str, str] | None = {
                "Authorization": f"BEARER {mcp_server['authorization_token']}"
            }
        else:
            headers = None

        # build config
        config = MCPServerConfigHTTP(
            type="sse" if "sse" in mcp_server["url"] else "http",
            name=mcp_server["name"],
            tools=allowed_tools,
            url=mcp_server["url"],
            headers=headers,
        )
        # create tool from config
        tools.append(
            ToolInfo(
                name=f"mcp_server_{config.name}",
                description=f"mcp_server_{config.name}",
                options=config.model_dump(),
            )
        )

    return tools


def resolve_web_search_providers(
    tool_param: WebSearchTool20250305Param, web_search: WebSearchProviders
) -> WebSearchProviders:
    # pass through anthropic options if there is no special anthropic config
    anthropic_options = web_search.get("anthropic", False)
    if anthropic_options is True or (
        isinstance(anthropic_options, dict) and len(anthropic_options) == 0
    ):
        # this came from the user in the external scaffold. we want
        # all the fields except the type as our 'web_search' config
        tool_param = tool_param.copy()
        del tool_param["type"]  # type: ignore[misc]

        # this came from the inspect agent_bridge() call. we want
        # to replace it with whatever the user specified in the scaffold.
        web_search = web_search.copy()
        web_search["anthropic"] = tool_param  # type: ignore[typeddict-item]

    return web_search


def tool_choice_from_anthropic_tool_choice(
    tool_choice: ToolChoiceParam | None,
) -> ToolChoice | None:
    if tool_choice is None:
        return None

    match tool_choice["type"]:
        case "any":
            return "any"
        case "auto":
            return "auto"
        case "none":
            return "none"
        case "tool":
            return ToolFunction(name=tool_choice["name"])


async def messages_from_anthropic_input(
    input: list[MessageParam], tools: list[ToolInfo | Tool]
) -> list[ChatMessage]:
    messages: list[ChatMessage] = []

    # resolve tools to tool info
    tools_info = [
        tool_to_tool_info(tool) if not isinstance(tool, ToolInfo) else tool
        for tool in tools
    ]

    # track tool names for tool ids
    tool_names: dict[str, str] = {}

    for param in input:
        if param["role"] == "assistant":
            # resolve str to block
            if isinstance(param["content"], str):
                param_content: list[ContentBlockParam | ContentBlock] = [
                    TextBlockParam(type="text", text=param["content"])
                ]
            else:
                param_content = list(param["content"])
            # create assistant message
            assistant_content, tool_calls = (
                content_and_tool_calls_from_assistant_content_blocks(
                    param_content, tools_info
                )
            )
            messages.append(
                ChatMessageAssistant(content=assistant_content, tool_calls=tool_calls)
            )

            # record tool names for creating ChatMessageTool
            for tool_call in tool_calls or []:
                tool_names[tool_call.id] = tool_call.function

        elif param["role"] == "user":
            if isinstance(param["content"], str):
                messages.append(ChatMessageUser(content=param["content"]))
            else:
                pending_user_content: list[
                    TextBlockParam | ImageBlockParam | DocumentBlockParam
                ] = []

                def flush_pending_user_content() -> None:
                    nonlocal pending_user_content
                    if len(pending_user_content) > 0:  # noqa: B023
                        messages.append(
                            ChatMessageUser(
                                content=[
                                    content_block_to_content(b)
                                    for b in pending_user_content  # noqa: B023
                                ]
                            )
                        )
                        pending_user_content.clear()  # noqa: B023

                for c in param["content"]:
                    if not isinstance(c, dict):
                        logger.warning(f"Unexpected message content: {c}")
                        continue
                    if c["type"] == "tool_result":
                        flush_pending_user_content()
                        content = (
                            c["content"]
                            if isinstance(c["content"], str)
                            else [content_block_to_content(b) for b in c["content"]]
                        )
                        messages.append(
                            ChatMessageTool(
                                tool_call_id=c["tool_use_id"],
                                function=tool_names.get(c["tool_use_id"], None),
                                content=content,
                                error=ToolCallError(
                                    type="unknown", message=str(c["content"])
                                )
                                if c.get("is_error", False) is True
                                else None,
                            )
                        )
                    elif (
                        c["type"] == "text"
                        or c["type"] == "image"
                        or c["type"] == "document"
                    ):
                        pending_user_content.append(c)
                    else:
                        raise RuntimeError("Unexpected input parameter: {c}")

                flush_pending_user_content()

        else:
            raise RuntimeError(f"Unexpected message role: {param['role']}")

    return messages


def content_block_to_content(
    block: TextBlockParam
    | ImageBlockParam
    | DocumentBlockParam
    | SearchResultBlockParam,
) -> Content:
    if block["type"] == "text":
        text = block["text"]
        text, content_internal = parse_content_with_internal(text, CONTENT_INTERNAL_TAG)
        return ContentText(
            text=text,
            internal=content_internal,
            citations=[
                to_inspect_citation(cite) for cite in block.get("citations", []) or []
            ]
            if block.get("citations", None) is not None
            else None,
        )
    elif block["type"] == "image":
        if block["source"]["type"] == "base64":
            data = base_64_data(block["source"]["data"])
            return ContentImage(
                image=as_data_uri(
                    mime_type=block["source"]["media_type"],
                    data=data,
                )
            )
        else:
            return ContentImage(image=block["source"]["url"])
    elif block["type"] == "document":
        source = block["source"]
        if source["type"] == "text":
            return ContentDocument(
                document=source["data"], mime_type=source["media_type"]
            )
        elif source["type"] == "url":
            return ContentDocument(document=source["url"])
        elif source["type"] == "base64":
            data = base_64_data(source["data"])
            return ContentDocument(
                document=as_data_uri(source["media_type"], data),
                mime_type=source["media_type"],
            )
        elif source["type"] == "content":
            c = source["content"]
            if isinstance(c, str):
                return ContentText(text=c)
            else:
                return content_block_to_content(list(c)[0])
    else:
        raise RuntimeError(f"Unsupported content block type: {type(block)}")


def base_64_data(data: str | IO[bytes] | PathLike[str]) -> str:
    if isinstance(data, io.IOBase):
        data = base64.b64encode(data.read()).decode("utf-8")
    if isinstance(data, str):
        return data
    else:
        raise RuntimeError("Unsupported image content type: {data}")


def anthropic_stop_reason(stop_reason: StopReason) -> AnthropicStopReason:
    match stop_reason:
        case "stop":
            return "end_turn"
        case "max_tokens":
            return "max_tokens"
        case "model_length":
            return "max_tokens"
        case "tool_calls":
            return "tool_use"
        case "content_filter":
            return "refusal"
        case "unknown":
            return "end_turn"


def anthropic_usage(usage: ModelUsage) -> Usage:
    return Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_creation_input_tokens=usage.input_tokens_cache_write,
        cache_read_input_tokens=usage.input_tokens_cache_read,
    )
