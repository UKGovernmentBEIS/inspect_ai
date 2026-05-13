import contextlib
import sys
from pathlib import Path
from typing import Any, AsyncIterator

import anyio
import pytest
from test_helpers.utils import (
    skip_if_no_docker,
    skip_if_no_mcp_package,
    skip_if_no_openai,
)

from inspect_ai import Task, eval, task
from inspect_ai._util.environ import environ_var
from inspect_ai.agent import react
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.solver import solver
from inspect_ai.tool import (
    MCPServer,
    ToolError,
    mcp_connection,
    mcp_server_stdio,
    mcp_tools,
)
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util import sandbox

MCP_TEST_SERVER = str(Path(__file__).parent / "mcp_test_server.py")


def _test_server() -> MCPServer:
    return mcp_server_stdio(command=sys.executable, args=[MCP_TEST_SERVER])


@skip_if_no_mcp_package
async def test_mcp_server_stdio():
    server = _test_server()
    async with mcp_connection(server):
        tools = await server.tools()
        tool_names = {ToolDef(t).name for t in tools}
        assert "echo" in tool_names
        assert "add" in tool_names
        assert "get_status" in tool_names
        assert "get_info" in tool_names


@skip_if_no_mcp_package
async def test_mcp_tool_call():
    server = _test_server()
    async with mcp_connection(server):
        tools = await server.tools()
        echo_tool = next(t for t in tools if ToolDef(t).name == "echo")
        result = await echo_tool(message="hello")
        assert isinstance(result, list)
        assert result[0].text == "hello"


@skip_if_no_mcp_package
async def test_mcp_filter():
    server = _test_server()
    filtered = mcp_tools(server, tools=["get_*"])
    async with mcp_connection(server):
        tools = await filtered.tools()
        tool_names = {ToolDef(t).name for t in tools}
        assert tool_names == {"get_status", "get_info"}


@skip_if_no_mcp_package
async def test_mcp_tool_call_timeout_becomes_tool_error():
    """A sandbox-style transport timeout should surface as ToolError.

    Sandbox MCP must not raise TimeoutError from the writer task: that collapses
    the task group and the client sees CancelledError. Instead the writer sends
    a JSON-RPC error for the pending request (see ``sandbox_client``); the MCP
    client raises ``McpError``, which ``_local.py`` maps to ``ToolError``.
    """
    from anyio.streams.memory import (
        MemoryObjectReceiveStream,
        MemoryObjectSendStream,
    )
    from mcp.shared.message import SessionMessage
    from mcp.types import (
        INTERNAL_ERROR,
        ErrorData,
        InitializeResult,
        Implementation,
        JSONRPCError,
        JSONRPCMessage,
        JSONRPCNotification,
        JSONRPCRequest,
        JSONRPCResponse,
        LATEST_PROTOCOL_VERSION,
        ServerCapabilities,
    )
    from mcp.types import Tool as MCPTool

    from inspect_ai.tool._mcp._local import MCPServerLocalSession

    @contextlib.asynccontextmanager
    async def timing_out_client() -> AsyncIterator[Any]:
        # Mirrors sandbox_client: writer forwards or injects JSON-RPC errors.
        read_stream_writer: MemoryObjectSendStream
        read_stream: MemoryObjectReceiveStream
        write_stream: MemoryObjectSendStream
        write_stream_reader: MemoryObjectReceiveStream

        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        async def stdin_writer() -> None:
            try:
                async with write_stream_reader:
                    async for message in write_stream_reader:
                        root = message.message.root
                        if isinstance(root, JSONRPCRequest):
                            if root.method == "initialize":
                                init = InitializeResult(
                                    protocolVersion=LATEST_PROTOCOL_VERSION,
                                    capabilities=ServerCapabilities(),
                                    serverInfo=Implementation(name="test", version="1"),
                                )
                                await read_stream_writer.send(
                                    SessionMessage(
                                        message=JSONRPCMessage(
                                            JSONRPCResponse(
                                                jsonrpc="2.0",
                                                id=root.id,
                                                result=init.model_dump(
                                                    by_alias=True, exclude_none=True
                                                ),
                                            )
                                        )
                                    )
                                )
                            elif root.method == "tools/call":
                                await anyio.sleep(0.05)
                                await read_stream_writer.send(
                                    SessionMessage(
                                        message=JSONRPCMessage(
                                            JSONRPCError(
                                                jsonrpc="2.0",
                                                id=root.id,
                                                error=ErrorData(
                                                    code=INTERNAL_ERROR,
                                                    message="simulated transport timeout",
                                                    data=None,
                                                ),
                                            )
                                        )
                                    )
                                )
                            else:
                                pytest.fail(
                                    f"unexpected JSON-RPC method {root.method!r}"
                                )
                        elif isinstance(root, JSONRPCNotification):
                            pass
                        else:
                            pytest.fail(f"unexpected message type {message!r}")
            except anyio.ClosedResourceError:
                pass

        async with anyio.create_task_group() as tg:
            tg.start_soon(stdin_writer)
            try:
                yield read_stream, write_stream
            finally:
                pass

    session = MCPServerLocalSession(
        timing_out_client,
        name="test-timeout",
        events=False,
    )
    fake_tool = MCPTool(
        name="slow_tool",
        description="A tool that times out",
        inputSchema={"type": "object", "properties": {}},
    )
    tool_def = session._tool_def_from_mcp_tool(fake_tool)

    def _flatten(exc: BaseException) -> list[BaseException]:
        if isinstance(exc, BaseExceptionGroup):
            return [leaf for sub in exc.exceptions for leaf in _flatten(sub)]
        return [exc]

    with pytest.raises(BaseExceptionGroup) as exc_info:
        await tool_def.tool()
    assert any(
        isinstance(exc, ToolError) and "simulated transport timeout" in str(exc)
        for exc in _flatten(exc_info.value)
    )


