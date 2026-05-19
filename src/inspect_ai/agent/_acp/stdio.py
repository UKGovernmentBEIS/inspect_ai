"""Stdio↔socket bridge for ``inspect acp --stdio``.

The bridge is a transport adapter: it forwards newline-delimited
JSON-RPC frames between the editor's stdio streams and a running ACP
server's AF_UNIX or TCP socket. No client logic, no parsing on the
hot path beyond line framing.

The actual ``acp_server`` already speaks newline-delimited JSON-RPC
(confirmed by ``acp.connection.Connection``), so a line-by-line copy
is a correct 1:1 forwarder for any ACP traffic — initialize,
session/load, session/prompt, notifications, ``inspect/*``
extensions, future approval prompts, all of it.

Why line-framed and not raw bytes: ``readline()`` preserves message
boundaries; a chunk-based byte copy could split or merge frames if a
partial write landed at a chunk boundary. The per-line cost is
negligible at ACP traffic rates.

asyncio boundary note
=====================

This module is intentionally **asyncio-bound** (not anyio). The
bridge connects to the same socket the ACP server bound — via
``asyncio.open_unix_connection`` / ``asyncio.open_connection`` —
because the resulting ``asyncio.StreamReader`` / ``StreamWriter``
pair is what the line-forwarders work on. The two-way race
(``asyncio.create_task`` × 2 → ``asyncio.wait(FIRST_COMPLETED)`` →
cancel-loser) is a deliberate idiom for the symmetric stdin↔socket
forwarder topology; an anyio task-group equivalent would add scope
nesting around the asyncio stream APIs for no functional gain.

The bridge is a CLI-leaf — it doesn't compose with the rest of
inspect_ai's anyio code. Cancellation catches use
``anyio.get_cancelled_exc_class()`` so they're backend-agnostic
even though the surrounding code is asyncio.
"""

from __future__ import annotations

import asyncio
import contextlib
from logging import getLogger

import anyio

from inspect_ai.agent._acp._config import ACP_STREAM_BUFFER_LIMIT
from inspect_ai.agent._acp.discovery import TargetAddress

logger = getLogger(__name__)


async def _open_socket(
    target: TargetAddress,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open an asyncio connection for the resolved target.

    Switches on ``target`` shape: AF_UNIX via :func:`asyncio.open_unix_connection`,
    TCP via :func:`asyncio.open_connection`. The caller is responsible
    for translating ``ConnectionRefusedError`` / ``FileNotFoundError``
    into a user-friendly diagnostic.

    ``limit`` overrides asyncio's 64 KiB StreamReader buffer default;
    see :data:`ACP_STREAM_BUFFER_LIMIT` for why a single JSON-RPC line
    can easily exceed that on the Inspect transcript firehose.
    """
    if target.socket_path is not None:
        return await asyncio.open_unix_connection(
            str(target.socket_path), limit=ACP_STREAM_BUFFER_LIMIT
        )
    if target.host is not None and target.port is not None:
        return await asyncio.open_connection(
            target.host, target.port, limit=ACP_STREAM_BUFFER_LIMIT
        )
    raise ValueError(f"TargetAddress has no connectable address: {target!r}")


async def _forward_lines(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    label: str,
) -> None:
    """Copy newline-delimited frames from ``reader`` to ``writer`` until EOF.

    On exit (EOF or exception) closes ``writer`` so the partner
    forwarder's ``readline()`` observes an EOF too and exits cleanly.
    Without this, one side closing would leave the other forwarder
    blocked on its socket indefinitely.
    """
    try:
        while True:
            line = await reader.readline()
            if not line:
                logger.debug("acp bridge %s: EOF", label)
                return
            writer.write(line)
            await writer.drain()
    except (BrokenPipeError, ConnectionResetError) as exc:
        logger.debug(
            "acp bridge %s: %s — peer closed mid-write", label, type(exc).__name__
        )
    finally:
        # Closing our writer gives the other forwarder's reader an EOF.
        with contextlib.suppress(Exception):
            writer.close()


async def bridge_stdio(
    in_stream: asyncio.StreamReader,
    out_stream: asyncio.StreamWriter,
    target: TargetAddress,
) -> None:
    """Two-way line-framed forwarder between stdio streams and an ACP socket.

    Connects to ``target``, then runs two concurrent forwarders:
    one copies lines from ``in_stream`` (editor's stdin) to the
    socket; the other copies lines from the socket back to
    ``out_stream`` (editor's stdout).

    Exits as soon as **either** forwarder completes — the other is
    cancelled. We can't rely on the writer-close-cascade alone,
    because a forwarder blocked on ``reader.readline()`` from a
    still-open reader (e.g. stdin when the server side closed) won't
    observe the closure of its own ``writer`` and would block forever.

    Stream args are passed explicitly (not read from ``sys.stdin`` /
    ``sys.stdout``) so the bridge is directly unit-testable in-process.
    The CLI entrypoint uses :func:`acp.stdio.stdio_streams` to obtain
    cross-platform stdio streams for production.
    """
    sock_reader, sock_writer = await _open_socket(target)
    out_task = asyncio.create_task(
        _forward_lines(in_stream, sock_writer, "client→server"),
        name="acp-bridge-out",
    )
    in_task = asyncio.create_task(
        _forward_lines(sock_reader, out_stream, "server→client"),
        name="acp-bridge-in",
    )
    try:
        done, pending = await asyncio.wait(
            {out_task, in_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(anyio.get_cancelled_exc_class(), Exception):
                await task
        # Surface a real exception (not CancelledError) from whichever
        # forwarder finished first; tests rely on this to assert clean
        # exit vs error.
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, anyio.get_cancelled_exc_class()):
                raise exc
    finally:
        with contextlib.suppress(Exception):
            sock_writer.close()
            await sock_writer.wait_closed()
