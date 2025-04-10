import os
import signal
import sys
from dataclasses import dataclass, field
from typing import Dict, Literal, TextIO

import anyio
from anyio.abc import Process, TaskStatus
from anyio.streams.text import TextReceiveStream
from mcp import (
    ErrorData,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    StdioServerParameters,
)
from mcp.types import JSONRPCMessage, JSONRPCNotification
from pydantic import ValidationError

# TODO: I've taken steps down the path of getting rid of PendingRequest and just
# having _pending_requests be a dict of `QueueEntry`'s. I don't think it works
# because we need the code inside the task group to wait until the inner event
# has been set. I think, otherwise, exceptions that occur async won't necessarily
# go to the code that's waiting on the call to the public send_request.


@dataclass
class PendingRequest:
    """A container for a pending request with its associated event."""

    event: anyio.Event = field(default_factory=anyio.Event)
    response: JSONRPCResponse | JSONRPCError | None = None


@dataclass
class QueueEntry:
    request_or_notification: JSONRPCRequest | JSONRPCNotification | Literal["stop"]
    event: anyio.Event = field(default_factory=anyio.Event)
    response: JSONRPCResponse | JSONRPCError | None = None


class MCPServerSession:
    """
    A wrapper around an MCP server process.

    It does not support unsolicited messages from the server to the client.
    """

    @classmethod
    async def create(
        cls, server_params: StdioServerParameters, errlog: TextIO = sys.stderr
    ) -> "MCPServerSession":
        # TODO: I wonder if there's a way to add the process creation into the
        # async context manager as well. Hmmmmm...
        process = await anyio.open_process(
            [server_params.command, *server_params.args],
            # TODO: I'm just passing my local env for testing. revert this before merging
            env={**server_params.env, **os.environ}
            if server_params.env
            else os.environ,
            stderr=errlog,
            cwd=server_params.cwd,
        )

        session = cls(process, server_params)
        await session._start()
        return session

    def __init__(self, process: Process, server_params: StdioServerParameters) -> None:
        self._process = process
        self._server_params = server_params
        self._terminated = False
        self._pending_requests: Dict[str | int, PendingRequest] = {}
        self._task_queue = anyio.create_memory_object_stream[QueueEntry]()
        self._task_group = anyio.create_task_group()  # created but not yet entered
        self._shutdown_complete = anyio.Event()

    async def send_request(
        self, request: JSONRPCRequest
    ) -> JSONRPCResponse | JSONRPCError:
        entry = QueueEntry(request_or_notification=request)
        await self._task_queue[0].send(entry)
        await entry.event.wait()
        assert entry.response is not None
        return entry.response

    async def send_notification(self, notification: JSONRPCNotification) -> None:
        entry = QueueEntry(request_or_notification=notification)
        await self._task_queue[0].send(entry)
        await entry.event.wait()
        assert entry.response is None

    async def terminate(self, timeout: int = 30) -> None:
        """
        Gracefully terminate the session.

        Cancels running tasks and waits for clean shutdown up to the timeout.
        If the timeout expires, attempts forceful termination of the process.

        Args:
            timeout: Maximum seconds to wait for graceful shutdown.
        """
        self._assert_not_terminated()
        self._terminated = True

        # Resolve all pending requests with termination error
        self._fail_pending_requests(-32803, "Server session is being terminated")

        kill_message = QueueEntry("stop")
        await self._task_queue[0].send(kill_message)

        # # Cancel the task group to stop the session and its readers
        # self._task_group.cancel_scope.cancel()

        # # Protect against exceptions during task group exit
        # try:
        #     await self._task_group.__aexit__(None, None, None)
        # except Exception as exc:
        #     # Log the exception but continue with cleanup
        #     print(f"Error during task group exit: {exc}", file=sys.stderr)

        # Wait for the task group to fully shut down with timeout
        graceful_shutdown = False
        with anyio.move_on_after(timeout):
            await self._shutdown_complete.wait()
            graceful_shutdown = True

        # Force terminate if graceful shutdown timed out and process is still running
        if not graceful_shutdown and self._process.returncode is None:
            try:
                # Send SIGTERM first for cleaner termination
                os.kill(self._process.pid, signal.SIGTERM)

                # Give it a moment to terminate
                with anyio.move_on_after(1):
                    await self._process.wait()

                # If still running, force kill
                if self._process.returncode is None:
                    os.kill(self._process.pid, signal.SIGKILL)
            except OSError:
                # Process might have terminated between checks
                pass

        # The process cleanup is handled by the context manager in _start()

    async def _send_request(
        self, request: JSONRPCRequest
    ) -> JSONRPCResponse | JSONRPCError:
        assert self._process.stdin, "Opened process is missing stdin"
        self._assert_not_terminated()

        id = request.id
        assert id not in self._pending_requests, f"Request with id {id} already exists"
        pending = PendingRequest()
        self._pending_requests[id] = pending

        # Send the request to the process
        await self._process.stdin.send(
            (request.model_dump_json(by_alias=True, exclude_none=True) + "\n").encode(
                encoding=self._server_params.encoding,
                errors=self._server_params.encoding_error_handler,
            )
        )

        # Wait for response
        await pending.event.wait()
        assert pending.response is not None, (
            "Response should not be None after event is set"
        )
        return pending.response

    async def _send_notification(self, notification: JSONRPCNotification) -> None:
        assert self._process.stdin, "Opened process is missing stdin"
        self._assert_not_terminated()

        await self._process.stdin.send(
            (
                notification.model_dump_json(by_alias=True, exclude_none=True) + "\n"
            ).encode(
                encoding=self._server_params.encoding,
                errors=self._server_params.encoding_error_handler,
            )
        )

    async def _start(self) -> None:
        await self._task_group.__aenter__()
        await self._task_group.start(self._run_background_service)

    async def _run_background_service(
        self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED
    ) -> None:
        try:
            async with self._process:
                # Create a nested task group for the readers
                async with anyio.create_task_group() as reader_tg:
                    reader_tg.start_soon(self._task_queue_reader)
                    reader_tg.start_soon(self._stdout_reader)
                    task_status.started()
        except anyio.get_cancelled_exc_class():
            # Expected during termination
            pass
        except Exception as exc:
            self._fail_pending_requests(
                -32803, f"Server session terminated: Unexpected error: {str(exc)}"
            )
            raise
        finally:
            self._fail_pending_requests(
                -32803, "Server session terminated: Session terminated unexpectedly"
            )
            self._shutdown_complete.set()

    async def _task_queue_reader(self) -> None:
        try:
            while True:
                entry = await self._task_queue[1].receive()
                if entry.request_or_notification == "stop":
                    self._task_group.cancel_scope.cancel()
                    # await self._task_group.__aexit__(None, None, None)
                    continue
                print(
                    f"→ {entry.request_or_notification.model_dump_json(by_alias=True, exclude_none=True)}"
                )
                match entry.request_or_notification:
                    case JSONRPCRequest():
                        entry.response = await self._send_request(
                            entry.request_or_notification
                        )
                        print(
                            f"← {entry.response.model_dump_json(by_alias=True, exclude_none=True)}"
                        )
                        entry.event.set()
                    case JSONRPCNotification():
                        await self._send_notification(entry.request_or_notification)
                        entry.event.set()
        # TODO: Seems slightly odd that I need to catch and ignore this myself
        # It seems like a footgun, but I guess there's no way around that. confirm.
        except anyio.get_cancelled_exc_class() as exc:
            print(exc)
            pass
        except Exception as wtf:
            print(wtf)
            raise
        finally:
            print("Task queue reader finished")

    def _resolve_request(self, response: JSONRPCResponse | JSONRPCError) -> None:
        pending = self._pending_requests.pop(response.id, None)
        assert pending, f"No pending request for response with id {response.id}"

        # Set the response and trigger the event
        pending.response = response
        pending.event.set()

    def _fail_pending_requests(self, code: int, message: str) -> None:
        """
        Fail all pending requests with a JSON-RPC error.

        Args:
            code: The JSON-RPC error code
            message: The error message
        """
        events_to_set = []

        # Set error responses for all pending requests
        for id, pending in self._pending_requests.items():
            error_response = JSONRPCError(
                jsonrpc="2.0",
                id=id,
                error=ErrorData(code=code, message=message),
            )
            pending.response = error_response
            events_to_set.append(pending.event)

        # Clear all pending requests
        self._pending_requests.clear()

        # Now that we've cleared the dictionary, set all events
        for event in events_to_set:
            event.set()

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
                    except ValidationError as exc:
                        self._fail_pending_requests(-32700, f"Parse error: {str(exc)}")
                        continue

                    if not isinstance(message.root, JSONRPCResponse | JSONRPCError):
                        print(
                            f"Support for unsolicited message from server is NYI. Ignoring: {message}",
                            file=sys.stderr,
                        )
                        continue

                    self._resolve_request(message.root)

        except (anyio.ClosedResourceError, anyio.get_cancelled_exc_class()):
            pass
        except Exception as wtf:
            print(wtf)
            raise

    def _assert_not_terminated(self) -> None:
        assert not self._terminated, "process must not be terminated"
