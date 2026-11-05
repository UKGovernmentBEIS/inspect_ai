"""Regression tests for MCPServerSession's stdout reader.

The reader must tolerate lines it cannot dispatch — an unsolicited
notification, an uncorrelatable null-id error response — rather than crash: a
dead reader fails every pending request. The test feeds the unexpected line
ahead of a normal response and asserts the matching request still resolves.
"""

import asyncio

import pytest
from inspect_sandbox_tools._remote_tools._mcp.jsonrpc_types import (
    JSONRPCRequest,
    JSONRPCResponse,
)
from inspect_sandbox_tools._remote_tools._mcp.mcp_server_session import (
    MCPServerSession,
)

from .mcp_session_fakes import FakeProcess


@pytest.mark.parametrize(
    "unexpected_line",
    [
        pytest.param(
            b'{"jsonrpc":"2.0","method":"notifications/tools/list_changed","params":{}}\n',
            id="unsolicited-notification",
        ),
        pytest.param(
            b'{"jsonrpc":"2.0","id":null,'
            b'"error":{"code":-32700,"message":"parse error"}}\n',
            id="null-id-error",
        ),
    ],
)
async def test_unexpected_line_does_not_kill_reader(unexpected_line: bytes) -> None:
    reader = asyncio.StreamReader()
    session = MCPServerSession(FakeProcess(reader), "utf-8", "strict")
    try:
        # The unexpected line arrives before the response we are waiting on.
        reader.feed_data(unexpected_line)

        async def feed_response() -> None:
            await asyncio.sleep(0.05)
            reader.feed_data(b'{"jsonrpc":"2.0","id":7,"result":{"tools":[]}}\n')

        # Hold a reference: the event loop keeps only a weak ref to tasks.
        feeder = asyncio.create_task(feed_response())
        request = JSONRPCRequest(jsonrpc="2.0", id=7, method="tools/list", params={})

        # If the reader died on the unexpected line, this would never resolve
        # (or send_request would fail fast) instead of receiving the response.
        response = await asyncio.wait_for(session.send_request(request), timeout=2.0)
        await feeder

        assert isinstance(response, JSONRPCResponse)
        assert response.id == 7
    finally:
        await session.terminate()
