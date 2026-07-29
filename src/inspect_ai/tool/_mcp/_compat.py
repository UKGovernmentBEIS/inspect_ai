"""Compatibility layer spanning mcp 1.x and 2.x.

mcp 2.0 is a hard-breaking API redesign with no deprecation aliases:

- ``McpError`` was renamed to ``MCPError`` and its constructor changed from
  ``McpError(ErrorData(...))`` to ``MCPError(code, message, data)`` (the
  ``.error`` attribute is present on both).
- ``streamablehttp_client`` was renamed to ``streamable_http_client``, and its
  ``headers``/``timeout``/``sse_read_timeout`` parameters were replaced by a
  caller-supplied ``httpx2.AsyncClient``.
- ``read_timeout_seconds`` (on ``ClientSession.__init__`` and ``call_tool``)
  changed from ``datetime.timedelta`` to ``float``.
- The error code carried by the ``McpError`` raised when a read timeout
  expires changed from HTTP 408 to JSON-RPC -32001.
- All camelCase pydantic model fields were renamed to snake_case
  (``isError`` -> ``is_error``, ``inputSchema`` -> ``input_schema``, ...).
  ``model_validate`` still accepts the camelCase alias on 2.x, but attribute
  *reads* raise ``AttributeError`` (so reads go through the accessors below)
  and 2.x constructor keywords are snake_case-only under mypy (so
  constructions go through the ``model_validate``-based factories below).
- ``JSONRPCMessage`` changed from a ``RootModel`` wrapper class to a plain
  union type alias: ``SessionMessage.message`` no longer has ``.root``, the
  alias is not constructible, and it has no ``model_validate``.

Version-specific attributes are resolved dynamically (``getattr`` /
``importlib.import_module``) rather than via try/except imports: mypy runs
with ``warn_unused_ignores`` against whichever mcp happens to be installed,
so any version-dependent ``# type: ignore`` would fail the check under the
other version.
"""

import importlib
from contextlib import asynccontextmanager
from datetime import timedelta
from importlib.metadata import version as _package_version
from typing import Any, AsyncIterator, cast

from mcp.types import (
    AudioContent,
    CallToolResult,
    CreateMessageRequestParams,
    CreateMessageResult,
)
from mcp.types import ImageContent as MCPImageContent
from mcp.types import Tool as MCPTool

MCP_V2: bool = int(_package_version("mcp").split(".")[0]) >= 2

McpError: type[Any] = getattr(
    importlib.import_module("mcp.shared.exceptions"),
    "MCPError" if MCP_V2 else "McpError",
)

# Error code carried by the McpError that `ClientSession` raises when a
# `read_timeout_seconds` deadline expires while awaiting a response: mcp 1.x
# uses HTTP 408 (httpx.codes.REQUEST_TIMEOUT), mcp 2.x uses JSON-RPC -32001
# (REQUEST_TIMEOUT). Gated on the installed major — which determines the only
# code the client itself can raise — so a *server-originated* error that
# happens to use the other code (e.g. -32001 sits in JSON-RPC's
# implementation-defined server-error range, which real servers use) still
# flows through the error mapper with its own message rather than being
# misreported as a client read timeout.
MCP_READ_TIMEOUT_CODES = (-32001,) if MCP_V2 else (408,)


def read_timeout_arg(seconds: float | None) -> Any:
    """Value to pass as `read_timeout_seconds` (timedelta on 1.x, float on 2.x)."""
    if seconds is None:
        return None
    return float(seconds) if MCP_V2 else timedelta(seconds=seconds)


