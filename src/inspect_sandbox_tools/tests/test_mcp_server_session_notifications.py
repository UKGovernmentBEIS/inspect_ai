"""Regression test for unsolicited server->client MCP messages.

A stdio MCP server that advertises `tools.listChanged` may legally emit an
unsolicited `notifications/tools/list_changed` (the ExploitBench V8 server does
this right after `initialize`). MCPServerSession is a request/response proxy and
does not forward such messages, but it must IGNORE them rather than crash its
stdout reader task -- otherwise every pending request hangs until the MCP
timeout. This test feeds an unsolicited notification ahead of a normal response
and asserts the matching request still resolves.
"""

import asyncio

from inspect_sandbox_tools._remote_tools._mcp.mcp_server_session import (
    MCPServerSession,
)
from mcp import JSONRPCRequest, JSONRPCResponse


class _FakeStdin:
    def write(self, data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass


class _FakeProcess:
    def __init__(self, stdout: asyncio.StreamReader) -> None:
        self.stdout = stdout
        self.stdin = _FakeStdin()

    def terminate(self) -> None:
        pass

    async def wait(self) -> int:
        return 0

    def kill(self) -> None:
        pass


async def test_unsolicited_notification_does_not_hang_pending_requests() -> None:
    reader = asyncio.StreamReader()
    session = MCPServerSession(_FakeProcess(reader), "utf-8", "strict")
    try:
        # Unsolicited notification arrives before the response we are waiting on.
        reader.feed_data(
            b'{"jsonrpc":"2.0","method":"notifications/tools/list_changed","params":{}}\n'
        )

        async def feed_response() -> None:
            await asyncio.sleep(0.05)
            reader.feed_data(b'{"jsonrpc":"2.0","id":7,"result":{"tools":[]}}\n')

        asyncio.create_task(feed_response())
        request = JSONRPCRequest(jsonrpc="2.0", id=7, method="tools/list", params={})

        # Unpatched, the reader dies on the notification and this never resolves.
        response = await asyncio.wait_for(session.send_request(request), timeout=2.0)

        assert isinstance(response, JSONRPCResponse)
        assert response.id == 7
    finally:
        await session.terminate()
