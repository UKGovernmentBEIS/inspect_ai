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
from typing import Any
from unittest.mock import AsyncMock

import pytest

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


@pytest.mark.parametrize("teardown_raises", [False, True])
async def test_cached_tool_list_cleared_on_close(teardown_raises: bool) -> None:
    """A session whose refcount drops to zero must clear its cached tool list.

    Otherwise a reused session object would serve stale tools to the next
    caller without contacting the server. The cache is cleared after
    teardown, since a tools() call during teardown can refill it, and also
    when teardown raises.
    """
    session = MCPServerLocalSession(
        client=lambda: (_ for _ in ()).throw(AssertionError("unused")),
        name="s",
        events=False,
    )

    # Simulate an active session with a populated cache.
    sentinel_tools: list[Any] = [object()]
    session._cached_tool_list = sentinel_tools
    exit_stack = AsyncExitStack()

    async def teardown() -> None:
        session._cached_tool_list = sentinel_tools  # refilled during teardown
        if teardown_raises:
            raise RuntimeError("teardown failed")

    closed = AsyncMock(side_effect=teardown)
    exit_stack.push_async_callback(closed)
    session._conn = _Connection(AsyncMock(), exit_stack)

    if teardown_raises:
        with pytest.raises(RuntimeError, match="teardown failed"):
            await session.__aexit__(None, None, None)
    else:
        await session.__aexit__(None, None, None)

    closed.assert_awaited_once()
    assert session._conn is None
    assert session._cached_tool_list is None, (
        "cache must be dropped on close so a reused session re-fetches tools"
    )


async def test_cached_tool_list_preserved_when_still_referenced() -> None:
    """Closing one holder must NOT invalidate the cache while others remain.

    If the session is still held by another caller (refcount > 0), the
    remaining holder still expects its tools.
    """
    session = MCPServerLocalSession(
        client=lambda: (_ for _ in ()).throw(AssertionError("unused")),
        name="s",
        events=False,
    )
    sentinel_tools: list[Any] = [object()]
    session._cached_tool_list = sentinel_tools
    conn = _Connection(AsyncMock(), AsyncExitStack(), refcount=2)  # two holders
    session._conn = conn

    await session.__aexit__(None, None, None)

    assert session._conn is conn
    assert conn.refcount == 1
    assert session._cached_tool_list is sentinel_tools


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
