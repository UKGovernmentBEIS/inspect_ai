import asyncio
import os
import sys
from asyncio.subprocess import Process
from typing import TextIO

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
                # TODO: I'm just passing my local env for testing. revert this before merging
                env=(
                    {**server_params.env, **os.environ}
                    if server_params.env
                    else os.environ
                ),
                cwd=server_params.cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=errlog,
            ),
            server_params,
        )

    def __init__(
        self,
        process: Process,
        server_params: StdioServerParameters,
    ) -> None:
        self._process = process
        self._server_params = server_params
        self._terminated = False
        self._pending_requests = dict[
            str | int, asyncio.Future[JSONRPCResponse | JSONRPCError]
        ]()
        self._reader_task: asyncio.Task[None] = asyncio.create_task(
            self._stdout_reader()
        )

    async def send_request(
        self, request: JSONRPCRequest
    ) -> JSONRPCResponse | JSONRPCError:
        assert self._process.stdin, "Opened process is missing stdin"
        self._assert_not_terminated()

        id = request.id
        assert id not in self._pending_requests, f"Request with id {id} already exists"
        future = asyncio.Future[JSONRPCResponse | JSONRPCError]()
        self._pending_requests[id] = future

        is_tool_call = request.method == "tools/call"

        if is_tool_call:
            print(f"→ {request.model_dump_json(by_alias=True, exclude_none=True)}")
        json_str = (
            request.model_dump_json(by_alias=True, exclude_none=True) + "\n"
        ).encode(
            encoding=self._server_params.encoding,
            errors=self._server_params.encoding_error_handler,
        )
        self._process.stdin.write(json_str)
        await self._process.stdin.drain()

        response = await future
        if is_tool_call:
            print(f"← {response.model_dump_json(by_alias=True, exclude_none=True)}")
        return response

    async def send_notification(self, notification: JSONRPCNotification) -> None:
        assert self._process.stdin, "Opened process is missing stdin"
        self._assert_not_terminated()

        print(f"→ {notification.model_dump_json(by_alias=True, exclude_none=True)}")
        json_str = (
            notification.model_dump_json(by_alias=True, exclude_none=True) + "\n"
        ).encode(
            encoding=self._server_params.encoding,
            errors=self._server_params.encoding_error_handler,
        )
        self._process.stdin.write(json_str)
        await self._process.stdin.drain()

    async def terminate(self, timeout: int = 30) -> None:
        self._assert_not_terminated()
        self._terminated = True

        self._reader_task.cancel()
        try:
            await asyncio.wait_for(self._reader_task, 1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            # Force kill if taking too long
            self._process.kill()

    def _resolve_request(self, response: JSONRPCResponse | JSONRPCError) -> None:
        future = self._pending_requests.pop(response.id, None)
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
        for request_id, future in self._pending_requests.items():
            future.set_result(
                JSONRPCError(
                    jsonrpc="2.0",
                    id=request_id,
                    error=ErrorData(code=666, message=str(exception)),
                )
            )
        self._pending_requests.clear()

    async def _stdout_reader(self) -> None:
        assert self._process.stdout, "Opened process is missing stdout"

        try:
            buffer = ""
            while True:
                line_bytes = await self._process.stdout.readline()
                if not line_bytes:  # EOF
                    break

                chunk = line_bytes.decode(
                    self._server_params.encoding,
                    errors=self._server_params.encoding_error_handler,
                )

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
            # These signal shutdown
            pass
        except Exception as exc:
            print(f"Exception while reading stdout: {exc}", file=sys.stderr)
            raise

    def _assert_not_terminated(self) -> None:
        assert not self._terminated, "process must not be terminated"
