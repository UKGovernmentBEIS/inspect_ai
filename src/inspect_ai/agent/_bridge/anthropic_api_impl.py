from __future__ import annotations

import base64
import io
from logging import getLogger
from os import PathLike
from typing import IO, Any, Literal, cast

from anthropic.types import (
    BrowserStateBlockParam,
    ContentBlock,
    ContentBlockParam,
    DocumentBlockParam,
    ImageBlockParam,
    Message,
    MessageParam,
    OutputTokensDetails,
    SearchResultBlockParam,
    TextBlockParam,
    ToolReferenceBlockParam,
    Usage,
    WebSearchTool20250305Param,
    WebSearchTool20260209Param,
)
from anthropic.types import StopReason as AnthropicStopReason
from anthropic.types.beta import (
    BetaMessage,
    BetaOutputTokensDetails,
    BetaRequestMCPServerToolConfigurationParam,
    BetaRequestMCPServerURLDefinitionParam,
    BetaUsage,
)
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
from inspect_ai.model._generate_config import (
    GenerateConfig,
    ResponseSchema,
)
from inspect_ai.model._internal import CONTENT_INTERNAL_TAG, parse_content_with_internal
from inspect_ai.model._model import ModelName
from inspect_ai.model._model_output import ModelUsage, StopReason
from inspect_ai.model._providers._anthropic_citations import to_inspect_citation
from inspect_ai.model._providers.anthropic import (
    ToolParamDef,
    anthropic_extra_body_fields,
    assistant_message_blocks,
    content_and_tool_calls_from_assistant_content_blocks,
    is_bash_tool,
    is_code_execution_tool,
    is_computer_tool,
    is_text_editor_tool,
    is_tool_param,
    is_web_fetch_tool,
    is_web_search_tool,
)
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_call import ToolCallError
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.tool._tool_util import tool_to_tool_info
from inspect_ai.tool._tools._code_execution import (
    CodeExecutionProviders,
    code_execution,
)
from inspect_ai.tool._tools._computer._computer import computer
from inspect_ai.tool._tools._execute import bash
from inspect_ai.tool._tools._text_editor import text_editor
from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
    web_search,
)

from ._errors import BridgePolicyError
from .types import AgentBridge
from .util import (
    apply_message_ids,
    bridge_generate,
    clear_generation_params,
    client_json_schema,
    client_request_object,
    client_request_string,
    relax_tool_choice_for_withheld,
    resolve_generate_config,
    resolve_inspect_model,
    validate_bridge_media,
    validate_client_config,
    withheld_bridge_tool,
)

logger = getLogger(__name__)


