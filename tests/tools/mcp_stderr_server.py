"""Minimal MCP stdio server that writes to stderr (for testing stderr forwarding)."""

import sys

from mcp_test_server import create_server

server = create_server("stderr-test-server")


@server.tool(description="Echoes back the input")
async def echo(message: str) -> str:
    sys.stderr.write(f"[TOOL_STDERR] echo called with: {message}\n")
    sys.stderr.flush()
    return message


if __name__ == "__main__":
    sys.stderr.write("[STARTUP_STDERR] Server starting up\n")
    sys.stderr.flush()
    server.run("stdio")
