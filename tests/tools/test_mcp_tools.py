import contextlib
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Callable

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
from inspect_ai.model import get_model
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

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup

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


def _flatten_exc(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for sub in exc.exceptions for leaf in _flatten_exc(sub)]
    return [exc]


def _make_simulated_mcp_client(
    on_tool_call: Callable[[Any], Any],
    *,
    unexpected_methods: list[str],
):
    """Build a fake MCP transport context manager.

    The writer responds to ``initialize`` with a valid handshake, delegates
    ``tools/call`` to ``on_tool_call`` (which returns a ``JSONRPCMessage`` to
    send back), accepts notifications, and records anything else into
    ``unexpected_methods`` (asserted by callers — raising from the writer
    task wraps the failure in an ExceptionGroup, which obscures the message).
    """
    from anyio.streams.memory import (
        MemoryObjectReceiveStream,
        MemoryObjectSendStream,
    )
    from mcp.shared.message import SessionMessage
    from mcp.types import (
        LATEST_PROTOCOL_VERSION,
        Implementation,
        InitializeResult,
        JSONRPCMessage,
        JSONRPCNotification,
        JSONRPCRequest,
        JSONRPCResponse,
        ServerCapabilities,
    )

    @contextlib.asynccontextmanager
    async def client() -> AsyncIterator[Any]:
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
                                await read_stream_writer.send(on_tool_call(root))
                            else:
                                unexpected_methods.append(root.method)
                        elif isinstance(root, JSONRPCNotification):
                            pass
                        else:
                            unexpected_methods.append(
                                f"<message type {type(root).__name__}>"
                            )
            except anyio.ClosedResourceError:
                pass

        async with anyio.create_task_group() as tg:
            tg.start_soon(stdin_writer)
            yield read_stream, write_stream

    return client


