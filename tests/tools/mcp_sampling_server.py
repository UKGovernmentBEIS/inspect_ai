"""MCP stdio server whose `ask` tool asks the client's model to answer.

With `--sample-on-list return` or `--sample-on-list wait`, listing the tools
also asks the client's model, three times, ignoring errors. Then it returns
the tools, or never returns.
"""

import argparse
import importlib
from typing import Any

import anyio
from mcp.types import SamplingMessage, TextContent

parser = argparse.ArgumentParser()
parser.add_argument("--sample-on-list", choices=["return", "wait"])
sample_on_list = parser.parse_args().sample_on_list


async def _sample_on_list(session: Any) -> None:
    for _ in range(3):
        try:
            await _ask(session, "Hi?")
        except Exception:
            pass
    if sample_on_list == "wait":
        await anyio.sleep_forever()


# mcp 2.0 renamed FastMCP to MCPServer (see mcp_test_server.create_server)
try:
    _module = importlib.import_module("mcp.server.mcpserver")
    _base: Any = _module.MCPServer
except ImportError:
    _module = importlib.import_module("mcp.server.fastmcp")
    _base = _module.FastMCP


class _ListSamplingServer(_base):
    if hasattr(_base, "_handle_list_tools"):
        # mcp 2.x: the list handler receives the request context
        async def _handle_list_tools(self, ctx: Any, params: Any) -> Any:
            await _sample_on_list(ctx.session)
            return await super()._handle_list_tools(ctx, params)

    else:
        # mcp 1.x: list_tools is the handler
        async def list_tools(self) -> Any:
            await _sample_on_list(self.get_context().session)
            return await super().list_tools()


server: Any = (_ListSamplingServer if sample_on_list else _base)("sampling-server")


async def ask(question: str, ctx: Any) -> str:
    return await _ask(ctx.session, question)


async def _ask(session: Any, question: str) -> str:
    result = await session.create_message(
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
