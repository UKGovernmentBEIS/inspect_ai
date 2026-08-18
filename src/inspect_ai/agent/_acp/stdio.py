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
import json
from logging import getLogger
from typing import Any

import anyio

from inspect_ai.agent._acp._config import ACP_STREAM_BUFFER_LIMIT
from inspect_ai.agent._acp.discovery import TargetAddress
from inspect_ai.agent._acp.inspect_ext import (
    INSPECT_ATTACH_METHOD,
    INSPECT_LIST_SESSIONS_METHOD,
)

logger = getLogger(__name__)


class TripleResolutionError(Exception):
    """Raised by :func:`preflight_resolve_triple` when the triple isn't live.

    Carries a human-readable message naming the requested triple and (when
    discovery succeeded) the available targets. The CLI surfaces the
    message verbatim on stderr.
    """


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


async def preflight_resolve_triple(target: TargetAddress, triple: str) -> None:
    """Confirm ``triple`` matches a live session on ``target`` before bridging.

    Opens a one-shot connection to the ACP server, calls
    ``inspect/list_sessions`` (which doesn't require ``initialize`` first;
    discovery is the prerequisite for binding), and checks that ``triple``
    appears in the response's ``target`` field. Raises
    :class:`TripleResolutionError` with an actionable message naming the
    requested triple and the available targets if not.

    Kept separate from :func:`bridge_stdio` so the CLI can surface a clean
    diagnostic (and exit 2) before any editor-facing stdio handshake starts.
    """
    reader, writer = await _open_socket(target)
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": INSPECT_LIST_SESSIONS_METHOD,
            "params": {},
        }
        writer.write((json.dumps(payload) + "\n").encode("utf-8"))
        await writer.drain()
        line = b""
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        except asyncio.TimeoutError as exc:
            raise TripleResolutionError(
                f"preflight: timed out waiting for inspect/list_sessions response "
                f"from {target.describe()}"
            ) from exc
        if not line:
            raise TripleResolutionError(
                f"preflight: ACP server at {target.describe()} closed the "
                "connection before responding to inspect/list_sessions"
            )
        msg: Any = None
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TripleResolutionError(
                f"preflight: malformed JSON-RPC response from {target.describe()}: "
                f"{exc}"
            ) from exc
        if "error" in msg:
            raise TripleResolutionError(
                f"preflight: inspect/list_sessions failed on {target.describe()}: "
                f"{msg['error']}"
            )
        sessions = msg.get("result", {}).get("sessions", [])
        available = [s.get("target", "") for s in sessions]
        if triple not in available:
            avail_str = ", ".join(available) if available else "(no live sessions)"
            raise TripleResolutionError(
                f"preflight: triple {triple!r} matches no live session on "
                f"{target.describe()}. Available: {avail_str}"
            )
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()


def _rewrite_session_new_to_attach(line: bytes, target_triple: str) -> bytes | None:
    """Rewrite a JSON-RPC ``session/new`` line to ``inspect/attach``.

    Returns the rewritten line bytes when ``line`` is a ``session/new``
    request; returns ``None`` so the caller forwards the original line
    untouched otherwise.

    The rewrite preserves the JSON-RPC ``id`` so the server's response
    (a standard ``NewSessionResponse``) flows back to the editor as the
    response to its ``session/new`` — the editor sees a normal direct-bind
    handshake. The original ``cwd`` is preserved if present; ``mcpServers``
    is dropped because the Inspect server doesn't host any.
    """
    try:
        msg = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(msg, dict):
        return None
    if msg.get("method") != "session/new" or "id" not in msg:
        return None
    original_params = msg.get("params")
    cwd = ""
    if isinstance(original_params, dict):
        maybe_cwd = original_params.get("cwd")
        if isinstance(maybe_cwd, str):
            cwd = maybe_cwd
    rewritten: dict[str, Any] = {
        "jsonrpc": msg.get("jsonrpc", "2.0"),
        "id": msg["id"],
        "method": INSPECT_ATTACH_METHOD,
        "params": {"cwd": cwd, "target": target_triple},
    }
    return (json.dumps(rewritten) + "\n").encode("utf-8")


async def _forward_lines_with_rewrite(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    label: str,
    target_triple: str,
) -> None:
    """Forwarder variant that rewrites the first ``session/new`` to ``inspect/attach``.

    After the rewrite (or after passing through any non-matching line),
    reverts to pure forwarding for the rest of the stream — the parse
    cost only applies until we've seen the editor's initial handshake.

    Only the FIRST matching ``session/new`` is rewritten — subsequent ones
    pass through unchanged. The expected case is one rewrite at the start
    of the editor's handshake; the bridge can't tell whether later
    ``session/new`` calls came from a user re-prompting for the picker or
    from some other flow, and silently rewriting them all would be surprising.
    """
    rewritten = False
    try:
        while True:
            line = await reader.readline()
            if not line:
                logger.debug("acp bridge %s: EOF", label)
                return
            out_line = line
            if not rewritten:
                replacement = _rewrite_session_new_to_attach(line, target_triple)
                if replacement is not None:
                    logger.debug(
                        "acp bridge %s: rewrote session/new → inspect/attach "
                        "for target %s",
                        label,
                        target_triple,
                    )
                    out_line = replacement
                    rewritten = True
            writer.write(out_line)
            await writer.drain()
    except (BrokenPipeError, ConnectionResetError) as exc:
        logger.debug(
            "acp bridge %s: %s — peer closed mid-write", label, type(exc).__name__
        )
    finally:
        with contextlib.suppress(Exception):
            writer.close()


async def bridge_stdio(
    in_stream: asyncio.StreamReader,
    out_stream: asyncio.StreamWriter,
    target: TargetAddress,
    *,
    rewrite_session_new_to_attach: str | None = None,
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

    When ``rewrite_session_new_to_attach`` is set, the editor→server
    forwarder rewrites the first ``session/new`` request it sees into an
    ``inspect/attach`` for the given ``task/sample_id/epoch`` triple. The
    response carries the canonical sessionId back to the editor verbatim;
    subsequent traffic is pure byte forwarding.
    """
    sock_reader, sock_writer = await _open_socket(target)
    if rewrite_session_new_to_attach is not None:
        out_task = asyncio.create_task(
            _forward_lines_with_rewrite(
                in_stream,
                sock_writer,
                "client→server",
                rewrite_session_new_to_attach,
            ),
            name="acp-bridge-out",
        )
    else:
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
