import logging
import sys
from pathlib import Path

from test_helpers.utils import skip_if_no_mcp_package

from inspect_ai.tool import mcp_connection, mcp_server_stdio

STDERR_SERVER = str(Path(__file__).parent / "mcp_stderr_server.py")


@skip_if_no_mcp_package
async def test_mcp_stdio_stderr_forwarding(caplog: logging.LogRecord) -> None:
    server = mcp_server_stdio(command=sys.executable, args=[STDERR_SERVER])

    with caplog.at_level(logging.INFO):  # type: ignore
        async with mcp_connection(server):
            tools = await server.tools()
            assert len(tools) > 0

    mcp_records = [
        r
        for r in caplog.records  # type: ignore
        if r.name.startswith("inspect_ai.tool._mcp.")
    ]
    stderr_messages = [r.message for r in mcp_records]
    assert any("STARTUP_STDERR" in msg for msg in stderr_messages), (
        f"Expected startup stderr in log records, got: {stderr_messages}"
    )