async def inspect_anthropic_api_request_impl(
    json_data: dict[str, Any],
    headers: dict[str, str] | None,
    web_search: WebSearchProviders | None,
    code_execution: CodeExecutionProviders | None,
    bridge: AgentBridge,
    *,
    beta: bool = False,
) -> Message | BetaMessage:
    # resolve model
    bridge_model_name = str(json_data["model"])
    model = resolve_inspect_model(bridge_model_name, bridge.model_aliases, bridge.model)

    # tools
    anthropic_tools: list[ToolParamDef] | None = json_data.get("tools", None)
    anthropic_mcp_servers: list[BetaRequestMCPServerURLDefinitionParam] | None = (
        json_data.get("mcp_servers", None)
    )
    # validate computer use compatibility
    has_computer_use = any(is_computer_tool(tool) for tool in anthropic_tools or [])
    if has_computer_use and ModelName(model).api != "anthropic":
        raise RuntimeError(
            f"computer use with the Anthropic agent bridge requires an "
            f"Anthropic model, got '{ModelName(model)}'"
        )

    tools = tools_from_anthropic_tools(
        anthropic_tools,
        anthropic_mcp_servers,
        web_search,
        code_execution,
        bridge.allow_remote_mcp,
    )

    # tool choice
    tool_choice = relax_tool_choice_for_withheld(
        tool_choice_from_anthropic_tool_choice(json_data.get("tool_choice", None)),
        tools,
    )

    # convert to inspect messages
    input: list[MessageParam] = json_data["messages"]
    debug_log("SCAFFOLD INPUT", input)

    messages = await messages_from_anthropic_input(input, tools)
    await validate_bridge_media(bridge, messages)
    debug_log("INSPECT MESSAGES", messages)

    # extract generate config (hoist instructions into system messages)
    config = generate_config_from_anthropic(json_data)
    if not bridge.forward_generation_config:
        clear_generation_params(config)
    validate_client_config(config)
    config.extra_headers = headers
    # Hoist the request's `system` value into leading system messages, ONE PER
    # ANTHROPIC BLOCK. Block boundaries are load-bearing: the API consumes a
    # system block whose text begins with an `x-anthropic-*-header:` line as
    # request metadata, so concatenating blocks can prepend such a header to a
    # real instruction block and the API then discards the whole block --
    # silently dropping the instructions. Observed with Claude Code's auto-mode
    # security classifier, which sends `system` as
    # [billing-header, monitor-prompt, session-context]: flattened, the 106k-char
    # prompt billed only 253 input tokens (i.e. never arrived), leaving the
    # classifier with no instructions and no verdict grammar.
    system_texts = anthropic_system_to_texts(json_data.get("system"))
    for offset, system_text in enumerate(system_texts):
        messages.insert(offset, ChatMessageSystem(content=system_text))

    # try to maintain id stability
    apply_message_ids(bridge, messages)

    # give inspect-level config priority over agent default config
    config = resolve_generate_config(model, config)

    # if there is a bridge filter give it a shot first
    output, c_message = await bridge_generate(
        bridge, model, messages, tools, tool_choice, config
    )
    if c_message is not None:
        messages.append(c_message)

    debug_log("INSPECT OUTPUT", output.message)

    # update state if we have more messages than the last generation
    await bridge._track_state(messages, output, str(ModelName(model)))

    # return message (use beta message type if request came from beta endpoint)
    message_class = BetaMessage if beta else Message
    message = message_class.model_construct(
        id=output.message.id or uuid(),
        content=await assistant_message_blocks(output.message, beta=beta),
        model=output.model,
        role="assistant",
        stop_reason=anthropic_stop_reason(output.stop_reason),
        type="message",
        usage=anthropic_usage(output.usage or ModelUsage(), beta=beta),
    )
    debug_log("SCAFFOLD RESPONSE", message)

    return message


def debug_log(caption: str, o: Any) -> None:
    # from inspect_ai._util.json import to_json_str_safe

    # print(caption)
    # print(to_json_str_safe(o))
    pass


