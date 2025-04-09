import sys
import uuid
from contextlib import asynccontextmanager
from typing import TextIO

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import JSONRPCRequest, StdioServerParameters
from mcp.types import JSONRPCMessage, JSONRPCNotification, JSONRPCResponse

from inspect_ai.tool._mcp._mcp_fake_sandbox import FakeSandbox, exec_sandbox_rpc

from ._types import MCPServerContextEric


@asynccontextmanager
async def sandbox_client(
    server: StdioServerParameters,
    *,
    server_name: str,
    sandbox_name: str | None = None,
    errlog: TextIO = sys.stderr,
) -> MCPServerContextEric:
    # TODO: The way I modeled this for inspect-tool-support did not support
    # passing in a sandbox name. `tool_container_sandbox` just returns the
    # first sandbox found with the support code installed. I could refactor the
    # code to separate the validation of compatibility from the finding of the
    # sandbox.
    # sb1 = sandbox(sandbox_name)  # noqa: F841
    # sandbox_environment = await tool_container_sandbox("mcp support")

    # read_stream is remote process's stdout
    read_stream: MemoryObjectReceiveStream[JSONRPCMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[JSONRPCMessage | Exception]

    # write_stream is remote process's stdin
    write_stream: MemoryObjectSendStream[JSONRPCMessage]
    write_stream_reader: MemoryObjectReceiveStream[JSONRPCMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    # TODO: Do the standard session creation code here
    server_id = str(uuid.uuid4())
    sandbox_environment = FakeSandbox()

    await exec_sandbox_rpc(
        sandbox=sandbox_environment,
        method="mcp_launch_server",
        params={"session_id": server_id, "server_params": server.model_dump()},
        result_cls=str,
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
                                await exec_sandbox_rpc(
                                    sandbox=sandbox_environment,
                                    method="mcp_send_request",
                                    params={"session_id": server_id, "request": root},
                                    result_cls=JSONRPCResponse,
                                )
                            )
                        )
                    elif isinstance(root, JSONRPCNotification):
                        await exec_sandbox_rpc(
                            sandbox=sandbox_environment,
                            method="mcp_send_notification",
                            params={"session_id": server_id, "notification": root},
                            result_cls=str,
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
            await exec_sandbox_rpc(
                sandbox=sandbox_environment,
                method="mcp_kill_server",
                params={"session_id": server_id},
                result_cls=str,
            )
