"""Minimal MCP stdio server that writes to stderr (for testing stderr forwarding)."""

import asyncio
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("stderr-test-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="echo",
            description="Echoes back the input",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Message to echo"}
                },
                "required": ["message"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:  # type: ignore
    if name == "echo":
        sys.stderr.write(
            f"[TOOL_STDERR] echo called with: {arguments.get('message', '')}\n"
        )
        sys.stderr.flush()
        return [TextContent(type="text", text=arguments.get("message", ""))]
    raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    sys.stderr.write("[STARTUP_STDERR] Server starting up\n")
    sys.stderr.flush()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
