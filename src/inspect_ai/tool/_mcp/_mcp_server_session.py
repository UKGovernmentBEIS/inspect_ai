import asyncio
import sys
from typing import TextIO

import anyio
from anyio.abc import Process, TaskGroup
from anyio.streams.text import TextReceiveStream
from mcp import (
    ErrorData,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    StdioServerParameters,
)
from mcp.types import JSONRPCMessage, JSONRPCNotification


class MCPServerSession:
    """
    A wrapper around an MCP server process.

    It does not support unsolicited messages from the server to the client.
    """

    @classmethod
    async def create(
        cls, server_params: StdioServerParameters, errlog: TextIO = sys.stderr
    ) -> "MCPServerSession":
        tg = anyio.create_task_group()
        await tg.__aenter__()

        return cls(
            await anyio.open_process(
                [server_params.command, *server_params.args],
                env=server_params.env,
                stderr=errlog,
                cwd=server_params.cwd,
            ),
            server_params,
            tg,
        )

    def __init__(
        self,
        process: Process,
        server_params: StdioServerParameters,
        tg: TaskGroup,
    ) -> None:
        self._process = process
        self._server_params = server_params
        self._terminated = False
        self._pending_requests = dict[
            str | int, asyncio.Future[JSONRPCResponse | JSONRPCError]
        ]()

        self._tg = tg
        self._tg.start_soon(self._stdout_reader)

    async def send_request(
        self, request: JSONRPCRequest
    ) -> JSONRPCResponse | JSONRPCError:
        assert self._process.stdin, "Opened process is missing stdin"

        id = request.id
        assert id not in self._pending_requests, f"Request with id {id} already exists"
        future = asyncio.Future[JSONRPCResponse | JSONRPCError]()
        self._pending_requests[id] = future

        print(f"→ {request.model_dump_json(by_alias=True, exclude_none=True)}")
        await self._process.stdin.send(
            (request.model_dump_json(by_alias=True, exclude_none=True) + "\n").encode(
                encoding=self._server_params.encoding,
                errors=self._server_params.encoding_error_handler,
            )
        )

        response = await future
        print(f"← {response.model_dump_json(by_alias=True, exclude_none=True)}")
        return response

    async def send_notification(self, notification: JSONRPCNotification) -> None:
        assert self._process.stdin, "Opened process is missing stdin"

        print(f"→ {notification.model_dump_json(by_alias=True, exclude_none=True)}")
        await self._process.stdin.send(
            (
                notification.model_dump_json(by_alias=True, exclude_none=True) + "\n"
            ).encode(
                encoding=self._server_params.encoding,
                errors=self._server_params.encoding_error_handler,
            )
        )

    async def terminate(self, timeout: int = 30) -> None:
        self._assert_not_terminated()
        self._terminated = True
        await self._tg.__aexit__(None, None, None)
        await self._process.__aexit__(None, None, None)

    def _resolve_request(self, response: JSONRPCResponse | JSONRPCError) -> None:
        future = self._pending_requests.pop(response.id, None)
        assert future, "No pending request for response with id {response.id}"
        future.set_result(response)

    def _send_exception_somewhere(self, exception: Exception) -> None:
        # When this is called, it means that an exception occurred while trying
        # to parse a JSON-RPC response out of stdout. Because of the completely
        # async nature, we can't know which request this is related to. So,
        # we'll just marshal the exception as an error on ALL pending requests.
        #
        # TODO: I'm honestly unclear if we can recover from an error like this
        #
        for id, future in self._pending_requests.items():
            future.set_result(
                JSONRPCError(
                    jsonrpc="2.0",
                    id=id,
                    error=ErrorData(code=666, message=str(exception)),
                )
            )
        self._pending_requests.clear()

    async def _stdout_reader(self) -> None:
        assert self._process.stdout, "Opened process is missing stdout"

        try:
            buffer = ""
            async for chunk in TextReceiveStream(
                self._process.stdout,
                encoding=self._server_params.encoding,
                errors=self._server_params.encoding_error_handler,
            ):
                lines = (buffer + chunk).split("\n")
                buffer = lines.pop()

                for line in lines:
                    try:
                        message = JSONRPCMessage.model_validate_json(line)
                    except Exception as exc:
                        self._send_exception_somewhere(exc)
                        continue

                    assert isinstance(message.root, JSONRPCResponse | JSONRPCError), (
                        f"No unsolicited messages supported: {message}"
                    )
                    self._resolve_request(message.root)

        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    def _assert_not_terminated(self) -> None:
        assert not self._terminated, "process must not be terminated"
