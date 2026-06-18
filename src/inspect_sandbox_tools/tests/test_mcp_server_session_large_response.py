"""Regression tests for large MCP server responses exceeding the readline limit.

MCPServerSession reads the downstream stdio MCP server's responses with
asyncio.StreamReader.readline(), which has a 64KB line limit by default. A single
JSON-RPC response line longer than the limit makes readline() raise
LimitOverrunError. Previously that killed the stdout reader task and left every
pending request to hang until the client's MCP timeout (also poisoning the session
for subsequent requests). MCP tool responses routinely exceed 64KB once wrapped in
the JSON-RPC envelope (large file reads, verbose command output, base64
screenshots), so this was a real failure, not a corner case.

The fix is twofold:
  1. The reader's line limit defaults to 256 MiB (overridable via
     INSPECT_MCP_READLINE_LIMIT_BYTES), so realistic large responses just work.
  2. If a line still exceeds the limit (or the server EOFs with requests pending),
     the reader fails ALL pending requests with a clear error instead of hanging,
     and a subsequent send_request on the dead session fails fast.
"""

import asyncio

import pytest
from inspect_sandbox_tools._remote_tools._mcp.mcp_server_session import (
    MCPServerSession,
)
from mcp import JSONRPCError, JSONRPCRequest, JSONRPCResponse


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


async def test_large_response_resolves_under_default_limit() -> None:
    # ~1 MiB single-line response: above the old 64KB default (which hung), well
    # under the new 256 MiB default. Must resolve normally.
    reader = asyncio.StreamReader(limit=100 * 1024 * 1024)
    session = MCPServerSession(_FakeProcess(reader), "utf-8", "strict")
    try:
        payload = (
            '{"jsonrpc":"2.0","id":7,"result":{"content":[{"type":"text","text":"'
            + ("A" * (1024 * 1024))
            + '"}]}}\n'
        )

        async def feed() -> None:
            await asyncio.sleep(0.05)
            reader.feed_data(payload.encode())

        feed_task = asyncio.create_task(feed())
        request = JSONRPCRequest(jsonrpc="2.0", id=7, method="tools/call", params={})
        response = await asyncio.wait_for(session.send_request(request), timeout=5.0)
        assert isinstance(response, JSONRPCResponse)
        assert response.id == 7
        await feed_task
    finally:
        await session.terminate()


async def test_oversized_line_fails_fast_instead_of_hanging() -> None:
    # Small reader limit + an over-limit line with no newline: the pending request
    # must be failed promptly rather than hang until the client timeout.
    reader = asyncio.StreamReader(limit=4096)
    session = MCPServerSession(_FakeProcess(reader), "utf-8", "strict")
    try:

        async def feed() -> None:
            await asyncio.sleep(0.05)
            reader.feed_data(b'{"jsonrpc":"2.0","id":7,"result":"' + b"A" * 8192)

        feed_task = asyncio.create_task(feed())
        request = JSONRPCRequest(jsonrpc="2.0", id=7, method="tools/call", params={})
        try:
            response = await asyncio.wait_for(
                session.send_request(request), timeout=3.0
            )
            # graceful failure: the pending request resolves to a JSON-RPC error
            assert isinstance(response, JSONRPCError)
        except RuntimeError:
            pass  # or the reader already died and send_request failed fast
        await feed_task
    finally:
        await session.terminate()


async def test_send_request_after_reader_death_fails_fast() -> None:
    # After the reader dies on an oversized line, a SUBSEQUENT request must fail
    # fast rather than hang — the session must not be silently poisoned.
    reader = asyncio.StreamReader(limit=4096)
    session = MCPServerSession(_FakeProcess(reader), "utf-8", "strict")
    try:
        reader.feed_data(b'{"jsonrpc":"2.0","id":1,"result":"' + b"A" * 8192)
        # wait for the reader to observe the oversized line and exit; it swallows
        # the read error into pending requests, so awaiting it returns cleanly.
        await session._reader

        request = JSONRPCRequest(jsonrpc="2.0", id=2, method="tools/call", params={})
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(session.send_request(request), timeout=3.0)
    finally:
        await session.terminate()


async def test_terminate_resolves_inflight_request_instead_of_hanging() -> None:
    # A request parked on `await future` when terminate() cancels the reader must
    # be resolved (with an error) rather than left hanging until the client timeout.
    reader = asyncio.StreamReader(limit=100 * 1024 * 1024)
    session = MCPServerSession(_FakeProcess(reader), "utf-8", "strict")

    # never feed a response, so send_request parks on `await future`
    request = JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params={})
    pending = asyncio.create_task(session.send_request(request))

    # wait until send_request has registered its future and is awaiting it
    while not session._requests:
        await asyncio.sleep(0)
    assert not pending.done()

    await session.terminate()

    response = await asyncio.wait_for(pending, timeout=3.0)
    assert isinstance(response, JSONRPCError)


async def test_create_wires_readline_limit_into_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Guard the production path: create() must pass limit=_READLINE_LIMIT to
    # create_subprocess_exec. The large-response fix is moot if this kwarg is
    # dropped, and the reader-level tests above (which build their own
    # StreamReader) would not catch that regression.
    from inspect_sandbox_tools._remote_tools._mcp import mcp_server_session
    from mcp import StdioServerParameters

    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(
        *args: object, **kwargs: object
    ) -> _FakeProcess:
        captured["limit"] = kwargs.get("limit")
        return _FakeProcess(asyncio.StreamReader())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    session = await MCPServerSession.create(StdioServerParameters(command="true"))
    try:
        assert captured["limit"] == mcp_server_session._READLINE_LIMIT
    finally:
        await session.terminate()