def anthropic_system_to_texts(value: Any) -> list[str]:
    """Split an Anthropic ``system`` value into one text per block.

    ``system`` is either a plain string or a list of ``TextBlockParam``. Callers
    that turn these into Inspect system messages must preserve one entry per
    block rather than concatenating: the Anthropic API treats a system block
    beginning with an ``x-anthropic-*-header:`` line as request metadata and
    drops that block, so gluing a header block onto an instruction block causes
    the instructions to be discarded server-side.

    Empty blocks are omitted (they carry no instructions and would otherwise
    become empty system messages).
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    texts: list[str] = []
    for block in value:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = str(block.get("text", ""))
        if text:
            texts.append(text)
    return texts


def generate_config_from_anthropic(json_data: dict[str, Any]) -> GenerateConfig:
    config = GenerateConfig()
    config.max_tokens = json_data.get("max_tokens", None)
    config.stop_seqs = json_data.get("stop_sequences", None) or None
    config.temperature = json_data.get("temperature", None)
    config.top_k = json_data.get("top_k", None)
    config.top_p = json_data.get("top_p", None)

    thinking = client_request_object(json_data.get("thinking", None), "thinking")
    if thinking:
        if thinking.get("type", None) == "enabled":
            config.reasoning_tokens = thinking.get("budget_tokens", None)

    # `output_config.effort` carries the reasoning depth for adaptive thinking
    # (Claude 4.6+ clients send `thinking: {"type": "adaptive"}` and convey the
    # depth here rather than via `budget_tokens`). Forward it so the served model
    # keeps the requested effort instead of silently dropping it.
    output_config = client_request_object(
        json_data.get("output_config", None), "output_config"
    )
    if output_config:
        effort = output_config.get("effort", None)
        if effort is not None:
            config.effort = effort

        # `output_config.format` is Anthropic's native structured-output request.
        # The provider already sends `config.response_schema` as the
        # `output_format` extra_body field under the structured-outputs beta, so
        # the schema only needs mapping onto it -- the same mapping the OpenAI
        # (`response_format`/`text.format`) and Google (`responseJsonSchema`)
        # paths already do. Without it a client asking for JSON silently gets
        # prose, which fails a JSON-field extractor as "no candidate" rather
        # than as an error.
        output_format = client_request_object(
            output_config.get("format", None), "output_config.format"
        )
        if output_format and output_format.get("type") == "json_schema":
            schema = output_format.get("schema", None)
            if schema is not None:
                # `ResponseSchema` validates `name` on construction, so a
                # non-string one escapes as a raw `ValidationError` -- the
                # status-less failure `client_json_schema` exists to prevent.
                # Route it to the same 400 the real API answers.
                # Type-check before applying the default so a falsy
                # non-string (`0`, `false`) is rejected like any other
                # non-string rather than silently becoming "response".
                name = output_format.get("name", None)
                if name is not None and not isinstance(name, str):
                    raise BridgePolicyError(
                        "invalid response schema in bridged request "
                        "(output_config.format.name: input should be a valid "
                        f"string, got {type(name).__name__})"
                    )
                name = name or "response"
                config.response_schema = ResponseSchema(
                    name=name,
                    # NOTE: Inspect's `JSONSchema` does not model every keyword
                    # Anthropic's structured outputs accept (`allOf`, `const`,
                    # `$ref`/`$defs`, `minItems`), and unmodelled keywords are
                    # dropped rather than rejected -- so a schema using them is
                    # forwarded weaker than the client asked for.
                    # `client_json_schema` warns when that happens; see its
                    # docstring for why dropping beats a 400 here.
                    json_schema=client_json_schema(
                        schema, "output_config.format.schema"
                    ),
                )

    tool_choice = (
        client_request_object(json_data.get("tool_choice", None), "tool_choice") or {}
    )
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
    web_search_providers: WebSearchProviders | None,
    code_execution_providers: CodeExecutionProviders | None,
    allow_remote_mcp: bool,
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
            if web_search_providers is None:
                withheld_bridge_tool("web_search")
            else:
                tools.append(
                    web_search(
                        resolve_web_search_providers(
                            anthropic_tool, web_search_providers
                        )
                    )
                )
        elif is_web_fetch_tool(anthropic_tool):
            # Inspect has no standalone fetch tool: on Anthropic, fetch rides
            # along with a granted web_search (the provider emits both), so a
            # declaration of it maps to nothing of its own. A client that
            # declares fetch *without* search therefore gets no web tool even
            # when search is granted — mapping it to web_search would hand it
            # the search capability it didn't ask for.
            if web_search_providers is None:
                withheld_bridge_tool("web_fetch")
        elif is_code_execution_tool(anthropic_tool):
            if code_execution_providers is None:
                withheld_bridge_tool("code_execution")
            else:
                tools.append(code_execution(providers=code_execution_providers))
        elif is_bash_tool(anthropic_tool):
            tools.append(bash())
        else:
            raise RuntimeError(
                f"ToolParam of type {anthropic_tool['type']} not supported by agent bridge."
            )

    if anthropic_mcp_servers and not allow_remote_mcp:
        withheld_bridge_tool("mcp_servers")
        anthropic_mcp_servers = None

    for mcp_server in anthropic_mcp_servers or []:
        # allowed tools (default is 'all')
        tool_configuration: BetaRequestMCPServerToolConfigurationParam = (
            mcp_server.get(
                "tool_configuration", BetaRequestMCPServerToolConfigurationParam()
            )
            or BetaRequestMCPServerToolConfigurationParam()
        )
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
    tool_param: WebSearchTool20250305Param | WebSearchTool20260209Param,
    web_search: WebSearchProviders,
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
    tool_choice: Any,
) -> ToolChoice | None:
    # `Any` rather than `ToolChoiceParam`: the value is client-controlled JSON,
    # and this converter runs before `generate_config_from_anthropic` on the
    # request path -- so its guard must fire here, before the first subscript,
    # for a mistyped container to 400 rather than escape as a raw `TypeError`.
    tool_choice = client_request_object(tool_choice, "tool_choice")
    if tool_choice is None:
        return None

    match tool_choice.get("type", None):
        case "any":
            return "any"
        case "auto":
            return "auto"
        case "none":
            return "none"
        case "tool":
            return ToolFunction(
                name=client_request_string(
                    tool_choice.get("name", None), "tool_choice.name"
                )
            )
        case invalid:
            # A missing or unknown `type` previously fell through silently
            # (or raised a status-less `KeyError`); answer the 400 the real
            # API gives rather than ignoring the client's stated intent.
            raise BridgePolicyError(
                "invalid request field in bridged request (tool_choice.type: "
                f"expected one of 'any', 'auto', 'none', 'tool', got {invalid!r})"
            )


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
                        content_value = c.get("content")
                        if content_value is None:
                            content: str | list[Content] = ""
                        elif isinstance(content_value, str):
                            content = content_value
                        else:
                            content = [
                                content_block_to_content(b) for b in content_value
                            ]
                        messages.append(
                            ChatMessageTool(
                                tool_call_id=c["tool_use_id"],
                                function=tool_names.get(c["tool_use_id"], None),
                                content=content,
                                error=ToolCallError(
                                    type="unknown",
                                    message=str(content_value) if content_value else "",
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
                        raise RuntimeError(f"Unexpected input parameter: {c}")

                flush_pending_user_content()

        elif param["role"] == "system":
            messages.extend(
                ChatMessageSystem(content=text)
                for text in anthropic_system_to_texts(param["content"])
            )

        else:
            raise RuntimeError(f"Unexpected message role: {param['role']}")

    return messages


def content_block_to_content(
    block: TextBlockParam
    | ImageBlockParam
    | DocumentBlockParam
    | SearchResultBlockParam
    | ToolReferenceBlockParam
    | BrowserStateBlockParam,
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
        elif block["source"]["type"] == "url":
            return ContentImage(image=block["source"]["url"])
        else:
            raise RuntimeError(
                f"Unsupported image source type: {block['source']['type']}"
            )
    elif block["type"] == "document":
        source = block["source"]
        if source["type"] == "text":
            data = base64.b64encode(source["data"].encode("utf-8")).decode("ascii")
            return ContentDocument(
                document=as_data_uri(source["media_type"], data),
                mime_type=source["media_type"],
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
            raise RuntimeError(f"Unsupported document source type: {source['type']}")
    else:
        raise RuntimeError(f"Unsupported content block type: {block['type']}")


def base_64_data(data: str | IO[bytes] | PathLike[str]) -> str:
    if isinstance(data, io.IOBase):
        data = base64.b64encode(data.read()).decode("utf-8")
    if isinstance(data, str):
        return data
    else:
        raise RuntimeError(f"Unsupported image content type: {data}")


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


def anthropic_usage(usage: ModelUsage, beta: bool = False) -> Usage | BetaUsage:
    """Convert inspect-level usage to the Anthropic usage type matching the endpoint.

    Beta requests must carry `BetaUsage`: clients reading beta-only fields
    (e.g. pydantic-ai reads `usage.iterations`) fail on a plain `Usage`.
    """
    reasoning_tokens = usage.reasoning_tokens
    if beta:
        return BetaUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=usage.input_tokens_cache_write,
            cache_read_input_tokens=usage.input_tokens_cache_read,
            output_tokens_details=BetaOutputTokensDetails(
                thinking_tokens=reasoning_tokens
            )
            if reasoning_tokens is not None
            else None,
        )
    else:
        return Usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=usage.input_tokens_cache_write,
            cache_read_input_tokens=usage.input_tokens_cache_read,
            output_tokens_details=OutputTokensDetails(thinking_tokens=reasoning_tokens)
            if reasoning_tokens is not None
            else None,
        )
