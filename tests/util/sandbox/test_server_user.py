import json
from unittest.mock import AsyncMock, MagicMock

from inspect_ai.util._sandbox._json_rpc_transport import SandboxJSONRPCTransport


async def test_transport_uses_server_user_for_exec():
    """When server_user is set, CLI runs as server_user."""
    sandbox = MagicMock()
    sandbox._server_user = "root"
    sandbox.exec = AsyncMock(
        return_value=MagicMock(
            success=True, stdout='{"jsonrpc":"2.0","id":1,"result":{}}'
        )
    )

    transport = SandboxJSONRPCTransport(sandbox, "/opt/inspect-sandbox-tools")
    await transport(
        method="test_method",
        params={"command": "echo hello"},
        is_notification=False,
        user="agent_user",
    )

    call_kwargs = sandbox.exec.call_args
    assert call_kwargs.kwargs.get("user") == "root"


async def test_transport_does_not_inject_user_into_params():
    """Transport must not add user to RPC params (methods have extra=forbid)."""
    sandbox = MagicMock()
    sandbox._server_user = "root"
    sandbox.exec = AsyncMock(
        return_value=MagicMock(
            success=True, stdout='{"jsonrpc":"2.0","id":1,"result":{}}'
        )
    )

    transport = SandboxJSONRPCTransport(sandbox, "/opt/inspect-sandbox-tools")
    await transport(
        method="bash_session_interact",
        params={"session_name": "default", "input": "ls"},
        is_notification=False,
        user="agent_user",
    )

    call_kwargs = sandbox.exec.call_args
    rpc_input = call_kwargs.kwargs.get("input")
    rpc_body = json.loads(rpc_input)
    assert "user" not in rpc_body["params"]


async def test_transport_no_server_user_backward_compat():
    """Without server_user, transport behaves as before."""
    sandbox = MagicMock()
    sandbox._server_user = None
    sandbox.exec = AsyncMock(
        return_value=MagicMock(
            success=True, stdout='{"jsonrpc":"2.0","id":1,"result":{}}'
        )
    )

    transport = SandboxJSONRPCTransport(sandbox, "/opt/inspect-sandbox-tools")
    await transport(
        method="test_method",
        params={"command": "echo hello"},
        is_notification=False,
        user="agent_user",
    )

    call_kwargs = sandbox.exec.call_args
    assert call_kwargs.kwargs.get("user") == "agent_user"
