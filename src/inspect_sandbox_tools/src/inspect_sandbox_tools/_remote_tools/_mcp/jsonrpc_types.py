"""Vendored JSON-RPC 2.0 envelope models (https://www.jsonrpc.org/specification).

These models (plus ``StdioServerParameters``) are the only things this package
ever used from the mcp SDK — the injectable is a stdio envelope relay, with all
MCP protocol logic living host-side. Vendoring them removes the mcp dependency
entirely: the JSON-RPC 2.0 wire format is frozen, so these never need porting
across mcp majors, and the SDK's dependency tree stays out of the PyInstaller
bundle.

Wire behavior intentionally matches the mcp 1.x models the v27 binary shipped:
ids validate strictly (a nonconforming line with a float or bool id fails
validation and is skipped by the reader, like any other unparseable line) and
non-spec extra fields on envelopes round-trip to the host instead of being
stripped (``extra="allow"``).
"""

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, Strict, TypeAdapter

RequestId = Annotated[int, Strict()] | str


class _JSONRPCEnvelope(BaseModel):
    """Base for envelope models: round-trip non-spec extra fields."""

    model_config = ConfigDict(extra="allow")


class ErrorData(_JSONRPCEnvelope):
    code: int
    message: str
    data: Any = None


class JSONRPCRequest(_JSONRPCEnvelope):
    jsonrpc: Literal["2.0"]
    id: RequestId
    method: str
    params: dict[str, Any] | None = None


class JSONRPCNotification(_JSONRPCEnvelope):
    jsonrpc: Literal["2.0"]
    method: str
    params: dict[str, Any] | None = None


class JSONRPCResponse(_JSONRPCEnvelope):
    jsonrpc: Literal["2.0"]
    id: RequestId
    result: dict[str, Any]


class JSONRPCError(_JSONRPCEnvelope):
    jsonrpc: Literal["2.0"]
    # Required but nullable per JSON-RPC 2.0: None encodes "id": null (the
    # server could not determine the id, e.g. a parse-error response).
    id: RequestId | None
    error: ErrorData


# Union order matches mcp's JSONRPCMessage. With extra="allow" the order is
# observable: a nonconforming line carrying both "method" and "result" validates
# as the leftmost match (JSONRPCRequest) and is dropped as unsolicited, same as
# the shipped mcp 1.x binary behaved.
JSONRPCMessage = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError

jsonrpc_message_adapter: TypeAdapter[JSONRPCMessage] = TypeAdapter(JSONRPCMessage)


class StdioServerParameters(BaseModel):
    """The subset of launch parameters the host sends for an MCP server process.

    Field names and defaults mirror ``mcp.StdioServerParameters``, which the
    host serializes into the launch RPC.
    """

    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | Path | None = None
    encoding: str = "utf-8"
    encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict"
