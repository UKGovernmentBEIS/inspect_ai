import sys
from contextlib import asynccontextmanager
from typing import TextIO

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import JSONRPCRequest, StdioServerParameters
from mcp.types import JSONRPCMessage, JSONRPCNotification

from inspect_ai.tool._tool_support_helpers import (
    exec_model_request,
    exec_notification,
    exec_scalar_request,
    tool_support_sandbox,
)

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
    (sandbox_environment, _) = await tool_support_sandbox(
        "mcp support", sandbox_name=sandbox_name
    )

    # read_stream is remote process's stdout
    read_stream: MemoryObjectReceiveStream[JSONRPCMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[JSONRPCMessage | Exception]

    # write_stream is remote process's stdin
    write_stream: MemoryObjectSendStream[JSONRPCMessage]
    write_stream_reader: MemoryObjectReceiveStream[JSONRPCMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    session_id = await exec_scalar_request(
        sandbox=sandbox_environment,
        method="mcp_launch_server",
        params={"server_params": server.model_dump()},
        result_type=int,
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
                    root = message.root
                    if isinstance(root, JSONRPCRequest):
                        await read_stream_writer.send(
                            await exec_model_request(
                                sandbox=sandbox_environment,
                                method="mcp_send_request",
                                params={
                                    "session_id": session_id,
                                    "request": root.model_dump(),
                                },
                                result_type=JSONRPCMessage,
                                timeout=timeout,
                            )
                        )
                    elif isinstance(root, JSONRPCNotification):
                        await exec_notification(
                            sandbox=sandbox_environment,
                            method="mcp_send_notification",
                            params={
                                "session_id": session_id,
                                "notification": root.model_dump(),
                            },
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
                sandbox=sandbox_environment,
                method="mcp_kill_server",
                params={"session_id": session_id},
                result_type=type(None),
                timeout=timeout,
            )
