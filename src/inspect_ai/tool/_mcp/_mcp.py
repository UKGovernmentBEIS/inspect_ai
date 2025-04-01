from contextlib import AsyncExitStack, _AsyncGeneratorContextManager
from pathlib import Path
from typing import Any, Literal, TypeAlias

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

from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai.tool._tool import Tool, ToolError, ToolResult
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_params import ToolParams

from ._types import McpClient

McpClientContext: TypeAlias = _AsyncGeneratorContextManager[
    tuple[
        MemoryObjectReceiveStream[JSONRPCMessage | Exception],
        MemoryObjectSendStream[JSONRPCMessage],
    ]
]


class McpClientImpl(McpClient):
    def __init__(
        self,
        client: McpClientContext,
    ) -> None:
        super().__init__()
        self._client = client
        self._session: ClientSession | None = None
        self._exit_stack = AsyncExitStack()

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("Attempted to access session before it is initialized")
        return self._session

    async def initialize(self) -> None:
        await self._ensure_session()

    async def list_tools(self) -> list[Tool]:
        await self._ensure_session()

        mcp_tools = (await self.session.list_tools()).tools

        tool_defs: list[ToolDef] = []
        for mcp_tool in mcp_tools:

            async def execute(**kwargs: Any) -> ToolResult:
                result = await self.session.call_tool(mcp_tool.name, kwargs)
                if result.isError:
                    raise ToolError(tool_result_as_text(result.content))

                return tool_result_as_content_list(result.content)

            tool_defs.append(
                ToolDef(
                    execute,
                    name=mcp_tool.name,
                    description=mcp_tool.description,
                    parameters=ToolParams.model_validate(mcp_tool.inputSchema),
                )
            )

        return [tool_def.as_tool() for tool_def in tool_defs]

    async def close(self) -> None:
        await self._exit_stack.aclose()

    async def _ensure_session(self) -> None:
        if self._session is None:
            streams = await self._exit_stack.enter_async_context(self._client)
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(*streams)
            )
            await self._session.initialize()


def create_sse_client(
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> McpClient:
    return McpClientImpl(sse_client(url, headers, timeout, sse_read_timeout))


def create_stdio_client(
    command: str,
    args: list[str] = [],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    encoding: str = "utf-8",
    encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict",
) -> McpClient:
    return McpClientImpl(
        stdio_client(
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
