import asyncio
import sys
from asyncio.subprocess import Process
from typing import Literal, TextIO

import pydantic
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
        return cls(
            await asyncio.create_subprocess_exec(
                server_params.command,
                *server_params.args,
                env=server_params.env,
                cwd=server_params.cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=errlog,
            ),
            server_params.encoding,
            server_params.encoding_error_handler,
        )

    def __init__(
        self,
        process: Process,
        encoding: str,
        encoding_error_handler: Literal["strict", "ignore", "replace"],
    ) -> None:
        self._process = process
        self._encoding = encoding
        self._encoding_error_handler = encoding_error_handler
        self._terminated = False
        self._requests = dict[
            str | int, asyncio.Future[JSONRPCResponse | JSONRPCError]
        ]()
        self._reader = asyncio.create_task(self._stdout_reader())

    async def send_request(
        self, request: JSONRPCRequest
    ) -> JSONRPCResponse | JSONRPCError:
        assert self._process.stdin, "Opened process is missing stdin"
        self._assert_not_terminated()

        request_id = request.id
        assert request_id not in self._requests, (
            f"Request with id {request_id} already exists"
        )
        future = asyncio.Future[JSONRPCResponse | JSONRPCError]()
        self._requests[request_id] = future

        # print(f"→ {request.model_dump_json(by_alias=True, exclude_none=True)}")
        self._process.stdin.write(self._bytes_from_json_message(request))
        await self._process.stdin.drain()

        response = await future
        # print(f"← {response.model_dump_json(by_alias=True, exclude_none=True)}")
        return response

    async def send_notification(self, notification: JSONRPCNotification) -> None:
        assert self._process.stdin, "Opened process is missing stdin"
        self._assert_not_terminated()

        # print(f"→ {notification.model_dump_json(by_alias=True, exclude_none=True)}")
        self._process.stdin.write(self._bytes_from_json_message(notification))
        await self._process.stdin.drain()

    async def terminate(self, timeout: int = 30) -> None:
        self._assert_not_terminated()
        self._terminated = True

        self._reader.cancel()
        try:
            await asyncio.wait_for(self._reader, 1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            # Force kill if taking too long
            self._process.kill()

    def _bytes_from_json_message(
        self, message: JSONRPCRequest | JSONRPCNotification
    ) -> bytes:
        return self._encode(
            message.model_dump_json(by_alias=True, exclude_none=True) + "\n"
        )

    def _encode(self, message: str) -> bytes:
        return message.encode(
            encoding=self._encoding, errors=self._encoding_error_handler
        )

    def _decode(self, message: bytes) -> str:
        return message.decode(
            encoding=self._encoding, errors=self._encoding_error_handler
        )

    def _resolve_request(self, response: JSONRPCResponse | JSONRPCError) -> None:
        future = self._requests.pop(response.id, None)
        assert future, f"No pending request for response with id {response.id}"
        assert not future.done(), "Future should not be done before resolving"
        future.set_result(response)

    def _send_exception_somewhere(self, exception: Exception) -> None:
        # When this is called, it means that an exception occurred while trying
        # to parse a JSON-RPC response out of stdout. Because of the completely
        # async nature, we can't know which request this is related to. So,
        # we'll just marshal the exception as an error on ALL pending requests.
        #
        # TODO: I'm honestly unclear if we can recover from an error like this
        #
        for request_id, future in self._requests.items():
            future.set_result(
                JSONRPCError(
                    jsonrpc="2.0",
                    id=request_id,
                    error=ErrorData(code=666, message=str(exception)),
                )
            )
        self._requests.clear()

    async def _stdout_reader(self) -> None:
        assert self._process.stdout, "Opened process is missing stdout"

        try:
            buffer = ""
            while True:
                line_bytes = await self._process.stdout.readline()
                if not line_bytes:  # EOF
                    break

                chunk = self._decode(line_bytes)
                lines = (buffer + chunk).split("\n")
                buffer = lines.pop()

                for line in lines:
                    try:
                        message = JSONRPCMessage.model_validate_json(line)
                    except pydantic.ValidationError as exc:
                        self._send_exception_somewhere(exc)
                        continue

                    assert isinstance(message.root, JSONRPCResponse | JSONRPCError), (
                        f"No unsolicited messages supported: {message}"
                    )
                    self._resolve_request(message.root)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            # not much good can come of this
            print(f"Exception processing stdout: {exc}", file=sys.stderr)
            raise

    def _assert_not_terminated(self) -> None:
        assert not self._terminated, "process must not be terminated"
