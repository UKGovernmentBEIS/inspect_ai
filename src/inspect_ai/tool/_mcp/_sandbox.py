import sys
from contextlib import asynccontextmanager
from typing import TextIO

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import JSONRPCRequest, StdioServerParameters
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCNotification

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
    timeout: int | None = None,  # default 180 seconds
) -> MCPServerContext:  # type: ignore
    timeout = timeout or 180
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
        try:
            async with write_stream_reader:
                # This reads messages until the stream is closed
                async for message in write_stream_reader:
                    root = message.message.root
                    if isinstance(root, JSONRPCRequest):
                        await read_stream_writer.send(
                            SessionMessage(
                                message=await exec_model_request(
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
                            )
                        )
                    elif isinstance(root, JSONRPCNotification):
                        await exec_notification(
                            method="mcp_send_notification",
                            params={
                                "session_id": session_id,
                                "notification": root.model_dump(),
                            },
                            transport=transport,
                            timeout=timeout,
                        )
                    else:
                        assert False, f"Unexpected message type {message=}"

        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)

        try:
            yield read_stream, write_stream
        finally:
            await exec_scalar_request(
                method="mcp_kill_server",
                params={"session_id": session_id},
                result_type=type(None),
                transport=transport,
                error_mapper=SandboxToolsErrorMapper,
                timeout=timeout,
            )
