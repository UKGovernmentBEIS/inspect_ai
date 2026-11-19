"""Regression tests for MCPServerLocal session-cache isolation.

Before the fix, ``MCPServerLocal._task_sessions`` was a class-level dict
keyed on ``anyio.get_current_task().id`` (which is ``id(asyncio.current_task())``
— a memory address). Python recycles those addresses once tasks are GC'd,
so a later sample in an ``eval_set`` run could inherit the previous
sample's ``MCPServerLocalSession`` — including its cached tool list —
producing "Tool not found" errors when the tool sets differed.

These tests don't spawn real subprocesses; they exercise the session
bookkeeping directly so the isolation guarantees are easy to verify.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from inspect_ai.tool import Tool, ToolDef
from inspect_ai.tool._mcp._local import (
    MCPServerLocal,
    MCPServerLocalSession,
    _Connection,
)


def _make_server(name: str = "s") -> MCPServerLocal:
    # _client is only called when a real session connects; these tests never
    # reach that path, so a placeholder is sufficient.
    def _unused_client() -> Any:
        raise AssertionError("client should not be invoked in this test")

    return MCPServerLocal(client=_unused_client, name=name, events=False)


async def test_task_sessions_are_instance_level() -> None:
    """Two MCPServerLocal instances share no session state.

    Holds even on the same anyio task (i.e. same task id).
    """
    a = _make_server("a")
    b = _make_server("b")

    sa = a._task_session()
    sb = b._task_session()

    # Different instances → different sessions, regardless of shared task id.
    assert sa is not sb
    # Each instance owns its own table; class has none.
    assert "_task_sessions" not in MCPServerLocal.__dict__
    assert sa in a._task_sessions.values()
    assert sb in b._task_sessions.values()

    # And within one instance, repeated calls on the same task reuse the session.
    assert a._task_session() is sa


async def test_task_sessions_independent_across_instances_with_same_name() -> None:
    """Two instances sharing the same ``name`` don't collide.

    Sharing a name is a common pattern when the same Task builder runs for
    every sample.
    """
    a = _make_server("same-name")
    b = _make_server("same-name")

    sa = a._task_session()
    sb = b._task_session()

    assert sa is not sb


def _mcp_tool(name: str) -> Any:
    from mcp.types import Tool as MCPTool

    return MCPTool.model_validate(
        {
            "name": name,
            "description": name,
            "inputSchema": {"type": "object", "properties": {}},
        }
    )


def _tool_names(tools: list[Tool]) -> list[str]:
    return [ToolDef(t).name for t in tools]


def _local_session(
    monkeypatch: pytest.MonkeyPatch, connections: list[str]
) -> MCPServerLocalSession:
    """A session whose connects pop `connections`, each listing one tool so named."""
    session = MCPServerLocalSession(
        client=lambda: (_ for _ in ()).throw(AssertionError("unused")),
        name="s",
        events=False,
    )

    async def connect(exit_stack: AsyncExitStack) -> Any:
        client = AsyncMock()
        client.list_tools.return_value = SimpleNamespace(
            tools=[_mcp_tool(connections.pop(0))]
        )
        return client

    monkeypatch.setattr(session, "_connect", connect)
    return session


@pytest.mark.parametrize("teardown_raises", [False, True])
async def test_tool_list_not_served_after_close(
    monkeypatch: pytest.MonkeyPatch, teardown_raises: bool
) -> None:
    """A connection's tool list is not served once its refcount drops to zero.

    Otherwise a reused session would serve stale tools to the next connection
    without contacting the server. This holds when a tools() call during
    teardown lists over a temporary connection, and when teardown raises.
    """
    session = _local_session(monkeypatch, ["temporary", "reconnected"])

    async def teardown() -> None:
        assert _tool_names(await session.tools()) == ["temporary"]
        if teardown_raises:
            raise RuntimeError("teardown failed")

    closed = AsyncMock(side_effect=teardown)
    exit_stack = AsyncExitStack()
    exit_stack.push_async_callback(closed)
    session._conn = _Connection(
        AsyncMock(), exit_stack, tool_list=[_mcp_tool("closed")]
    )

    if teardown_raises:
        with pytest.raises(RuntimeError, match="teardown failed"):
            await session.__aexit__(None, None, None)
    else:
        await session.__aexit__(None, None, None)

    closed.assert_awaited_once()
    assert session._conn is None
    assert _tool_names(await session.tools()) == ["temporary"]
    async with session:
        assert _tool_names(await session.tools()) == ["reconnected"]


async def test_tool_list_preserved_when_still_referenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing one holder must NOT drop the tool list while others remain.

    If the session is still held by another caller (refcount > 0), the
    remaining holder still expects its tools without listing them again.
    """
    session = _local_session(monkeypatch, [])
    client = AsyncMock()
    conn = _Connection(
        client, AsyncExitStack(), refcount=2, tool_list=[_mcp_tool("held")]
    )  # two holders
    session._conn = conn

    await session.__aexit__(None, None, None)

    assert session._conn is conn
    assert conn.refcount == 1
    assert _tool_names(await session.tools()) == ["held"]
    client.list_tools.assert_not_called()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
