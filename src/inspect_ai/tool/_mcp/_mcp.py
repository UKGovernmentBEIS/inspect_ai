import contextlib
import sys
from contextlib import AsyncExitStack
from fnmatch import fnmatch
from logging import getLogger
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Literal

import anyio
from mcp import McpError
from mcp.client.session import ClientSession, SamplingFnT
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import (
    EmbeddedResource,
    ImageContent,
    TextContent,
    TextResourceContents,
)
from mcp.types import Tool as MCPTool
from typing_extensions import override

from inspect_ai._util.format import format_function_call
from inspect_ai._util.trace import trace_action
from inspect_ai.tool._json_rpc_helpers import exception_for_rpc_response_error
from inspect_ai.tool._tool import Tool, ToolError, ToolResult
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_params import ToolParams

from ._context import MCPServerContext
from ._sandbox import sandbox_client
from ._types import MCPServer
from .sampling import as_inspect_content, sampling_fn

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

    @override
    async def _connect(self) -> None:
        await self._task_session()._connect()

    @override
    async def _close(self) -> None:
        await self._task_session()._close()

    async def _list_tools(
        self, tools: Literal["all"] | list[str] = "all"
    ) -> list[Tool]:
        return await self._task_session()._list_tools(tools)

    # create a separate MCPServer session per async task / server name
    _task_sessions: dict[str, "MCPServerSession"] = {}

    def _task_session(self) -> "MCPServerSession":
        task_id = anyio.get_current_task().id
        session_key = f"{task_id}_{self._name}"
        if session_key not in self._task_sessions:
            MCPServerImpl._task_sessions[session_key] = MCPServerSession(
                self._client, name=self._name, events=self._events
            )
        return MCPServerImpl._task_sessions[session_key]


class MCPServerSession(MCPServer):
    def __init__(
        self, client: Callable[[], MCPServerContext], *, name: str, events: bool
    ) -> None:
        super().__init__()
        self._refcount = 0
        self._client = client
        self._name = name
        self._events = events
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._cached_tool_list: list[MCPTool] | None = None

    @override
    async def _connect(self) -> None:
        if self._session is not None:
            assert self._refcount > 0
            self._refcount = self._refcount + 1
        else:
            assert self._refcount == 0
            self._exit_stack = AsyncExitStack()
            await self._exit_stack.__aenter__()
            with trace_action(logger, "MCPServer", f"create client ({self._name})"):
                read, write = await self._exit_stack.enter_async_context(self._client())
            with trace_action(logger, "MCPServer", f"create session ({self._name})"):
                self._session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write, sampling_callback=self._sampling_fn())
                )
            with trace_action(
                logger, "MCPServer", f"initialize session ({self._name})"
            ):
                await self._session.initialize()
            self._refcount = 1

    @override
    async def _close(self) -> None:
        assert self._refcount > 0
        self._refcount = self._refcount - 1
        if self._refcount == 0:
            with trace_action(logger, "MCPServer", f"disconnect ({self._name})"):
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
        if self._cached_tool_list:
            mcp_tools = self._cached_tool_list
        else:
            async with self._client_session() as session:
                # get the underlying tools on the server
                with trace_action(logger, "MCPServer", f"list_tools {self._name}"):
                    mcp_tools = (await session.list_tools()).tools
                self._cached_tool_list = mcp_tools

        # filter them
        def include_tool(tool: MCPTool) -> bool:
            if tools == "all":
                return True
            else:
                return any([fnmatch(tool.name, t) for t in tools])

        mcp_tools = [mcp_tool for mcp_tool in mcp_tools if include_tool(mcp_tool)]

        # dynamically create tools
        return [
            self._tool_def_from_mcp_tool(mcp_tool).as_tool() for mcp_tool in mcp_tools
        ]

    def _tool_def_from_mcp_tool(self, mcp_tool: MCPTool) -> ToolDef:
        async def execute(**kwargs: Any) -> ToolResult:
            async with self._client_session() as tool_session:
                mcp_call = format_function_call(
                    mcp_tool.name, kwargs, width=sys.maxsize
                )
                with trace_action(
                    logger, "MCPServer", f"call_tool ({self._name}): {mcp_call}"
                ):
                    try:
                        result = await tool_session.call_tool(mcp_tool.name, kwargs)
                        if result.isError:
                            raise ToolError(tool_result_as_text(result.content))
                    except McpError as e:
                        # Some errors that are raised via McpError (e.g. -32603)
                        # need to be converted to ToolError so that they make it
                        # back to the model.
                        raise exception_for_rpc_response_error(
                            e.error.code, e.error.message, mcp_tool.name, kwargs
                        ) from e

                return [as_inspect_content(c) for c in result.content]

        # get parameters (fill in missing ones)
        parameters = ToolParams.model_validate(mcp_tool.inputSchema)
        for name, param in parameters.properties.items():
            param.description = param.description or name

        return ToolDef(
            execute,
            name=mcp_tool.name,
            description=mcp_tool.description,
            parameters=parameters,
        )

    # if we have been entered as a context manager then return that session,
    # otherwise, create a brand new session from the client
    @contextlib.asynccontextmanager
    async def _client_session(self) -> AsyncIterator[ClientSession]:
        # if _connect has been previously called and we still have the connection
        # to the session, we can just return nit
        if self._session is not None:
            yield self._session

        # otherwise, create a new session and yield it (it will be cleaned up
        # when the context manager exits)
        else:
            async with AsyncExitStack() as exit_stack:
                with trace_action(logger, "MCPServer", f"create client ({self._name})"):
                    read, write = await exit_stack.enter_async_context(self._client())
                with trace_action(
                    logger, "MCPServer", f"create session ({self._name})"
                ):
                    session = await exit_stack.enter_async_context(
                        ClientSession(
                            read, write, sampling_callback=self._sampling_fn()
                        )
                    )
                with trace_action(
                    logger, "MCPServer", f"initialize session ({self._name})"
                ):
                    await session.initialize()
                yield session

    def _sampling_fn(self) -> SamplingFnT | None:
        from inspect_ai.model._model import active_model

        if self._events and active_model() is not None:
            return sampling_fn
        else:
            return None


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
) -> MCPServer:
    return MCPServerImpl(
        lambda: stdio_client(
            StdioServerParameters(
                command=command,
                args=args,
                cwd=cwd,
                env=env,
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
    sandbox: str | None = None,
    timeout: int | None = None,
) -> MCPServer:
    # TODO: Confirm the lifetime concepts. By the time a request makes it to the
    # sandbox, it's going to need both a session id and a server "name".
    name = " ".join([command] + args)
    return MCPServerImpl(
        lambda: sandbox_client(
            StdioServerParameters(
                command=command,
                args=args,
                cwd=cwd,
                env=env,
            ),
            sandbox_name=sandbox,
            timeout=timeout,
        ),
        name=name,
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
