import contextlib
from contextlib import AsyncExitStack, _AsyncGeneratorContextManager
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Literal, TypeAlias

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import (
    EmbeddedResource,
    ImageContent,
    JSONRPCMessage,
    TextContent,
    TextResourceContents,
)
from mcp.types import (
    Tool as MCPTool,
)
from typing_extensions import override

from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai.tool._tool import Tool, ToolError, ToolResult
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_params import ToolParams

from ._types import MCPServer

MCPServerContext: TypeAlias = _AsyncGeneratorContextManager[
    tuple[
        MemoryObjectReceiveStream[JSONRPCMessage | Exception],
        MemoryObjectSendStream[JSONRPCMessage],
    ]
]


class MCPServerImpl(MCPServer):
    def __init__(self, client: Callable[[], MCPServerContext]) -> None:
        super().__init__()
        self._client = client
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None

    @override
    async def _connect(self) -> None:
        assert self._session is None
        assert self._exit_stack is None
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()
        read, write = await self._exit_stack.enter_async_context(self._client())
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()

    @override
    async def _close(self) -> None:
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

                        return tool_result_as_content_list(result.content)

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
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session


def create_server_sse(
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> MCPServer:
    return MCPServerImpl(lambda: sse_client(url, headers, timeout, sse_read_timeout))


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
        )
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


def tool_result_as_content_list(
    content: list[TextContent | ImageContent | EmbeddedResource],
) -> list[Content]:
    content_list: list[Content] = []
    for c in content:
        if isinstance(c, TextContent):
            content_list.append(ContentText(text=c.text))
        elif isinstance(c, ImageContent):
            content_list.append(
                ContentImage(image=f"data:image/{c.mimeType};base64,{c.data}")
            )
        elif isinstance(c.resource, TextResourceContents):
            content_list.append(ContentText(text=c.resource.text))

    return content_list
