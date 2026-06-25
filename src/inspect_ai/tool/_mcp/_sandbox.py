import sys
from contextlib import asynccontextmanager
from logging import getLogger
from typing import TextIO

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import JSONRPCRequest, StdioServerParameters
from mcp.shared.message import SessionMessage
from mcp.types import (
    INTERNAL_ERROR,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
)

from inspect_ai._util._json_rpc import (
    exec_model_request,
    exec_notification,
    exec_scalar_request,
)
from inspect_ai.tool._sandbox_tools_utils._error_mapper import (
    SandboxToolsErrorMapper,
)
from inspect_ai.tool._sandbox_tools_utils.sandbox import sandbox_with_injected_tools
from inspect_ai.util._sandbox._cli import SANDBOX_CLI
from inspect_ai.util._sandbox._json_rpc_transport import SandboxJSONRPCTransport

from ._context import MCPServerContext

logger = getLogger(__name__)

# Default per-request timeout (seconds) applied when a sandbox MCP server is
# created without an explicit `timeout`. Shared so the in-sandbox transport
# timeout and the host-side MCP read timeout normalize to the same value.
DEFAULT_SANDBOX_TIMEOUT = 180

# Upper bound (seconds) on the best-effort server shutdown performed during
# `sandbox_client` teardown. Kept short and independent of the per-request
# timeout so a slow/broken transport cannot stall teardown.
_KILL_SERVER_TIMEOUT = 30


# Pardon the type: ignore's here. This code is a modified clone of Anthropic code
# for stdio_client. In their case, they don't provide a type hint for the return
# value. We suspect that if they did, they'd encounter the same issues we're
# suppressing. Nevertheless, we're confident that the runtime behavior of the
# code is what we want, and that the errors are purely in the type domain.
@asynccontextmanager  # type: ignore
async def sandbox_client(  # type: ignore
    server: StdioServerParameters,
    *,
    sandbox_name: str | None = None,
    errlog: TextIO = sys.stderr,
    timeout: int | None = None,  # default DEFAULT_SANDBOX_TIMEOUT seconds
) -> MCPServerContext:  # type: ignore
    timeout = timeout or DEFAULT_SANDBOX_TIMEOUT
    sandbox_environment = await sandbox_with_injected_tools(sandbox_name=sandbox_name)

    # Create transport for all RPC calls
    transport = SandboxJSONRPCTransport(sandbox_environment, SANDBOX_CLI)

    # read_stream is remote process's stdout
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    # write_stream is remote process's stdin
    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    session_id = await exec_scalar_request(
        method="mcp_launch_server",
        params={"server_params": server.model_dump()},
        result_type=int,
        transport=transport,
        error_mapper=SandboxToolsErrorMapper,
        timeout=timeout,
    )

    async def stdout_reader() -> None:
        # This is NYI until we support unsolicited messages from the sandbox
        # back to the client
        pass

    async def stdin_writer() -> None:
        async def send_to_read_stream(item: SessionMessage) -> None:
            try:
                await read_stream_writer.send(item)
            except anyio.ClosedResourceError:
                # Let any pending cancellation propagate even though we swallowed
                # the closed-stream error.
                await anyio.lowlevel.checkpoint()

        try:
            async with write_stream_reader:
                # This reads messages until the stream is closed
                async for message in write_stream_reader:
                    root = message.message.root
                    if isinstance(root, JSONRPCRequest):
                        try:
                            response = await exec_model_request(
                                method="mcp_send_request",
                                params={
                                    "session_id": session_id,
                                    "request": root.model_dump(),
                                },
                                result_type=JSONRPCMessage,
                                transport=transport,
                                error_mapper=SandboxToolsErrorMapper,
                                timeout=timeout,
                            )
                        except Exception as ex:
                            # Do not let transport failures propagate: that would
                            # collapse the task group and cancel the MCP client,
                            # which surfaces as a bare CancelledError on call_tool.
                            # Turn it into a JSON-RPC error on the same request id
                            # so ClientSession raises McpError and _local.py maps
                            # it to ToolError. (Cancelled / KeyboardInterrupt
                            # inherit from BaseException and still propagate.)
                            if isinstance(ex, TimeoutError):
                                error_message = (
                                    "MCP request timed out before completing."
                                )
                            else:
                                error_message = f"MCP request failed before completing ({type(ex).__name__}): {ex}"
                            await send_to_read_stream(
                                SessionMessage(
                                    message=JSONRPCMessage(
                                        JSONRPCError(
                                            jsonrpc="2.0",
                                            id=root.id,
                                            error=ErrorData(
                                                code=INTERNAL_ERROR,
                                                message=error_message,
                                                data=None,
                                            ),
                                        )
                                    )
                                )
                            )
                            continue
                        await send_to_read_stream(
                            SessionMessage(message=response),
                        )
                    elif isinstance(root, JSONRPCNotification):
                        try:
                            await exec_notification(
                                method="mcp_send_notification",
                                params={
                                    "session_id": session_id,
                                    "notification": root.model_dump(),
                                },
                                transport=transport,
                                timeout=timeout,
                            )
                        except Exception as ex:
                            # Notifications are fire-and-forget per JSON-RPC: there
                            # is no request id to attach an error to, and the MCP
                            # client does not block on them. Log and continue —
                            # subsequent requests may still succeed.
                            logger.warning(
                                "Sandbox MCP notification dropped after transport "
                                "failure (%s): %s",
                                type(ex).__name__,
                                ex,
                            )
                    else:
                        assert False, f"Unexpected message type {message=}"

        except anyio.ClosedResourceError:
            # Let any pending cancellation propagate even though we swallowed
            # the closed-stream error.
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)

        try:
            yield read_stream, write_stream
        finally:
            # Best-effort server shutdown. This runs while the surrounding task
            # group is being torn down, so it must neither hang nor raise: a
            # slow or broken transport here would otherwise corrupt the
            # cancel-scope unwinding and surface as an inscrutable "Attempted to
            # exit a cancel scope ..." RuntimeError that masks the real failure.
            # We shield so a pending outer cancellation can't abort the kill
            # mid-flight, bound it with our own deadline, and swallow any error.
            try:
                with anyio.move_on_after(_KILL_SERVER_TIMEOUT, shield=True):
                    await exec_scalar_request(
                        method="mcp_kill_server",
                        params={"session_id": session_id},
                        result_type=type(None),
                        transport=transport,
                        error_mapper=SandboxToolsErrorMapper,
                        timeout=_KILL_SERVER_TIMEOUT,
                    )
            except Exception as ex:
                logger.warning(
                    "Sandbox MCP server shutdown failed (%s): %s",
                    type(ex).__name__,
                    ex,
                )
