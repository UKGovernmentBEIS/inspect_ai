"""Self-contained MCP server (stdio or streamable-http) for testing MCP infrastructure."""

import argparse
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


def run_streamable_http(server: Any, port: int) -> None:
    """Serve on streamable-http at http://127.0.0.1:{port}/mcp.

    mcp 1.x FastMCP takes host/port via its settings object; 2.x MCPServer
    takes them as run() kwargs (its settings no longer carry network config).
    """
    if hasattr(server.settings, "port"):
        server.settings.host = "127.0.0.1"
        server.settings.port = port
        server.run("streamable-http")
    else:
        server.run("streamable-http", host="127.0.0.1", port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http"], default="stdio"
    )
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    sys.stderr.write("[STARTUP] Test MCP server starting\n")
    sys.stderr.flush()
    if args.transport == "streamable-http":
        run_streamable_http(server, args.port)
    else:
        server.run("stdio")
