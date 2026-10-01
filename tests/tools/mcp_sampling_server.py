"""MCP stdio server whose `ask` tool asks the client's model to answer."""

import importlib
from typing import Any

import anyio
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


async def ask_repeatedly(question: str, times: int, ctx: Any) -> str:
    answers: list[str] = []
    for _ in range(times):
        try:
            answers.append(await ask(question, ctx))
        except Exception as ex:
            answers.append(f"error: {ex}")
    return "\n".join(answers)


async def ask_then_wait(question: str, ctx: Any) -> str:
    try:
        await ask(question, ctx)
    except Exception:
        pass
    await anyio.sleep_forever()
    return "unreachable"


# the server finds the context parameter by its annotation
for _fn in (ask, ask_repeatedly, ask_then_wait):
    _fn.__annotations__["ctx"] = _module.Context
server.tool(description="Asks the client's model a question")(ask)
server.tool(description="Asks the client's model, ignoring errors")(ask_repeatedly)
server.tool(description="Asks the client's model, then never returns")(ask_then_wait)


if __name__ == "__main__":
    server.run("stdio")
