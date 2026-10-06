import pytest
from inspect_sandbox_tools._remote_tools._mcp import json_rpc_methods as mcp_methods


class _FakeSession:
    def __init__(self) -> None:
        self.terminate_timeouts: list[int] = []
        self.shutdown_timeouts: list[int] = []

    async def terminate(self, timeout: int) -> None:
        self.terminate_timeouts.append(timeout)

    async def shutdown(self, timeout: int) -> None:
        self.shutdown_timeouts.append(timeout)


@pytest.mark.asyncio
async def test_shutdown_sweeps_session_retired_by_kill() -> None:
    previous_sessions = mcp_methods.sessions.copy()
    previous_retired_sessions = mcp_methods.retired_sessions.copy()
    retired_session = _FakeSession()
    active_session = _FakeSession()
    session_id = 987_654_321

    try:
        mcp_methods.sessions.clear()
        mcp_methods.retired_sessions.clear()
        mcp_methods.sessions[session_id] = retired_session  # type: ignore[assignment]

        await mcp_methods.mcp_kill_server(session_id=session_id)

        assert retired_session.terminate_timeouts == [30]
        assert session_id not in mcp_methods.sessions
        assert mcp_methods.retired_sessions == [retired_session]

        mcp_methods.sessions[session_id + 1] = active_session  # type: ignore[assignment]
        await mcp_methods.shutdown()

        assert retired_session.shutdown_timeouts == [30]
        assert active_session.shutdown_timeouts == [30]
        assert not mcp_methods.sessions
        assert not mcp_methods.retired_sessions
    finally:
        mcp_methods.sessions.clear()
        mcp_methods.sessions.update(previous_sessions)
        mcp_methods.retired_sessions.clear()
        mcp_methods.retired_sessions.extend(previous_retired_sessions)
