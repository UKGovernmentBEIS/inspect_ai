from collections.abc import Mapping
from logging import Filter, LogRecord, getLogger
from types import TracebackType
from typing import Any

from typing_extensions import override

from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import MCP_SERVER_TOOL_PREFIX, REDACTED, ToolInfo

from .._tool import Tool, ToolResult
from ._config import (
    MCPServerConfigHTTP,
    authorization_header_values,
    strip_bearer,
)
from ._types import MCPServer


class MCPServerRemote(MCPServer):
    def __init__(self, config: MCPServerConfigHTTP) -> None:
        self._config = config

    @override
    async def tools(self) -> list[Tool]:
        return [mcp_server_tool(self._config)]

    # no-op async context manager as we don't manage resources
    @override
    async def __aenter__(self) -> MCPServer:
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass


def mcp_server_tool(config: MCPServerConfigHTTP) -> Tool:
    async def execute() -> ToolResult:
        raise RuntimeError("MCPServerTool should not be called directly")

    name = f"{MCP_SERVER_TOOL_PREFIX}{config.name}"

    return ToolDef(
        execute,
        name=name,
        description=name,
        options=config.model_dump(),
    ).as_tool()


def is_mcp_server_tool(tool: ToolInfo) -> bool:
    return tool.name.startswith(MCP_SERVER_TOOL_PREFIX) and tool.options is not None


def mcp_server_config(tool: ToolInfo) -> MCPServerConfigHTTP:
    """The remote MCP server config carried by an MCP server tool.

    Raises:
        ValueError: If the server's credentials were redacted (e.g. the
            `ToolInfo` was read back from an eval log), rather than sending the
            redaction marker to the server as a credential.
    """
    config = MCPServerConfigHTTP.model_validate(tool.options)
    redacted = [
        name for name, value in (config.headers or {}).items() if value == REDACTED
    ]
    # the agent bridge sends a recorded `authorization_token` as "BEARER <token>"
    if not any(name.lower() == "authorization" for name in redacted) and any(
        strip_bearer(value) == REDACTED
        for value in authorization_header_values(config.headers)
    ):
        redacted.append("Authorization")
    if redacted:
        raise ValueError(
            f"Remote MCP server '{config.name}' has redacted credentials "
            f"(headers: {', '.join(redacted)}). Its tool definition was likely read "
            "from an eval log, which doesn't record MCP server credentials. Pass "
            "the server (e.g. `mcp_server_http()`) to generate instead."
        )
    return config


def redact_anthropic_mcp_servers(request: dict[str, Any]) -> dict[str, Any]:
    """Anthropic request with `mcp_servers[].authorization_token` redacted.

    Handles `mcp_servers` at the top level and under `extra_body`. Returns
    `request` itself when there is nothing to redact; otherwise a copy (the
    request sent to the provider is never modified).
    """

    def redact_servers(servers: Any) -> Any:
        if not isinstance(servers, list) or not any(
            isinstance(s, dict) and s.get("authorization_token") for s in servers
        ):
            return servers
        return [
            s | {"authorization_token": REDACTED}
            if isinstance(s, dict) and s.get("authorization_token")
            else s
            for s in servers
        ]

    redacted = request
    servers = request.get("mcp_servers")
    if (new_servers := redact_servers(servers)) is not servers:
        redacted = redacted | {"mcp_servers": new_servers}
    extra_body = request.get("extra_body")
    if isinstance(extra_body, dict):
        servers = extra_body.get("mcp_servers")
        if (new_servers := redact_servers(servers)) is not servers:
            redacted = redacted | {
                "extra_body": extra_body | {"mcp_servers": new_servers}
            }
    return redacted


def redact_responses_mcp_tools(request: dict[str, Any]) -> dict[str, Any]:
    """OpenAI Responses request with `tools[type=mcp]` header values redacted.

    Returns `request` itself when there is nothing to redact; otherwise a copy
    (the request sent to the provider is never modified).
    """

    def has_headers(tool: Any) -> bool:
        return (
            isinstance(tool, dict)
            and tool.get("type") == "mcp"
            and isinstance(tool.get("headers"), dict)
            and len(tool["headers"]) > 0
        )

    tools = request.get("tools")
    if not isinstance(tools, list) or not any(has_headers(t) for t in tools):
        return request
    return request | {
        "tools": [
            t | {"headers": {k: REDACTED for k in t["headers"]}}
            if has_headers(t)
            else t
            for t in tools
        ]
    }


def redact_grok_mcp_tools(request: dict[str, Any]) -> dict[str, Any]:
    """Grok request with `tools[].mcp` `authorization` and `extraHeaders` redacted.

    Returns `request` itself when there is nothing to redact; otherwise a copy
    (the request sent to the provider is never modified).
    """

    def redact(tool: Any) -> Any:
        mcp = tool.get("mcp") if isinstance(tool, dict) else None
        if not isinstance(mcp, dict):
            return tool
        redacted = mcp
        if mcp.get("authorization"):
            redacted = redacted | {"authorization": REDACTED}
        if isinstance(headers := mcp.get("extraHeaders"), dict) and headers:
            redacted = redacted | {"extraHeaders": {k: REDACTED for k in headers}}
        return tool if redacted is mcp else tool | {"mcp": redacted}

    tools = request.get("tools")
    if not isinstance(tools, list):
        return request
    new_tools = [redact(t) for t in tools]
    if all(new is old for new, old in zip(new_tools, tools)):
        return request
    return request | {"tools": new_tools}


class _AnthropicRequestOptionsRedactor(Filter):
    """Redacts MCP tokens in the Anthropic SDK's "Request options" debug record.

    At debug level the SDK logs each request's options, and Inspect captures
    debug records into the eval log. The request sent is not modified.
    """

    def filter(self, record: LogRecord) -> bool:
        # a single mapping argument is stored as `record.args` itself
        options = record.args
        if record.msg != "Request options: %s" or not isinstance(options, Mapping):
            return True
        redacted = dict(options)
        for key in ("json_data", "extra_json"):
            value = options.get(key)
            if isinstance(value, dict):
                redacted[key] = redact_anthropic_mcp_servers(value)
        if any(redacted[key] is not options[key] for key in options):
            record.args = redacted
        return True


_anthropic_request_options_redactor = _AnthropicRequestOptionsRedactor()


def redact_anthropic_sdk_debug_log() -> None:
    """Install the redactor on the Anthropic SDK's request logger (idempotent)."""
    getLogger("anthropic._base_client").addFilter(_anthropic_request_options_redactor)