@skip_if_no_mcp_package
async def test_mcp_tool_call_timeout_becomes_tool_error() -> None:
    """A sandbox-style transport timeout should surface as ToolError.

    Sandbox MCP must not raise TimeoutError from the writer task: that collapses
    the task group and the client sees CancelledError. Instead the writer sends
    a JSON-RPC error for the pending request (see ``sandbox_client``); the MCP
    client raises ``McpError``, which ``_local.py`` maps to ``ToolError``.

    Also asserts ``inner_exception()`` (used by ``_call_tools.py``) unwraps the
    surrounding ExceptionGroup back to the ToolError the model needs to see.
    """
    from mcp.shared.message import SessionMessage
    from mcp.types import (
        INTERNAL_ERROR,
        ErrorData,
        JSONRPCError,
        JSONRPCMessage,
    )
    from mcp.types import Tool as MCPTool

    from inspect_ai.tool._mcp._local import MCPServerLocalSession
    from inspect_ai.util._anyio import inner_exception

    def on_tool_call(root: Any) -> SessionMessage:
        return SessionMessage(
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

    unexpected: list[str] = []
    client = _make_simulated_mcp_client(on_tool_call, unexpected_methods=unexpected)

    session = MCPServerLocalSession(client, name="test-timeout", events=False)
    fake_tool = MCPTool(
        name="slow_tool",
        description="A tool that times out",
        inputSchema={"type": "object", "properties": {}},
    )
    tool_def = session._tool_def_from_mcp_tool(fake_tool)

    with pytest.raises(BaseExceptionGroup) as exc_info:
        await tool_def.tool()

    assert not unexpected, f"writer saw unexpected methods: {unexpected}"
    leaves = _flatten_exc(exc_info.value)
    assert any(
        isinstance(exc, ToolError) and "simulated transport timeout" in str(exc)
        for exc in leaves
    )

    # _call_tools.py:167-169 unwraps the group via inner_exception() before its
    # except ToolError clause; verify that path resolves to ToolError.
    assert isinstance(exc_info.value, Exception)
    unwrapped = inner_exception(exc_info.value)
    assert isinstance(unwrapped, ToolError)
    assert "simulated transport timeout" in str(unwrapped)


def _patch_sandbox_module(monkeypatch, exec_model_request_impl):
    """Patch the imports in `_sandbox` so `sandbox_client` runs without a real sandbox."""
    from inspect_ai.tool._mcp import _sandbox as sandbox_module

    class _FakeTransport:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    async def _fake_sandbox_with_injected_tools(*, sandbox_name: Any = None) -> None:
        return None

    async def _fake_exec_scalar_request(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("method") == "mcp_launch_server":
            return 1
        return None

    async def _noop_exec_notification(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        sandbox_module,
        "sandbox_with_injected_tools",
        _fake_sandbox_with_injected_tools,
    )
    monkeypatch.setattr(sandbox_module, "SandboxJSONRPCTransport", _FakeTransport)
    monkeypatch.setattr(
        sandbox_module, "exec_scalar_request", _fake_exec_scalar_request
    )
    monkeypatch.setattr(sandbox_module, "exec_model_request", exec_model_request_impl)
    monkeypatch.setattr(sandbox_module, "exec_notification", _noop_exec_notification)
    return sandbox_module


async def _drive_sandbox_request(sandbox_module):
    """Send one tools/call request through `sandbox_client` and return the response."""
    from mcp import StdioServerParameters
    from mcp.shared.message import SessionMessage
    from mcp.types import JSONRPCMessage, JSONRPCRequest

    server_params = StdioServerParameters(command="fake")
    async with sandbox_module.sandbox_client(server_params) as (
        read_stream,
        write_stream,
    ):
        await write_stream.send(
            SessionMessage(
                message=JSONRPCMessage(
                    JSONRPCRequest(jsonrpc="2.0", id=42, method="tools/call", params={})
                )
            )
        )
        response_msg = await read_stream.receive()
        # Close write_stream so the writer task can exit; ClientSession would
        # normally do this on shutdown.
        await write_stream.aclose()
    return response_msg


@skip_if_no_mcp_package
async def test_sandbox_writer_synthesizes_jsonrpc_error_for_non_timeout(monkeypatch):
    """Non-TimeoutError exceptions from ``exec_model_request`` also synthesize errors.

    Any exception from ``exec_model_request`` (not just TimeoutError) must be
    converted to a JSON-RPC error response, so the MCP client sees a normal
    error rather than CancelledError from a collapsed task group.
    """
    from mcp.types import INTERNAL_ERROR, JSONRPCError

    async def _raising_exec_model_request(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    sandbox_module = _patch_sandbox_module(monkeypatch, _raising_exec_model_request)
    response_msg = await _drive_sandbox_request(sandbox_module)

    root = response_msg.message.root
    assert isinstance(root, JSONRPCError)
    assert root.id == 42
    assert root.error.code == INTERNAL_ERROR
    assert "RuntimeError" in root.error.message
    assert "boom" in root.error.message


@skip_if_no_mcp_package
async def test_sandbox_writer_uses_friendly_message_for_timeout(monkeypatch):
    """TimeoutError gets the friendlier 'timed out' wording the model expects."""
    from mcp.types import INTERNAL_ERROR, JSONRPCError

    async def _timeout_exec_model_request(*args: Any, **kwargs: Any) -> Any:
        raise TimeoutError("transport deadline exceeded")

    sandbox_module = _patch_sandbox_module(monkeypatch, _timeout_exec_model_request)
    response_msg = await _drive_sandbox_request(sandbox_module)

    root = response_msg.message.root
    assert isinstance(root, JSONRPCError)
    assert root.id == 42
    assert root.error.code == INTERNAL_ERROR
    assert root.error.message == "MCP request timed out before completing."


@skip_if_no_mcp_package
async def test_sandbox_writer_logs_warning_when_notification_fails(monkeypatch):
    """A failed notification is logged and dropped, never collapsing the writer.

    Notifications have no JSON-RPC id to respond on; the writer must log and
    continue rather than letting the exception escape the task.
    """
    from mcp import StdioServerParameters
    from mcp.shared.message import SessionMessage
    from mcp.types import JSONRPCMessage, JSONRPCNotification

    from inspect_ai.tool._mcp import _sandbox as sandbox_module

    class _FakeTransport:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    async def _fake_sandbox_with_injected_tools(*, sandbox_name: Any = None) -> None:
        return None

    async def _fake_exec_scalar_request(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("method") == "mcp_launch_server":
            return 1
        return None

    notification_called = anyio.Event()

    async def _raising_exec_notification(*args: Any, **kwargs: Any) -> None:
        notification_called.set()
        raise TimeoutError("notify timeout")

    captured = []

    def _capture_warning(msg: str, *args: Any, **kwargs: Any) -> None:
        captured.append(msg % args if args else msg)

    monkeypatch.setattr(
        sandbox_module,
        "sandbox_with_injected_tools",
        _fake_sandbox_with_injected_tools,
    )
    monkeypatch.setattr(sandbox_module, "SandboxJSONRPCTransport", _FakeTransport)
    monkeypatch.setattr(
        sandbox_module, "exec_scalar_request", _fake_exec_scalar_request
    )
    monkeypatch.setattr(sandbox_module, "exec_notification", _raising_exec_notification)
    monkeypatch.setattr(sandbox_module.logger, "warning", _capture_warning)

    server_params = StdioServerParameters(command="fake")
    async with sandbox_module.sandbox_client(server_params) as (
        read_stream,
        write_stream,
    ):
        await write_stream.send(
            SessionMessage(
                message=JSONRPCMessage(
                    JSONRPCNotification(
                        jsonrpc="2.0", method="notifications/initialized"
                    )
                )
            )
        )
        with anyio.fail_after(2):
            await notification_called.wait()
        # Close write_stream so the writer task can exit; ClientSession would
        # normally do this on shutdown.
        await write_stream.aclose()

    assert len(captured) == 1
    assert "notification dropped" in captured[0]
    assert "TimeoutError" in captured[0]
    assert "notify timeout" in captured[0]


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
        message_limit=10,
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
