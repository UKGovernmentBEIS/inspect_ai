"""Wire-format tests for the vendored JSON-RPC models.

The injectable does not bundle mcp; the host does. These tests pin the two
places drift could break the relay silently:

- parity: the host serializes its installed mcp models into the launch/relay
  RPCs, and the injectable validates them with the vendored models (and vice
  versa for responses). Round-tripping through the real installed mcp catches
  a future mcp release changing its serialization.
- envelope behavior the vendored models own outright: non-spec extras
  round-trip, and nonconforming request/response ids fail validation (so the
  reader skips the line) while error-envelope ids coerce laxly, matching the
  mcp 1.x models the v27 binary shipped.
"""

import pydantic
import pytest
from inspect_sandbox_tools._remote_tools._mcp.jsonrpc_types import (
    ErrorData,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    StdioServerParameters,
    jsonrpc_message_adapter,
)

mcp = pytest.importorskip("mcp", reason="parity tests need the host's mcp")


def test_request_parity_host_to_vendored() -> None:
    host_request = mcp.JSONRPCRequest(
        jsonrpc="2.0", id=7, method="tools/call", params={"name": "x"}
    )
    wire = host_request.model_dump_json(by_alias=True, exclude_none=True)
    vendored = JSONRPCRequest.model_validate_json(wire)
    assert vendored.model_dump_json(by_alias=True, exclude_none=True) == wire


def test_notification_parity_host_to_vendored() -> None:
    host_notification = mcp.types.JSONRPCNotification(
        jsonrpc="2.0", method="notifications/initialized"
    )
    wire = host_notification.model_dump_json(by_alias=True, exclude_none=True)
    vendored = JSONRPCNotification.model_validate_json(wire)
    assert vendored.model_dump_json(by_alias=True, exclude_none=True) == wire


def test_stdio_server_parameters_parity_host_to_vendored() -> None:
    host_params = mcp.StdioServerParameters(
        command="server", args=["--flag"], env={"K": "V"}, cwd="/work"
    )
    vendored = StdioServerParameters.model_validate_json(host_params.model_dump_json())
    assert vendored.model_dump() == host_params.model_dump()


def test_response_parity_vendored_to_host() -> None:
    wire = JSONRPCResponse(jsonrpc="2.0", id=7, result={"ok": True}).model_dump_json(
        by_alias=True, exclude_none=True
    )
    assert mcp.types.JSONRPCResponse.model_validate_json(wire).result == {"ok": True}


def test_error_parity_vendored_to_host() -> None:
    wire = JSONRPCError(
        jsonrpc="2.0", id=7, error=ErrorData(code=-32000, message="boom")
    ).model_dump_json(by_alias=True, exclude_none=True)
    assert mcp.types.JSONRPCError.model_validate_json(wire).error.code == -32000


def test_envelope_extras_round_trip() -> None:
    line = '{"jsonrpc":"2.0","id":1,"result":{"ok":true},"vendor_ext":"x"}'
    message = jsonrpc_message_adapter.validate_json(line)
    assert isinstance(message, JSONRPCResponse)
    assert "vendor_ext" in message.model_dump_json(by_alias=True, exclude_none=True)


@pytest.mark.parametrize("bad_id", ["7.0", "true"])
def test_nonconforming_result_ids_fail_validation(bad_id: str) -> None:
    # The reader skips unparseable lines; a float or bool id must not coerce
    # into (or hijack) a pending int-id request.
    line = f'{{"jsonrpc":"2.0","id":{bad_id},"result":{{}}}}'
    with pytest.raises(pydantic.ValidationError):
        jsonrpc_message_adapter.validate_json(line)


@pytest.mark.parametrize(("lax_id", "expected"), [("7.0", 7), ("true", 1)])
def test_error_envelope_id_is_lax(lax_id: str, expected: int) -> None:
    # mcp 1.x (as shipped in v27) coerced float-integral and bool ids on the
    # error envelope only; a late error for request 7 sent as 7.0 must
    # correlate, and the coerced value must be a true int (not bool) so the
    # host's strict mcp models accept the relayed envelope.
    message = jsonrpc_message_adapter.validate_json(
        f'{{"jsonrpc":"2.0","id":{lax_id},"error":{{"code":-32000,"message":"boom"}}}}'
    )
    assert isinstance(message, JSONRPCError)
    assert message.id == expected and type(message.id) is int
