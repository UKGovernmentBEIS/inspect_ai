import contextlib
from contextlib import AsyncExitStack
from copy import deepcopy
from fnmatch import fnmatch
from logging import getLogger
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Literal

from mcp.client.session import ClientSession, SamplingFnT
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import EmbeddedResource, ImageContent, TextContent, TextResourceContents
from mcp.types import Tool as MCPTool
from typing_extensions import override

from inspect_ai._util.trace import trace_action
from inspect_ai.tool._mcp._sandbox import sandbox_client
from inspect_ai.tool._mcp.sampling import as_inspect_content
from inspect_ai.tool._tool import Tool, ToolError, ToolResult
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_params import ToolParams

from ._types import MCPServer, MCPServerContext
from .sampling import sampling_fn

# https://github.com/modelcontextprotocol/python-sdk/pull/401
# https://github.com/modelcontextprotocol/python-sdk/pull/361
# https://github.com/modelcontextprotocol/python-sdk/pull/289

logger = getLogger(__name__)


class MCPServerImpl(MCPServer):
    def __init__(
        self, client: Callable[[], MCPServerContext], *, name: str, events: bool
    ) -> None:
        super().__init__()
        self._client = client
        self._name = name
        self._events = events
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None

    @override
    async def _connect(self) -> None:
        with trace_action(logger, "MCPServer", f"connect: {self._name}"):
            assert self._session is None
            assert self._exit_stack is None
            self._exit_stack = AsyncExitStack()
            await self._exit_stack.__aenter__()
            read, write = await self._exit_stack.enter_async_context(self._client())
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read, write, sampling_callback=self._sampling_fn())
            )
            await self._session.initialize()

    @override
    async def _close(self) -> None:
        with trace_action(logger, "MCPServer", f"disconnect: {self._name}"):
            assert self._session is not None
            assert self._exit_stack is not None
            try:
                await self._exit_stack.aclose()
            finally:
                self._session = None
                self._exit_stack = None

    async def _list_tools(
        self, tools: Literal["all"] | list[str] = "all"
    ) -> list[Tool]:
        async with self._client_session() as session:
            # function for filtering tools
            def include_tool(tool: MCPTool) -> bool:
                if tools == "all":
                    return True
                else:
                    return any([fnmatch(tool.name, t) for t in tools])

            # get the underlying tools on the server
            mcp_tools = (await session.list_tools()).tools

            # filter them
            mcp_tools = [mcp_tool for mcp_tool in mcp_tools if include_tool(mcp_tool)]

            # dynamically create tools
            tool_defs: list[ToolDef] = []
            for mcp_tool in mcp_tools:

                async def execute(**kwargs: Any) -> ToolResult:
                    async with self._client_session() as tool_session:
                        result = await tool_session.call_tool(mcp_tool.name, kwargs)
                        if result.isError:
                            raise ToolError(tool_result_as_text(result.content))

                        return [as_inspect_content(c) for c in result.content]

                # get parameters (fill in missing ones)
                parameters = ToolParams.model_validate(mcp_tool.inputSchema)
                for name, param in parameters.properties.items():
                    param.description = param.description or name

                tool_defs.append(
                    ToolDef(
                        execute,
                        name=mcp_tool.name,
                        description=mcp_tool.description,
                        parameters=parameters,
                    )
                )

            return [tool_def.as_tool() for tool_def in tool_defs]

    # if we have been entered as a context manager then return that session,
    # otherwise, create a brand new session from the client
    @contextlib.asynccontextmanager
    async def _client_session(self) -> AsyncIterator[ClientSession]:
        if self._session is not None:
            yield self._session
        else:
            async with self._client() as (read, write):
                async with ClientSession(
                    read, write, sampling_callback=self._sampling_fn()
                ) as session:
                    await session.initialize()
                    yield session

    def _sampling_fn(self) -> SamplingFnT | None:
        from inspect_ai.model._model import active_model

        if self._events and active_model() is not None:
            return sampling_fn
        else:
            return None

    def __deepcopy__(self, memo: dict[int, Any]) -> "MCPServerImpl":
        if self._session is not None:
            raise RuntimeError(
                "You cannot deepcopy an MCPServer with an active session."
            )
        return MCPServerImpl(
            deepcopy(self._client), name=self._name, events=self._events
        )


def create_server_sse(
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> MCPServer:
    return MCPServerImpl(
        lambda: sse_client(url, headers, timeout, sse_read_timeout),
        name=url,
        events=True,
    )


def create_server_stdio(
    command: str,
    args: list[str] = [],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    encoding: str = "utf-8",
    encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict",
) -> MCPServer:
    return MCPServerImpl(
        lambda: stdio_client(
            StdioServerParameters(
                command=command,
                args=args,
                cwd=cwd,
                env=env,
                encoding=encoding,
                encoding_error_handler=encoding_error_handler,
            )
        ),
        name=" ".join([command] + args),
        events=True,
    )


def create_server_sandbox(
    command: str,
    args: list[str] = [],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    encoding: str = "utf-8",
    encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict",
    sandbox: str | None = None,
) -> MCPServer:
    return MCPServerImpl(
        lambda: sandbox_client(
            StdioServerParameters(
                command=command,
                args=args,
                cwd=cwd,
                env=env,
                encoding=encoding,
                encoding_error_handler=encoding_error_handler,
            ),
            sandbox,
        ),
        name=" ".join([command] + args),
        events=False,
    )


def tool_result_as_text(
    content: list[TextContent | ImageContent | EmbeddedResource],
) -> str:
    content_list: list[str] = []
    for c in content:
        if isinstance(c, TextContent):
            content_list.append(c.text)
        elif isinstance(c, ImageContent):
            content_list.append("(base64 encoded image ommitted)")
        elif isinstance(c.resource, TextResourceContents):
            content_list.append(c.resource.text)

    return "\n\n".join(content_list)
