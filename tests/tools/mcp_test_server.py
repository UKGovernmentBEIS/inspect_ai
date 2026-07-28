"""Self-contained MCP stdio server for testing MCP infrastructure."""

import importlib
import sys
from typing import Any


def create_server(name: str) -> Any:
    """High-level MCP server for whichever mcp major version is installed.

    mcp 2.0 removed the low-level `Server` decorator API and renamed the
    high-level `FastMCP` server to `MCPServer` (same `@server.tool()` /
    `run("stdio")` shape). Resolved dynamically so this module imports (and
    type-checks) under either version.
    """
    try:
        return importlib.import_module("mcp.server.mcpserver").MCPServer(name)
    except ImportError:
        return importlib.import_module("mcp.server.fastmcp").FastMCP(name)


server = create_server("test-server")


@server.tool(description="Echoes back the input message")
async def echo(message: str) -> str:
    return message


@server.tool(description="Adds two numbers")
async def add(x: int, y: int) -> str:
    return str(x + y)


@server.tool(description="Returns a fixed status string")
async def get_status() -> str:
    return "ok"


@server.tool(description="Returns a fixed info string")
async def get_info() -> str:
    return "test server v1"


if __name__ == "__main__":
    sys.stderr.write("[STARTUP] Test MCP server starting\n")
    sys.stderr.flush()
    server.run("stdio")
