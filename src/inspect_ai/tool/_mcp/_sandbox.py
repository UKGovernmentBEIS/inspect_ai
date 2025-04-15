import sys
from contextlib import asynccontextmanager
from typing import TextIO

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import JSONRPCRequest, StdioServerParameters
from mcp.types import JSONRPCMessage, JSONRPCNotification, JSONRPCResponse

from inspect_ai.tool._tool_support_helpers import (
    exec_sandbox_notification,
    exec_sandbox_request,
    tool_container_sandbox,
)

from ._types import MCPServerContextEric


@asynccontextmanager
async def sandbox_client(
    server: StdioServerParameters,
    *,
    server_name: str,
    sandbox_name: str | None = None,
    errlog: TextIO = sys.stderr,
) -> MCPServerContextEric:
    sandbox_environment = await tool_container_sandbox(
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

    session_id = await exec_sandbox_request(
        sandbox=sandbox_environment,
        method="mcp_launch_server",
        params={"server_params": server.model_dump()},
        result_cls=int,
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
                            JSONRPCMessage(
                                await exec_sandbox_request(
                                    sandbox=sandbox_environment,
                                    method="mcp_send_request",
                                    params={
                                        "session_id": session_id,
                                        "request": root.model_dump(),
                                    },
                                    result_cls=JSONRPCResponse,
                                )
                            )
                        )
                    elif isinstance(root, JSONRPCNotification):
                        await exec_sandbox_notification(
                            sandbox=sandbox_environment,
                            method="mcp_send_notification",
                            params={
                                "session_id": session_id,
                                "notification": root.model_dump(),
                            },
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
            await exec_sandbox_request(
                sandbox=sandbox_environment,
                method="mcp_kill_server",
                params={"session_id": session_id},
                result_cls=type(None),
            )
