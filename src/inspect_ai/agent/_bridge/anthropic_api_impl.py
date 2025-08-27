from __future__ import annotations

from logging import getLogger
from typing import Any, Literal, cast

from anthropic.types import Message, ToolChoiceParam, Usage
from anthropic.types import StopReason as AnthropicStopReason
from anthropic.types.beta import BetaRequestMCPServerURLDefinitionParam
from shortuuid import uuid

from inspect_ai.model._chat_message import ChatMessage, ChatMessageSystem
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelUsage, StopReason
from inspect_ai.model._providers.anthropic import (
    ToolParamDef,
    anthropic_extra_body_fields,
    assistant_message_blocks,
)
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders

from .types import AgentBridge
from .util import apply_message_ids, resolve_inspect_model

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
    messages: list[ChatMessage] = []

    # extract generate config (hoist instructions into system_message)
    config = generate_config_from_anthropic(json_data)
    if config.system_message is not None:
        messages.insert(0, ChatMessageSystem(content=config.system_message))
        config.system_message = None

    # try to maintain id stability
    apply_message_ids(bridge, messages)

    # run inference
    output = await model.generate(
        input=messages,
        tools=tools,
        tool_choice=tool_choice,
        config=config,
    )

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
    web_search: WebSearchProviders,
) -> list[ToolInfo]:
    tools: list[ToolInfo] = []

    for anthropic_tool in anthropic_tools or []:
        pass

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
