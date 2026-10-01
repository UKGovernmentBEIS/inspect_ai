"""MCP stdio server whose `ask` tool asks the client's model to answer."""

import importlib
from typing import Any

from mcp.types import SamplingMessage, TextContent

# mcp 2.0 renamed FastMCP to MCPServer (see mcp_test_server.create_server)
try:
    _module = importlib.import_module("mcp.server.mcpserver")
    server: Any = _module.MCPServer("sampling-server")
except ImportError:
    _module = importlib.import_module("mcp.server.fastmcp")
    server = _module.FastMCP("sampling-server")


async def ask(question: str, ctx: Any) -> str:
    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user", content=TextContent(type="text", text=question)
            )
        ],
        max_tokens=100,
    )
    return result.content.text


# the server finds the context parameter by its annotation
ask.__annotations__["ctx"] = _module.Context
server.tool(description="Asks the client's model a question")(ask)


if __name__ == "__main__":
    server.run("stdio")
