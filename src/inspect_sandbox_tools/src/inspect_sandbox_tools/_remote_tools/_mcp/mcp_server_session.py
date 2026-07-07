import asyncio
import json
import os
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

# Maximum line length for reading MCP server stdout via asyncio.StreamReader.
#
# asyncio.StreamReader defaults to a 64KB line limit. A single JSON-RPC response
# line longer than the limit makes readline() raise ValueError ("Separator is not
# found, and chunk exceed the limit"), which previously killed the reader task and
# hung every pending request until the client timed out. MCP tool responses
# routinely exceed 64KB once wrapped in the JSON-RPC envelope (a base64 screenshot,
# a large file read, or verbose command output), so the 64KB default is too small
# to be safe as a floor.
#
# Default to a generous limit so realistic large responses just work; override with
# INSPECT_MCP_READLINE_LIMIT_BYTES. We size this comfortably above the host-side
# read_file cap (100 MiB) with headroom for the JSON-RPC envelope and base64
# expansion: a 100 MiB binary payload base64-encodes to ~133 MiB before the envelope
# is added, so a limit of exactly 100 MiB would still reject a cap-sized read.
# (This is a ceiling, not a reservation — memory grows only with the actual line
# length.) Even so, an over-limit line is now handled gracefully rather than hanging
# the session — see _stdout_reader.
_DEFAULT_READLINE_LIMIT = 256 * 1024 * 1024  # 256 MiB
_READLINE_LIMIT: int = (
    int(os.environ["INSPECT_MCP_READLINE_LIMIT_BYTES"])
    if "INSPECT_MCP_READLINE_LIMIT_BYTES" in os.environ
    else _DEFAULT_READLINE_LIMIT
)


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
                limit=_READLINE_LIMIT,
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

        # If the reader task has already exited (EOF on the server's stdout, or a
        # fatal read error such as an oversized line), no future will ever be
        # resolved. Fail fast with a clear error instead of hanging until the
        # client's timeout.
        if self._reader.done():
            reader_exc = None
            if not self._reader.cancelled():
                reader_exc = self._reader.exception()
            raise RuntimeError(
                "MCP server stdout reader is no longer running; the server "
                "connection is closed and cannot service requests."
            ) from reader_exc

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
            if future.done():
                continue
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
                try:
                    line_bytes = await self._process.stdout.readline()
                except ValueError as exc:
                    # asyncio.StreamReader.readline() raises ValueError (re-raised
                    # from an internal LimitOverrunError, which it does not surface
                    # directly) when a line exceeds the reader's `limit` with no
                    # newline yet; it clears its own buffer in the process. Treat it
                    # as a fatal, diagnosable read error: re-raise to the handler
                    # below, which fails every pending request rather than hanging
                    # them until timeout. With the default 256 MiB limit this should
                    # be unreachable for real responses; raise
                    # INSPECT_MCP_READLINE_LIMIT_BYTES if needed.
                    raise RuntimeError(
                        "MCP server response line exceeded the read limit of "
                        f"{_READLINE_LIMIT} bytes. Set INSPECT_MCP_READLINE_LIMIT_BYTES "
                        "higher if responses are legitimately larger than this."
                    ) from exc
                if not line_bytes:  # EOF
                    break

                chunk = self._decode(line_bytes)
                lines = (buffer + chunk).split("\n")
                buffer = lines.pop()

                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        message = JSONRPCMessage.model_validate_json(line)
                    except (pydantic.ValidationError, json.JSONDecodeError):
                        # Skip non-JSON lines (e.g. debug output, shell traces).
                        # This matches the MCP SDK's stdio_client behavior.
                        continue

                    # Drop unsolicited server->client messages (notifications and
                    # server-initiated requests). This session is a request/response
                    # proxy and does not forward them to the client. Crucially we must
                    # ignore them rather than crash the reader task: a server that
                    # emits e.g. `notifications/tools/list_changed` after initialize
                    # (legal for any server advertising listChanged) would otherwise
                    # kill this loop and hang every pending request until timeout.
                    if not isinstance(message.root, JSONRPCResponse | JSONRPCError):
                        continue
                    self._resolve_request(message.root)

        except asyncio.CancelledError:
            # The reader was cancelled (e.g. by terminate()). Resolve any
            # still-pending requests with an error so callers parked on
            # `await future` are told the session is going away instead of
            # hanging forever until their own timeout.
            self._send_exception_somewhere(
                RuntimeError("MCP server session terminated with requests pending.")
            )
        except Exception as exc:
            # The reader task is dying and cannot deliver any more responses.
            # Fail every pending request with this exception instead of leaving
            # them to hang until the client's timeout (which also poisons the
            # session for all subsequent requests). See _send_exception_somewhere.
            print(f"Exception processing stdout: {exc}", file=sys.stderr)
            self._send_exception_somewhere(exc)
        else:
            # Clean EOF: the server closed stdout without answering pending
            # requests. Don't leave them to hang — fail them with a clear error.
            if self._requests:
                self._send_exception_somewhere(
                    RuntimeError(
                        "MCP server closed its stdout (EOF) with requests pending."
                    )
                )

    def _assert_not_terminated(self) -> None:
        assert not self._terminated, "process must not be terminated"
