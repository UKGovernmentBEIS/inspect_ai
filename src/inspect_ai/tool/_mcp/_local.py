import contextlib
import sys
from contextlib import AsyncExitStack
from logging import getLogger
from pathlib import Path
from types import TracebackType
from typing import Any, AsyncIterator, Callable

import anyio
from mcp import McpError
from mcp.client.session import ClientSession, SamplingFnT
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import (
    AudioContent,
    EmbeddedResource,
    ImageContent,
    ResourceLink,
    TextContent,
    TextResourceContents,
)
from mcp.types import Tool as MCPTool
from typing_extensions import override

from inspect_ai._util._json_rpc import (
    JSONRPCErrorMapper,
    JSONRPCParamsType,
    exception_for_rpc_response_error,
)
from inspect_ai._util.format import format_function_call
from inspect_ai._util.trace import trace_action
from inspect_ai.tool._tool import Tool, ToolError, ToolParsingError, ToolResult
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_params import ToolParams

from ._context import MCPServerContext
from ._sandbox import sandbox_client
from ._types import MCPServer
from .sampling import as_inspect_content_list, sampling_fn

logger = getLogger(__name__)


class _McpErrorMapper(JSONRPCErrorMapper):
    """Error mapper for MCP server JSON-RPC errors.

    MCP servers are opaque — we don't know what server-defined error codes they
    might use, so all errors are mapped to ToolError/ToolParsingError so they
    are fed back to the model rather than crashing the eval.

    This preserves the behavior from when the MCP path called
    exception_for_rpc_response_error with server_error_mapper=None.

    TODO: Consider whether MCP can share SandboxToolsErrorMapper instead.
    """

    @staticmethod
    def server_error(
        code: int, message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        del code, method, params
        return ToolError(message)

    @staticmethod
    def invalid_params(
        message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        del method, params
        return ToolParsingError(message)

    @staticmethod
    def internal_error(
        message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        del method, params
        return ToolError(message)


class MCPServerLocal(MCPServer):
    def __init__(
        self,
        client: Callable[[], MCPServerContext],
        *,
        name: str,
        events: bool,
    ) -> None:
        super().__init__()
        self._client = client
        self._name = name
        self._events = events

    @override
    async def __aenter__(self) -> MCPServer:
        return await self._task_session().__aenter__()

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._task_session().__aexit__(exc_type, exc_val, exc_tb)

    @override
    async def tools(self) -> list[Tool]:
        return await self._task_session().tools()

    # create a separate MCPServer session per async task / server name
    _task_sessions: dict[str, "MCPServerLocalSession"] = {}

    def _task_session(self) -> "MCPServerLocalSession":
        task_id = anyio.get_current_task().id
        session_key = f"{task_id}_{self._name}"
        if session_key not in self._task_sessions:
            MCPServerLocal._task_sessions[session_key] = MCPServerLocalSession(
                self._client, name=self._name, events=self._events
            )
        return MCPServerLocal._task_sessions[session_key]


class MCPServerLocalSession(MCPServer):
    def __init__(
        self,
        client: Callable[[], MCPServerContext],
        *,
        name: str,
        events: bool,
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
    async def __aenter__(self) -> MCPServer:
        if self._session is not None:
            assert self._refcount > 0
            self._refcount = self._refcount + 1
        else:
            assert self._refcount == 0
            self._exit_stack = AsyncExitStack()
            await self._exit_stack.__aenter__()
            with trace_action(logger, "MCPServer", f"create client ({self._name})"):
                read, write, *_ = await self._exit_stack.enter_async_context(
                    self._client()
                )
            with trace_action(logger, "MCPServer", f"create session ({self._name})"):
                self._session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write, sampling_callback=self._sampling_fn())
                )
            with trace_action(
                logger, "MCPServer", f"initialize session ({self._name})"
            ):
                await self._session.initialize()
            self._refcount = 1

        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
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

    @override
    async def tools(self) -> list[Tool]:
        if self._cached_tool_list:
            mcp_tools = self._cached_tool_list
        else:
            async with self._client_session() as session:
                # get the underlying tools on the server
                with trace_action(logger, "MCPServer", f"list_tools {self._name}"):
                    mcp_tools = (await session.list_tools()).tools
                self._cached_tool_list = mcp_tools

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
                            e.error.code,
                            e.error.message,
                            mcp_tool.name,
                            kwargs,
                            error_mapper=_McpErrorMapper,
                        ) from e

                return as_inspect_content_list(result.content)  # type: ignore[return-value,arg-type]

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
                    read, write, *_ = await exit_stack.enter_async_context(
                        self._client()
                    )
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
    *,
    name: str,
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> MCPServer:
    return MCPServerLocal(
        lambda: sse_client(url, headers, timeout, sse_read_timeout),
        name=name,
        events=True,
    )


def create_server_streamablehttp(
    *,
    name: str,
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> MCPServer:
    return MCPServerLocal(
        lambda: streamablehttp_client(url, headers, timeout, sse_read_timeout),
        name=url,
        events=True,
    )


def create_server_stdio(
    *,
    name: str,
    command: str,
    args: list[str] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> MCPServer:
    return MCPServerLocal(
        lambda: stdio_client(
            StdioServerParameters(
                command=command,
                args=args if args is not None else [],
                cwd=cwd,
                env=env,
            )
        ),
        name=name,
        events=True,
    )


def create_server_sandbox(
    *,
    name: str,
    command: str,
    args: list[str] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    sandbox: str | None = None,
    timeout: int | None = None,
) -> MCPServer:
    # TODO: Confirm the lifetime concepts. By the time a request makes it to the
    # sandbox, it's going to need both a session id and a server "name".
    return MCPServerLocal(
        lambda: sandbox_client(
            StdioServerParameters(
                command=command,
                args=args if args is not None else [],
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
    content: list[
        TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource
    ],
) -> str:
    content_list: list[str] = []
    for c in content:
        if isinstance(c, TextContent):
            content_list.append(c.text)
        elif isinstance(c, ImageContent):
            content_list.append("(base64 encoded image omitted)")
        elif isinstance(c, AudioContent):
            content_list.append("(base64 encoded audio omitted)")
        elif isinstance(c, ResourceLink):
            content_list.append(f"{c.description} ({c.uri})")
        elif isinstance(c.resource, TextResourceContents):
            content_list.append(c.resource.text)

    return "\n\n".join(content_list)
