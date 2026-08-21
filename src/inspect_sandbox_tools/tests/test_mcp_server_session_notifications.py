"""Regression tests for unexpected lines on the MCP server's stdout.

MCPServerSession's stdout reader must tolerate lines it cannot dispatch rather
than crash -- a dead reader fails every pending request. Two such cases are
covered here:

- A stdio MCP server that advertises `tools.listChanged` may legally emit an
  unsolicited `notifications/tools/list_changed` (the ExploitBench V8 server
  does this right after `initialize`). The session is a request/response proxy
  and does not forward such messages, but it must IGNORE them.
- A JSON-RPC parse-error response carries `id: null` and so cannot be
  correlated to any pending request; it must be dropped.

Each test feeds the unexpected line ahead of a normal response and asserts the
matching request still resolves.
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


async def test_null_id_error_response_does_not_kill_reader() -> None:
    """A JSON-RPC parse-error response (null id) must be ignored, not fatal.

    mcp 1.x rejects a null id at validation so the line is skipped as
    unparseable; mcp 2.x validates it (the id field is optional there), and an
    uncorrelatable response must likewise be dropped rather than crash the
    reader task and fail every pending request.
    """
    reader = asyncio.StreamReader()
    session = MCPServerSession(_FakeProcess(reader), "utf-8", "strict")
    try:
        reader.feed_data(
            b'{"jsonrpc":"2.0","id":null,'
            b'"error":{"code":-32700,"message":"parse error"}}\n'
        )

        async def feed_response() -> None:
            await asyncio.sleep(0.05)
            reader.feed_data(b'{"jsonrpc":"2.0","id":7,"result":{"tools":[]}}\n')

        asyncio.create_task(feed_response())
        request = JSONRPCRequest(jsonrpc="2.0", id=7, method="tools/list", params={})

        # Under mcp 2.x without the null-id guard, the reader's resolve step
        # asserts on the uncorrelatable response and dies; the pending request
        # is then failed with a synthetic error (or send_request fails fast if
        # the reader died first) instead of receiving its real response.
        response = await asyncio.wait_for(session.send_request(request), timeout=2.0)

        assert isinstance(response, JSONRPCResponse)
        assert response.id == 7
    finally:
        await session.terminate()
