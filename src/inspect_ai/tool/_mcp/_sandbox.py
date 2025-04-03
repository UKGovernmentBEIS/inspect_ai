from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp import StdioServerParameters

from ._types import MCPServerContext


@asynccontextmanager
async def sandbox_client(
    server: StdioServerParameters,
) -> AsyncIterator[MCPServerContext]:
    yield None  # type: ignore[misc]