@skip_if_no_mcp_package
async def test_mcp_connection_refcount():
    server = _test_server()

    # First entry — opens connection
    async with mcp_connection(server):
        tools = await server.tools()
        assert len(tools) > 0

        # Nested entry — reuses connection via refcount
        async with mcp_connection(server):
            tools_inner = await server.tools()
            assert len(tools_inner) > 0

        # After inner exit — connection still alive (refcount > 0)
        tools_after = await server.tools()
        assert len(tools_after) > 0

    # After outer exit — connection closed. Re-entering should work.
    async with mcp_connection(server):
        tools_reopen = await server.tools()
        assert len(tools_reopen) > 0


# to run this test:
# - git clone https://github.com/modelcontextprotocol/python-sdk
# - pip install python-sdk/examples/servers/simple-tool/
# - mcp-simple-tool --transport sse --port 8000
# - comment out the skip decorator below


@pytest.mark.skip
async def test_mcp_server_sse():
    from inspect_ai.tool import mcp_server_sse

    server = mcp_server_sse(url="http://localhost:8000/sse")

    _, output = await get_model("openai/gpt-4o").generate_loop(
        "Use the fetch tool to read the website at https://example.com/, then please tell me what is there.",
        tools=server,
    )
    assert "example.com" in output.completion


# to run this test
# - git clone https://github.com/modelcontextprotocol/python-sdk
# - uv run python-sdk/examples/snippets/servers/streamable_config.py
# - comment out the skip decorator below


@pytest.mark.skip
async def test_mcp_server_http():
    from inspect_ai.tool import mcp_server_http

    server = mcp_server_http(url="http://localhost:8000/mcp")

    _, output = await get_model("openai/gpt-4o").generate_loop(
        "Please call the greet() tool with the name 'Bob'",
        tools=server,
    )
    assert "bob" in output.completion.lower()


@task
def react_mcp_task():
    server = mcp_server_stdio(command=sys.executable, args=[MCP_TEST_SERVER])
    return Task(
        dataset=MemoryDataset(
            [Sample("Use the add tool to compute 2 + 3. Report the result.")]
        ),
        solver=react(
            name="tool_worker",
            prompt="Use the available tools to solve the problem.",
            tools=[mcp_tools(server)],
        ),
        config=GenerateConfig(max_messages=10),
    )


@skip_if_no_openai
@skip_if_no_mcp_package
def test_react_mcp_connection():
    log = eval(react_mcp_task(), model="openai/gpt-4o")[0]
    assert log.status == "success"
    assert log.samples


@skip_if_no_openai
@skip_if_no_mcp_package
async def test_mcp_sampling_fn():
    from mcp.types import CreateMessageRequestParams, SamplingMessage, TextContent

    from inspect_ai.tool._mcp.sampling import sampling_fn

    with environ_var("INSPECT_EVAL_MODEL", "openai/gpt-4o"):
        result = await sampling_fn(
            None,
            CreateMessageRequestParams(
                messages=[
                    SamplingMessage(
                        role="user",
                        content=TextContent(type="text", text="What color is the sky?"),
                    )
                ],
                systemPrompt="You are a helpful assistant.",
                temperature=0.8,
                maxTokens=2048,
            ),
        )
        assert result.role == "assistant"
        assert isinstance(result.content, TextContent)
        assert "sky" in result.content.text or "mockllm" in result.content.text


@pytest.mark.slow
@skip_if_no_docker
def test_mcp_server_sandbox_nodejs():
    @solver
    def run_mcp_server():
        async def solve(state, generate):
            result = await sandbox().exec(["mcp-server-filesystem", "/"])
            if "MCP Filesystem Server" not in result.stderr:
                raise ValueError("Failed to run server")

            return state

        return solve

    dockerfile = Path(__file__).parent / "docker-mcp-server" / "Dockerfile"
    log = eval(
        Task(solver=[run_mcp_server()], sandbox=("docker", dockerfile.as_posix()))
    )[0]
    assert log.status == "success"
