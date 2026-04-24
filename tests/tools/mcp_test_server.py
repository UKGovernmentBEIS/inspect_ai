"""Self-contained MCP stdio server for testing MCP infrastructure."""

import asyncio
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("test-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="echo",
            description="Echoes back the input message",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Message to echo"}
                },
                "required": ["message"],
            },
        ),
        Tool(
            name="add",
            description="Adds two numbers",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "First number"},
                    "y": {"type": "integer", "description": "Second number"},
                },
                "required": ["x", "y"],
            },
        ),
        Tool(
            name="get_status",
            description="Returns a fixed status string",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_info",
            description="Returns a fixed info string",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "echo":
        return [TextContent(type="text", text=arguments.get("message", ""))]
    elif name == "add":
        result = arguments.get("x", 0) + arguments.get("y", 0)
        return [TextContent(type="text", text=str(result))]
    elif name == "get_status":
        return [TextContent(type="text", text="ok")]
    elif name == "get_info":
        return [TextContent(type="text", text="test server v1")]
    raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    sys.stderr.write("[STARTUP] Test MCP server starting\n")
    sys.stderr.flush()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
