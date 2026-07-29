"""Regression test for sandbox MCP `call_tool` timeout handling.

A sandbox MCP `call_tool` whose response never arrives must time out (raising,
convertible to ToolError) instead of deadlocking forever.

Repro of the production hang: the sandbox carrier exec times out at the OS level
but its JSON-RPC error never wakes the host-side `ClientSession.call_tool` await,
so the tool call hangs for hours, ignoring the per-RPC `mcp_timeout`. The fix
passes `read_timeout_seconds` to `call_tool` so `ClientSession` bounds the wait,
and translates the resulting request-timeout `McpError` (HTTP 408 on mcp 1.x,
JSON-RPC -32001 on 2.x) into a `ToolError` so the model is notified rather than
the sample erroring out.
"""

from datetime import timedelta

import anyio
import httpx
import pytest

pytest.importorskip("mcp")  # mcp is a dev-only dependency

from inspect_ai.tool import ToolError  # noqa: E402
from inspect_ai.tool._mcp._compat import MCP_V2, McpError  # noqa: E402
from inspect_ai.tool._mcp._local import (  # noqa: E402
    MCPServerLocal,
    MCPServerLocalSession,
    create_server_sandbox,
)
from inspect_ai.tool._mcp._sandbox import DEFAULT_SANDBOX_TIMEOUT  # noqa: E402


def _read_timeout_error() -> Exception:
    """The error mcp raises when read_timeout_seconds expires.

    mcp 1.x raises McpError(ErrorData(code=408)) (httpx.codes.REQUEST_TIMEOUT);
    mcp 2.x raises MCPError(code=-32001) (JSON-RPC REQUEST_TIMEOUT).
    """
    message = "Timed out while waiting for response to CallToolRequest."
    if MCP_V2:
        return McpError(-32001, message)
    else:
        from mcp.types import ErrorData

        return McpError(
            ErrorData(code=int(httpx.codes.REQUEST_TIMEOUT), message=message)
        )


class _NeverRespondsSession:
    """Stand-in ClientSession that never receives a response.

    Honours read_timeout_seconds but never receives a response — mirroring a
    lost transport reply.
    """

    async def call_tool(self, name, arguments=None, *, read_timeout_seconds=None, **kw):
        # Faithfully model mcp.ClientSession: bound the wait with the supplied
        # read timeout (timedelta on mcp 1.x, float on 2.x) and, on expiry,
        # raise the same request-timeout error mcp's send_request raises.
        if read_timeout_seconds is None:
            await anyio.sleep_forever()  # the OLD behaviour: hang forever
        seconds = (
            read_timeout_seconds.total_seconds()
            if isinstance(read_timeout_seconds, timedelta)
            else read_timeout_seconds
        )
        try:
            with anyio.fail_after(seconds):
                await anyio.sleep_forever()
        except TimeoutError as ex:
            raise _read_timeout_error() from ex


async def _run(timeout):
    session = MCPServerLocalSession(
        client=lambda: None, name="exploit", events=False, timeout=timeout
    )
    session._session = _NeverRespondsSession()  # inject the fake
    session._refcount = 1

    # build a ToolDef for a fake tool and call its execute()
    from mcp.types import Tool as MCPTool

    # model_validate because keyword construction with the camelCase alias
    # (inputSchema=...) fails mypy under mcp 2.x (see test_mcp_tools.py)
    tool = MCPTool.model_validate(
        {
            "name": "grade",
            "description": "",
            "inputSchema": {"type": "object", "properties": {}},
        }
    )
    tool_def = session._tool_def_from_mcp_tool(tool)
    return await tool_def.tool()  # invoke execute()


@pytest.mark.anyio
async def test_call_tool_times_out_instead_of_hanging():
    # With a finite timeout, the call must raise quickly — NOT hang.
    with anyio.fail_after(10):  # test-level guard: if the fix regresses, fail loudly
        with pytest.raises(ToolError) as ei:
            await _run(timeout=1)
    # The 408 timeout must surface as a ToolError the model can see — not the
    # RuntimeError that exception_for_rpc_response_error produces for an
    # unrecognized code (which would error the sample instead).
    assert "timed out" in str(ei.value).lower()


def test_create_server_sandbox_bounds_host_read_timeout_by_default():
    # A default (timeout=None) sandbox server must still get a finite host-side
    # read timeout, otherwise a lost transport response deadlocks the call.
    server = create_server_sandbox(name="srv", command="cmd")
    assert isinstance(server, MCPServerLocal)
    assert server._timeout == DEFAULT_SANDBOX_TIMEOUT

    # An explicit timeout is threaded through unchanged.
    server = create_server_sandbox(name="srv", command="cmd", timeout=42)
    assert isinstance(server, MCPServerLocal)
    assert server._timeout == 42


@pytest.fixture
def anyio_backend():
    return "asyncio"
