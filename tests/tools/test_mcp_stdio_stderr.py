import logging
import sys
from pathlib import Path

from test_helpers.utils import skip_if_no_mcp_package

from inspect_ai.tool import mcp_connection, mcp_server_stdio

STDERR_SERVER = str(Path(__file__).parent / "mcp_stderr_server.py")


@skip_if_no_mcp_package
async def test_mcp_stdio_stderr_forwarding(
    monkeypatch: logging.LogRecord,
) -> None:
    server = mcp_server_stdio(command=sys.executable, args=[STDERR_SERVER])

    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record)  # type: ignore

    mcp_logger = logging.getLogger("inspect_ai.tool._mcp")
    monkeypatch.setattr(mcp_logger, "handlers", [handler])  # type: ignore
    monkeypatch.setattr(mcp_logger, "propagate", False)  # type: ignore
    monkeypatch.setattr(mcp_logger, "level", logging.DEBUG)  # type: ignore

    async with mcp_connection(server):
        tools = await server.tools()
        assert len(tools) > 0

    stderr_messages = [r.getMessage() for r in records]
    assert any("STARTUP_STDERR" in msg for msg in stderr_messages), (
        f"Expected startup stderr in log records, got: {stderr_messages}"
    )
