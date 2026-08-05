"""A ToolSource must not hand one caller another caller's tools.

Each Tool returned by an MCP server closes over the MCPServerLocalSession that
produced it, and those sessions are scoped per async task. A ToolSource is
shared -- inspect eval builds one per Task and every sample uses it -- so
caching the resolved list on the instance handed later samples tools bound to
the FIRST sample's session, and their tool calls then executed in that sample's
sandbox while their own sandbox was never touched.

The cache scope token is the per-task session OBJECT rather than the raw
anyio task id: on asyncio the task id is id()-based and can be reused once an
earlier task is garbage collected, so two tasks can share an id over time.
Sessions therefore evict themselves from the per-task registry when they
close, and the tool source re-resolves whenever the session object changes.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import anyio

from inspect_ai.tool._mcp._local import MCPServerLocal
from inspect_ai.tool._mcp.tools import MCPToolSourceLocal


class _FakeServer:
    """Returns a distinct tool object per call, standing in for a per-task session."""

    def __init__(self) -> None:
        self.calls = 0
        self.scope_token: object = object()

    def _tool_cache_scope(self) -> object:
        return self.scope_token

    async def tools(self) -> list[Any]:
        self.calls += 1
        marker = self.calls

        async def tool_a() -> int:
            return marker

        return [tool_a]


def _never_client() -> Any:
    raise AssertionError("transport must not be used by these tests")


def test_tools_are_reresolved_when_the_scope_changes() -> None:
    """A new session object (e.g. a new sample's task) must not see cached tools."""
    server = _FakeServer()
    source = MCPToolSourceLocal(server, "all")  # type: ignore[arg-type]
    seen: list[str] = []

    async def caller() -> None:
        tools = await source.tools()
        seen.append(str(await tools[0]()))

    async def main() -> None:
        await caller()
        # a fresh per-task session -- however the task id compares -- means a
        # fresh scope token, and the cached list must be discarded
        server.scope_token = object()
        await caller()

    anyio.run(main)

    assert server.calls == 2, (
        f"expected one resolution per scope, got {server.calls}; a shared cache "
        "hands the second caller tools bound to the first caller's session"
    )
    assert seen[0] != seen[1], "second caller received the first caller's tool object"


def test_tools_are_cached_within_one_scope() -> None:
    """The cache must still work inside a single scope -- that is its purpose."""
    server = _FakeServer()
    source = MCPToolSourceLocal(server, "all")  # type: ignore[arg-type]

    async def main() -> None:
        await source.tools()
        await source.tools()
        await source.tools()

    anyio.run(main)

    assert server.calls == 1, (
        f"expected a single resolution per scope, got {server.calls}"
    )


def test_task_session_is_evicted_when_it_closes() -> None:
    """A reused task id must get a fresh session, not a closed one.

    Calling _task_session() twice from one task uses the same registry key --
    exactly what a later task reusing a collected task's id would present. If
    the closed session were not evicted, the second lookup would return it
    (and its stale cached tool list).
    """
    server = MCPServerLocal(_never_client, name=f"evict-{uuid4()}", events=False)

    async def main() -> None:
        s1 = server._task_session()
        assert server._task_session() is s1, "session should be cached per task"
        await s1._close_and_evict()
        s2 = server._task_session()
        assert s2 is not s1, "a closed session must not be handed out again"
        await s2._close_and_evict()

    anyio.run(main)


def test_close_does_not_evict_a_replacement_session() -> None:
    """Eviction is identity-guarded: closing an old session must not drop a new one."""
    server = MCPServerLocal(_never_client, name=f"guard-{uuid4()}", events=False)

    async def main() -> None:
        s1 = server._task_session()
        await s1._close_and_evict()
        s2 = server._task_session()
        # closing the OLD session again must leave the replacement registered
        await s1._close_and_evict()
        assert server._task_session() is s2, (
            "closing a stale session evicted its replacement"
        )
        await s2._close_and_evict()

    anyio.run(main)


def test_tool_cache_scope_tracks_the_live_session() -> None:
    """MCPServerLocal's cache token is the session object itself."""
    server = MCPServerLocal(_never_client, name=f"scope-{uuid4()}", events=False)

    async def main() -> None:
        s1 = server._task_session()
        assert server._tool_cache_scope() is s1
        await s1._close_and_evict()
        token = server._tool_cache_scope()
        assert token is not s1, "cache token still points at a closed, evicted session"
        assert isinstance(token, type(s1))
        await server._task_session()._close_and_evict()

    anyio.run(main)
