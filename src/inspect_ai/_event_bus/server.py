from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Any, Callable, Coroutine

from pydantic import BaseModel

from .protocol import (
    CancelSampleCommand,
    ServerMessage,
    parse_client_message,
    to_json_line,
)
from .state import StateManager

logger = logging.getLogger(__name__)


class SocketServer:
    def __init__(
        self,
        state: StateManager,
        on_cancel_sample: Callable[[str | int], Coroutine[Any, Any, None]]
        | None = None,
        socket_path: str | None = None,
    ) -> None:
        self._state = state
        self._on_cancel_sample = on_cancel_sample
        self._clients: set[asyncio.StreamWriter] = set()
        self._server: asyncio.AbstractServer | None = None
        self._client_tasks: set[asyncio.Task[None]] = set()

        if socket_path is None:
            run_id = os.getpid()
            socket_path = os.path.join(tempfile.gettempdir(), f"inspect-{run_id}.sock")
        self._socket_path = socket_path

    @property
    def socket_path(self) -> str:
        return self._socket_path

    async def start(self) -> None:
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=self._socket_path
        )
        logger.info(f"Socket server listening on {self._socket_path}")
        print(f"Socket server listening on {self._socket_path}")

    async def stop(self) -> None:
        for writer in list(self._clients):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()

        for t in self._client_tasks:
            t.cancel()
        if self._client_tasks:
            await asyncio.gather(*self._client_tasks, return_exceptions=True)
        self._client_tasks.clear()

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)

    async def broadcast(self, msg: ServerMessage | BaseModel) -> None:
        if not self._clients:
            return
        data = to_json_line(msg)
        dead_clients: list[asyncio.StreamWriter] = []
        for writer in list(self._clients):
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                dead_clients.append(writer)
        for writer in dead_clients:
            self._clients.discard(writer)
            try:
                writer.close()
            except Exception:
                pass

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._clients.add(writer)
        logger.info(f"Client connected ({len(self._clients)} total)")

        try:
            snapshot = await self._state.snapshot()
            writer.write(to_json_line(snapshot))
            await writer.drain()

            task = asyncio.create_task(self._read_commands(reader, writer))
            self._client_tasks.add(task)
            task.add_done_callback(self._client_tasks.discard)
        except Exception:
            self._clients.discard(writer)
            try:
                writer.close()
            except Exception:
                pass

    async def _read_commands(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = parse_client_message(line)
                    if isinstance(msg, CancelSampleCommand) and self._on_cancel_sample:
                        await self._on_cancel_sample(msg.sample_id)
                except Exception as e:
                    logger.warning(f"Invalid client message: {e}")
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._clients.discard(writer)
            try:
                writer.close()
            except Exception:
                pass
            logger.info(f"Client disconnected ({len(self._clients)} total)")
