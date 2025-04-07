import sys
from contextlib import asynccontextmanager
from typing import TextIO

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import StdioServerParameters
from mcp.types import JSONRPCMessage, JSONRPCResponse

from inspect_ai.tool._tool_support_helpers import (
    exec_sandbox_rpc,
    tool_container_sandbox,
)
from inspect_ai.util import sandbox

from ._types import MCPServerContextEric


@asynccontextmanager
async def sandbox_client(
    server: StdioServerParameters,
    sandbox_name: str | None = None,
    errlog: TextIO = sys.stderr,
) -> MCPServerContextEric:
    # TODO: The way I modeled this for inspect-tool-support did not support
    # passing in a sandbox name. `tool_container_sandbox` just returns the
    # first sandbox found with the support code installed. I could refactor the
    # code to separate the validation of compatibility from the finding of the
    # sandbox.
    sb1 = sandbox(sandbox_name)  # noqa: F841
    sandbox_environment = await tool_container_sandbox("mcp support")

    # read_stream is remote process's stdout
    read_stream: MemoryObjectReceiveStream[JSONRPCMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[JSONRPCMessage | Exception]

    # write_stream is remote process's stdin
    write_stream: MemoryObjectSendStream[JSONRPCMessage]
    write_stream_reader: MemoryObjectReceiveStream[JSONRPCMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    remote_pid = await exec_sandbox_rpc(
        sandbox=sandbox_environment,
        method="create_process",
        params=server.model_dump(),
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
                    await read_stream_writer.send(
                        JSONRPCMessage(
                            await exec_sandbox_rpc(
                                sandbox=sandbox_environment,
                                method="proxy_request",
                                params={"inner_request": message},
                                result_cls=JSONRPCResponse,
                            )
                        )
                    )

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
                method="kill_process",
                params={"pid": remote_pid},
                result_cls=str,  # TODO: Do we need to add None support?
            )
