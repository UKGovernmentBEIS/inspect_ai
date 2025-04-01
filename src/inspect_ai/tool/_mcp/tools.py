from .._tool import Tool
from ._types import McpClient


def mcp_tools(client: McpClient) -> list[Tool]:
    """Tools from Model Context Protocol server.

    Args:
       client: Model Context Protocol client (created with
           `mcp_sse_client()`, `mcp_stdio_client()`, or `mcp_sandbox_client()`).

    Returns:
       List of tools.
    """
    return []