@asynccontextmanager
async def streamablehttp_client(
    url: str,
    headers: dict[str, str] | None,
    timeout: float,
    sse_read_timeout: float,
) -> AsyncIterator[Any]:
    """Streamable HTTP client transport for either mcp major version.

    On 2.x, HTTP configuration moves into a caller-supplied httpx2 client;
    `create_mcp_http_client` applies the same MCP-recommended defaults that
    the 1.x transport applied internally via its client factory.
    `streamable_http_client` does not close a client it did not create, so
    the client's lifetime is owned here.
    """
    transport = importlib.import_module("mcp.client.streamable_http")
    if MCP_V2:
        httpx2 = importlib.import_module("httpx2")
        async with transport.create_mcp_http_client(
            headers=headers,
            timeout=httpx2.Timeout(timeout, read=sse_read_timeout),
        ) as http_client:
            async with transport.streamable_http_client(
                url, http_client=http_client
            ) as streams:
                yield streams
    else:
        async with transport.streamablehttp_client(
            url, headers, timeout, sse_read_timeout
        ) as streams:
            yield streams


_mcp_types = importlib.import_module("mcp.types")

# BaseModel class that validates a JSON-RPC message payload. On 1.x this is
# `JSONRPCMessage` itself (a RootModel); on 2.x — where `JSONRPCMessage` is a
# bare union alias with no `model_validate` — it is a RootModel over that
# union. Either way the validated instance exposes the concrete message via
# `.root`.
if MCP_V2:
    from pydantic import RootModel

    # parametrized via method call rather than subscript: in a subscript
    # expression mypy treats the argument as a type and rejects the
    # dynamically-resolved union alias
    JSONRPC_MESSAGE_VALIDATOR: type[Any] = cast(
        "type[Any]", RootModel.__class_getitem__(_mcp_types.JSONRPCMessage)
    )
else:
    JSONRPC_MESSAGE_VALIDATOR = _mcp_types.JSONRPCMessage


def jsonrpc_message(concrete: Any) -> Any:
    """Value for `SessionMessage.message` given a concrete JSON-RPC model.

    1.x wraps the concrete model in the `JSONRPCMessage` RootModel; on 2.x the
    concrete model is the message.
    """
    if MCP_V2:
        return concrete
    return _mcp_types.JSONRPCMessage(concrete)


def jsonrpc_message_root(message: Any) -> Any:
    """Concrete JSON-RPC model from `SessionMessage.message`."""
    return getattr(message, "root", message)


def tool_input_schema(tool: MCPTool) -> dict[str, Any]:
    schema: dict[str, Any] = getattr(tool, "input_schema" if MCP_V2 else "inputSchema")
    return schema


def result_is_error(result: CallToolResult) -> bool:
    is_error: bool = getattr(result, "is_error" if MCP_V2 else "isError")
    return is_error


def params_system_prompt(params: CreateMessageRequestParams) -> str | None:
    system_prompt: str | None = getattr(
        params, "system_prompt" if MCP_V2 else "systemPrompt"
    )
    return system_prompt


def params_max_tokens(params: CreateMessageRequestParams) -> int:
    max_tokens: int = getattr(params, "max_tokens" if MCP_V2 else "maxTokens")
    return max_tokens


def params_stop_sequences(params: CreateMessageRequestParams) -> list[str] | None:
    stop_sequences: list[str] | None = getattr(
        params, "stop_sequences" if MCP_V2 else "stopSequences"
    )
    return stop_sequences


def content_mime_type(content: MCPImageContent | AudioContent) -> str:
    mime_type: str = getattr(content, "mime_type" if MCP_V2 else "mimeType")
    return mime_type


def create_message_result(
    *, content: Any, model: str, stop_reason: Any
) -> CreateMessageResult:
    """Construct an assistant CreateMessageResult.

    Constructed via model_validate because keyword construction is
    version-specific: 1.x accepts only the camelCase field names, 2.x's
    generated __init__ only the snake_case ones — but model_validate accepts
    the camelCase spelling on both (as field name on 1.x, alias on 2.x).
    """
    return CreateMessageResult.model_validate(
        {
            "role": "assistant",
            "content": content,
            "model": model,
            "stopReason": stop_reason,
        }
    )


def image_content(*, mime_type: str, data: str) -> MCPImageContent:
    """Construct an ImageContent (see create_message_result on why model_validate)."""
    return MCPImageContent.model_validate(
        {"type": "image", "mimeType": mime_type, "data": data}
    )
