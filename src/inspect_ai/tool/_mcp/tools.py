from typing import Literal

from .._tool import Tool
from ._types import McpClient


async def mcp_tools(
    client: McpClient, tools: Literal["all"] | list[str] = "all"
) -> list[Tool]:
    """Tools from Model Context Protocol server.

    Args:
       client: Model Context Protocol client (created with
          `mcp_sse_client()` or `mcp_stdio_client()`.
       tools: List of tool names (or globs) (defaults to "all")
          which returns all tools.

    Returns:
       List of tools.
    """
    return await client.list_tools()
