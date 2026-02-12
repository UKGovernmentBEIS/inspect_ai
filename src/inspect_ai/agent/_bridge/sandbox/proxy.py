#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from email.utils import formatdate
from http import HTTPStatus
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterator,
    Optional,
    TypeAlias,
)
from urllib.parse import parse_qs, unquote, urlparse

# ---------- Types ----------
RequestHandler: TypeAlias = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
RouteMap: TypeAlias = dict[str, RequestHandler]
MethodRoutes: TypeAlias = dict[str, RouteMap]

# ---------- Limits / Defaults ----------
MAX_HEADER_BYTES = 64 * 1024
MAX_BODY_BYTES = 50 * 1024 * 1024
READ_TIMEOUT_S = 60
WRITE_TIMEOUT_S = 60
STREAM_CHUNK = 8192

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


class AsyncHTTPServer:
    """Async HTTP server supporting GET/POST/OPTIONS with streaming + proxy utilities."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        self.host = host
        self.port = port
        self.routes: MethodRoutes = {"GET": {}, "POST": {}, "OPTIONS": {}}
        self.server: asyncio.Server | None = None
        self.enable_cors: bool = True
        self.server_name: str = "asyncio-proxy"

    # -------- Routing --------
    def route(
        self, path: str, method: str = "GET"
    ) -> Callable[[RequestHandler], RequestHandler]:
        """Decorator to register a route (supports wildcard via trailing '*')."""

        def decorator(handler: RequestHandler) -> RequestHandler:
            if method not in self.routes:
                raise ValueError(f"Unsupported method: {method}")
            self.routes[method][path] = handler
            return handler

        return decorator

    def add_route(
        self, path: str, handler: RequestHandler, method: str = "GET"
    ) -> None:
        if method not in self.routes:
            raise ValueError(f"Unsupported method: {method}")
        self.routes[method][path] = handler

    def _find_handler(self, method: str, path: str) -> Optional[RequestHandler]:
        """Find handler by exact match or wildcard (prefix with '*'). Longest prefix wins."""
        routes = self.routes.get(method, {})
        if path in routes:
            return routes[path]
        best: tuple[int, Optional[RequestHandler]] = (-1, None)
        for route, handler in routes.items():
            if route.endswith("*"):
                prefix = route[:-1]
                if path.startswith(prefix) and len(prefix) > best[0]:
                    best = (len(prefix), handler)
        return best[1]

    # -------- Parsing --------
    async def _read_headers(self, reader: asyncio.StreamReader) -> list[str]:
        """Read raw header lines until CRLFCRLF with limits."""
        buf = bytearray()
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=READ_TIMEOUT_S)
            if not line:
                break
            buf += line
            if len(buf) > MAX_HEADER_BYTES:
                raise ValueError("Header section too large")
            if buf.endswith(b"\r\n\r\n") or buf.endswith(b"\n\n"):
                break
        return buf.decode("iso-8859-1").splitlines()

    async def _read_chunked(self, reader: asyncio.StreamReader) -> bytes:
        """Read and de-chunk a chunked-encoded body into raw bytes."""
        chunks = bytearray()
        while True:
            size_line = (
                await asyncio.wait_for(reader.readline(), timeout=READ_TIMEOUT_S)
            ).strip()
            if not size_line:
                raise ValueError("Malformed chunked encoding")
            # allow chunk extensions: "<hex>;<ext>"
            hex_size = size_line.split(b";", 1)[0]
            try:
                size = int(hex_size, 16)
            except ValueError:
                raise ValueError("Invalid chunk size")
            if size == 0:
                # consume trailing headers until empty line
                while True:
                    trailer = await asyncio.wait_for(
                        reader.readline(), timeout=READ_TIMEOUT_S
                    )
                    if trailer in (b"\r\n", b"\n", b""):
                        break
                break
            chunk = await asyncio.wait_for(
                reader.readexactly(size), timeout=READ_TIMEOUT_S
            )
            chunks += chunk
            # consume CRLF after each chunk
            crlf = await asyncio.wait_for(reader.readline(), timeout=READ_TIMEOUT_S)
            if crlf not in (b"\r\n", b"\n"):
                raise ValueError("Malformed chunk terminator")
            if len(chunks) > MAX_BODY_BYTES:
                raise ValueError("Body too large")
        return bytes(chunks)

    async def _parse_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> tuple[str, str, str, dict[str, str], bytes]:
        """Parse an HTTP/1.1 request. Returns (method, full_path, http_version, headers, body)."""
        # Request line
        request_line = await asyncio.wait_for(reader.readline(), timeout=READ_TIMEOUT_S)
        if not request_line:
            raise ValueError("Empty request")

        parts = request_line.decode("ascii", "strict").strip().split()
        if len(parts) != 3:
            raise ValueError("Invalid request line")
        method, full_path, http_version = parts

        # Headers
        headers: dict[str, str] = {}
        raw_header_lines = await self._read_headers(reader)
        for header in raw_header_lines:
            if not header or header in ("\r",):
                continue
            if ":" in header:
                key, value = header.split(":", 1)
                headers[key.strip().lower()] = value.strip()

        # Expect: 100-continue
        expect = headers.get("expect")
        if expect and expect.lower() == "100-continue":
            try:
                writer.write(b"HTTP/1.1 100 Continue\r\n\r\n")
                await asyncio.wait_for(writer.drain(), timeout=WRITE_TIMEOUT_S)
            except Exception:
                pass

        # Body
        body: bytes = b""
        te = headers.get("transfer-encoding", "").lower()
        if "chunked" in te:
            body = await self._read_chunked(reader)
        elif "content-length" in headers:
            content_length = int(headers["content-length"])
            if content_length > MAX_BODY_BYTES:
                raise ValueError("Body too large")
            if content_length > 0:
                body = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=READ_TIMEOUT_S
                )
        else:
            body = b""

        return method, full_path, http_version, headers, body

    # -------- Response building / streaming --------
    def _cors_headers(self) -> dict[str, str]:
        if not self.enable_cors:
            return {}
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, OpenAI-Organization, OpenAI-Beta",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Max-Age": "600",
        }

    def _build_headers_block(
        self, status: int, headers: dict[str, str], reason: Optional[str] = None
    ) -> bytes:
        phrase = reason or HTTPStatus(status).phrase
        status_line = f"HTTP/1.1 {status} {phrase}\r\n"
        base = {
            "Date": _http_date(),
            "Server": self.server_name,
        }
        out = {**base, **headers}
        out.update(self._cors_headers())
        lines = [status_line]
        for k, v in out.items():
            if v is None:
                continue
            if "\r" in str(v) or "\n" in str(v):
                raise ValueError("Invalid header value")
            lines.append(f"{k}: {v}\r\n")
        lines.append("\r\n")
        return "".join(lines).encode("ascii")

    def _build_response(
        self,
        status: int,
        body: str | bytes | dict[str, Any] | None = None,
        content_type: str = "application/json; charset=utf-8",
        extra_headers: Optional[dict[str, str]] = None,
        reason: Optional[str] = None,
    ) -> bytes:
        if body is None:
            body_bytes = b""
        elif isinstance(body, dict):
            body_bytes = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body_bytes = body.encode("utf-8")
        else:
            body_bytes = body

        hdrs = {
            "Content-Type": content_type,
            "Content-Length": str(len(body_bytes)),
            "Connection": "close",
        }
        if extra_headers:
            hdrs.update(extra_headers)

        return self._build_headers_block(status, hdrs, reason=reason) + body_bytes

    async def _send_streaming_response(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        headers: Optional[dict[str, str]],
        body_iter: AsyncIterator[bytes],
        chunked: bool = True,
        reason: Optional[str] = None,
    ) -> None:
        """Send an internally-generated streaming response (e.g., SSE)."""
        hdrs = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
        if headers:
            hdrs.update(headers)
        hdrs.setdefault("Content-Type", "text/event-stream; charset=utf-8")
        if chunked:
            hdrs["Transfer-Encoding"] = "chunked"

        writer.write(self._build_headers_block(status, hdrs, reason=reason))
        await asyncio.wait_for(writer.drain(), timeout=WRITE_TIMEOUT_S)

        async for chunk in body_iter:
            if not chunk:
                continue
            if chunked:
                size = f"{len(chunk):X}\r\n".encode("ascii")
                writer.write(size + chunk + b"\r\n")
            else:
                writer.write(chunk)
            await asyncio.wait_for(writer.drain(), timeout=WRITE_TIMEOUT_S)

        if chunked:
            writer.write(b"0\r\n\r\n")
            await asyncio.wait_for(writer.drain(), timeout=WRITE_TIMEOUT_S)

    async def _relay_upstream_response(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        reason: str,
        headers_list: list[tuple[str, str]],
        upstream_reader: asyncio.StreamReader,
        content_length: Optional[int],
    ) -> None:
        """Write upstream status/headers, then pass upstream body bytes through.

        Handles both Content-Length and Transfer-Encoding: chunked without
        re-chunking or decoding.
        """
        # Lowercase map for checks
        headers_lower = {k.lower(): v for k, v in headers_list}
        is_chunked = "chunked" in headers_lower.get("transfer-encoding", "").lower()

        # Compose headers (preserve original case), then add CORS
        cors = self._cors_headers()
        status_line = f"HTTP/1.1 {status} {reason or HTTPStatus(status).phrase}\r\n"
        writer.write(status_line.encode("ascii"))
        for k, v in headers_list:
            writer.write(f"{k}: {v}\r\n".encode("latin-1", "strict"))
        for ck, cv in cors.items():
            writer.write(f"{ck}: {cv}\r\n".encode("ascii"))
        writer.write(b"\r\n")
        await asyncio.wait_for(writer.drain(), timeout=WRITE_TIMEOUT_S)

        # Body relay
        if is_chunked:
            # Relay chunked framing verbatim until final 0-size chunk + trailers
            while True:
                size_line = await upstream_reader.readline()
                if not size_line:
                    break  # upstream closed unexpectedly
                writer.write(size_line)
                # parse size to know when to finish
                try:
                    hex_size = size_line.strip().split(b";", 1)[0]
                    size = int(hex_size, 16)
                except Exception:
                    size = None
                if size == 0:
                    # forward any trailing headers then final CRLF
                    while True:
                        trailer = await upstream_reader.readline()
                        writer.write(trailer)
                        if trailer in (b"\r\n", b"\n", b""):
                            break
                    await writer.drain()
                    break
                if size is not None and size >= 0:
                    data = await upstream_reader.readexactly(size)
                    writer.write(data)
                    crlf = await upstream_reader.readline()
                    writer.write(crlf)
                else:
                    # If size couldn't be parsed, best-effort passthrough a single chunk
                    data = await upstream_reader.read(STREAM_CHUNK)
                    if not data:
                        break
                    writer.write(data)
                await writer.drain()
        else:
            if content_length is not None:
                remaining = content_length
                while remaining > 0:
                    n = min(STREAM_CHUNK, remaining)
                    chunk = await upstream_reader.readexactly(n)
                    writer.write(chunk)
                    await writer.drain()
                    remaining -= len(chunk)
            else:
                # read until EOF
                while True:
                    chunk = await upstream_reader.read(STREAM_CHUNK)
                    if not chunk:
                        break
                    writer.write(chunk)
                    await writer.drain()

    # -------- Connection handler --------
    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        t0 = time.monotonic()
        try:
            method, full_path, http_version, headers, body = await self._parse_request(
                reader, writer
            )
            parsed = urlparse(full_path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)

            # OPTIONS preflight
            if method == "OPTIONS":
                response_bytes = self._build_response(204, b"", "text/plain", {})
                writer.write(response_bytes)
                await writer.drain()
                return

            # Find handler
            handler = self._find_handler(method, path)
            if handler:
                # Build request context for handler
                request_data: dict[str, Any] = {
                    "method": method,
                    "path": path,  # decoded path
                    "full_path": full_path,  # includes query
                    "query": query,  # dict[str, list[str]]
                    "http_version": http_version,
                    "headers": headers,  # lowercase keys
                    "raw_body": body,
                    "json": None,
                    "text": None,
                }

                ctype = headers.get("content-type", "")
                if body:
                    if ctype.startswith("application/json"):
                        try:
                            request_data["json"] = json.loads(body.decode("utf-8"))
                        except Exception:
                            request_data["text"] = body.decode(
                                "utf-8", errors="replace"
                            )
                    elif ctype.startswith("text/"):
                        request_data["text"] = body.decode("utf-8", errors="replace")

                # Call handler
                response = await handler(request_data)

                # Relay upstream?
                if "_relay" in response:
                    rinfo = response["_relay"]
                    await self._relay_upstream_response(
                        writer=writer,
                        status=int(rinfo.get("status", 200)),
                        reason=rinfo.get("reason", ""),
                        headers_list=rinfo.get("headers_list", []),
                        upstream_reader=rinfo["reader"],
                        content_length=rinfo.get("content_length"),
                    )
                # Streaming from local generator?
                elif "body_iter" in response:
                    await self._send_streaming_response(
                        writer=writer,
                        status=response.get("status", 200),
                        headers=response.get("headers", {}),
                        body_iter=response["body_iter"],
                        chunked=response.get("chunked", True),
                        reason=response.get("reason"),
                    )
                else:
                    # Normal response
                    status = response.get("status", 200)
                    body_data = response.get("body")
                    content_type = response.get(
                        "content_type", "application/json; charset=utf-8"
                    )
                    headers_extra = response.get("headers", {})
                    resp_bytes = self._build_response(
                        status,
                        body_data,
                        content_type,
                        headers_extra,
                        reason=response.get("reason"),
                    )
                    writer.write(resp_bytes)
            else:
                # 404
                error_response = {
                    "error": {
                        "message": f"Path {path} not found",
                        "type": "not_found",
                        "code": 404,
                    }
                }
                writer.write(self._build_response(404, error_response))

            await writer.drain()
        except Exception as e:
            try:
                err = {
                    "error": {"message": str(e), "type": "internal_error", "code": 500}
                }
                writer.write(self._build_response(500, err))
                await writer.drain()
            except Exception:
                pass
        finally:
            dur_ms = int((time.monotonic() - t0) * 1000)
            try:
                peer = writer.get_extra_info("peername")
                print(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {peer} handled in {dur_ms} ms"
                )
            except Exception:
                pass
            writer.close()
            await writer.wait_closed()

    # -------- Lifecycle --------
    async def start(self) -> None:
        self.server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        print(f"Server running on http://{self.host}:{self.port}")
        async with self.server:
            await self.server.serve_forever()

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None


def _http_date() -> str:
    return formatdate(timeval=None, usegmt=True)


async def model_proxy_server(
    port: int, call_bridge_model_service_async: Any = None
) -> AsyncHTTPServer:
    """Create and configure the model proxy server.

    Args:
        port: Port to run the server on
        instance: Instance of service
        call_bridge_model_service_async: Optional bridge service function for testing

    Returns:
        Configured AsyncHTTPServer instance
    """
    # get generate method if not provided (for testing)
    call_bridge_model_service_async = (
        call_bridge_model_service_async or _call_bridge_model_service_async
    )

    # setup server
    server = AsyncHTTPServer(port=port)

    def _sse_bytes(payload: dict[str, Any]) -> bytes:
        # data-only SSE, as used by OpenAI's Chat Completions stream
        # https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

    def _iter_chunks(text: str, max_len: int = 48) -> Iterator[str]:
        # Simple fixed-width chunking; adjust max_len to change granularity
        for i in range(0, len(text), max_len):
            yield text[i : i + max_len]

    @server.route("/v1/responses", method="POST")
    async def responses(request: dict[str, Any]) -> dict[str, Any]:
        try:
            json_body = request.get("json", {}) or {}
            stream = json_body.get("stream", False)

            completion = await call_bridge_model_service_async(
                "generate_responses", json_data=json_body
            )

            if stream:

                async def stream_response() -> AsyncIterator[bytes]:
                    # Parse the completion as a dict
                    resp = (
                        completion
                        if isinstance(completion, dict)
                        else json.loads(completion)
                    )

                    # Helper to create SSE event
                    def _sse_event(
                        event_type: str, data: dict[str, Any], seq_num: int
                    ) -> bytes:
                        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode(
                            "utf-8"
                        )

                    seq_num = 0

                    # 1. response.created event
                    seq_num += 1
                    yield _sse_event(
                        "response.created",
                        {
                            "response": resp,
                            "sequence_number": seq_num,
                            "type": "response.created",
                        },
                        seq_num,
                    )

                    # 2. response.in_progress event
                    seq_num += 1
                    in_progress_resp = dict(resp)
                    in_progress_resp["status"] = "in_progress"
                    yield _sse_event(
                        "response.in_progress",
                        {
                            "response": in_progress_resp,
                            "sequence_number": seq_num,
                            "type": "response.in_progress",
                        },
                        seq_num,
                    )

                    # 3. Process each output item
                    for output_index, output_item in enumerate(resp.get("output", [])):
                        # Use dict directly - output_item is a dict
                        item_id = output_item.get("id", f"item_{output_index}")
                        item_type = output_item.get("type")

                        # 3a. response.output_item.added
                        seq_num += 1
                        # Set initial status to in_progress for streaming
                        item_dict = dict(output_item)
                        if "status" in item_dict:
                            item_dict["status"] = "in_progress"

                        yield _sse_event(
                            "response.output_item.added",
                            {
                                "item": item_dict,
                                "output_index": output_index,
                                "sequence_number": seq_num,
                                "type": "response.output_item.added",
                            },
                            seq_num,
                        )

                        # Process based on item type
                        if item_type == "message":
                            # Process message content - content is a list of dicts
                            for content_index, content in enumerate(
                                output_item.get("content", [])
                            ):
                                content_type = content.get("type")

                                # 3b. response.content_part.added
                                seq_num += 1
                                content_dict = dict(content)
                                if content_type == "output_text":
                                    # Clear text for streaming
                                    content_dict["text"] = ""
                                elif content_type == "refusal":
                                    content_dict["refusal"] = ""

                                yield _sse_event(
                                    "response.content_part.added",
                                    {
                                        "item_id": item_id,
                                        "output_index": output_index,
                                        "content_index": content_index,
                                        "part": content_dict,
                                        "sequence_number": seq_num,
                                        "type": "response.content_part.added",
                                    },
                                    seq_num,
                                )

                                # Stream content
                                if content_type == "output_text":
                                    text = content.get("text", "")
                                    # Stream text in chunks
                                    for chunk in _iter_chunks(text):
                                        seq_num += 1
                                        yield _sse_event(
                                            "response.output_text.delta",
                                            {
                                                "item_id": item_id,
                                                "output_index": output_index,
                                                "content_index": content_index,
                                                "delta": chunk,
                                                "logprobs": [],  # Empty for simulated streaming
                                                "sequence_number": seq_num,
                                                "type": "response.output_text.delta",
                                            },
                                            seq_num,
                                        )

                                    # Text done event
                                    seq_num += 1
                                    yield _sse_event(
                                        "response.output_text.done",
                                        {
                                            "item_id": item_id,
                                            "output_index": output_index,
                                            "content_index": content_index,
                                            "text": text,
                                            "logprobs": [],
                                            "sequence_number": seq_num,
                                            "type": "response.output_text.done",
                                        },
                                        seq_num,
                                    )

                                elif content_type == "refusal":
                                    refusal_text = content.get("refusal", "")
                                    # Stream refusal in chunks
                                    for chunk in _iter_chunks(refusal_text):
                                        seq_num += 1
                                        yield _sse_event(
                                            "response.refusal.delta",
                                            {
                                                "item_id": item_id,
                                                "output_index": output_index,
                                                "content_index": content_index,
                                                "delta": chunk,
                                                "sequence_number": seq_num,
                                                "type": "response.refusal.delta",
                                            },
                                            seq_num,
                                        )

                                    # Refusal done event
                                    seq_num += 1
                                    yield _sse_event(
                                        "response.refusal.done",
                                        {
                                            "item_id": item_id,
                                            "output_index": output_index,
                                            "content_index": content_index,
                                            "refusal": refusal_text,
                                            "sequence_number": seq_num,
                                            "type": "response.refusal.done",
                                        },
                                        seq_num,
                                    )

                                # 3c. response.content_part.done
                                seq_num += 1
                                yield _sse_event(
                                    "response.content_part.done",
                                    {
                                        "item_id": item_id,
                                        "output_index": output_index,
                                        "content_index": content_index,
                                        "part": content,
                                        "sequence_number": seq_num,
                                        "type": "response.content_part.done",
                                    },
                                    seq_num,
                                )

                        elif item_type == "function_call":
                            # Handle function call streaming
                            arguments = output_item.get("arguments", "")

                            # Stream function arguments
                            for chunk in _iter_chunks(arguments, max_len=32):
                                seq_num += 1
                                yield _sse_event(
                                    "response.function_call_arguments.delta",
                                    {
                                        "item_id": item_id,
                                        "output_index": output_index,
                                        "delta": chunk,
                                        "sequence_number": seq_num,
                                        "type": "response.function_call_arguments.delta",
                                    },
                                    seq_num,
                                )

                            # Function arguments done
                            seq_num += 1
                            yield _sse_event(
                                "response.function_call_arguments.done",
                                {
                                    "item_id": item_id,
                                    "output_index": output_index,
                                    "arguments": arguments,
                                    "sequence_number": seq_num,
                                    "type": "response.function_call_arguments.done",
                                },
                                seq_num,
                            )

                        elif item_type == "computer_call":
                            # Computer calls complete immediately (no streaming)
                            pass

                        elif item_type == "reasoning":
                            # Handle reasoning item streaming
                            if output_item.get("content"):
                                for reasoning_idx, reasoning_content in enumerate(
                                    output_item.get("content", [])
                                ):
                                    if (
                                        reasoning_content.get("type")
                                        == "reasoning_text"
                                    ):
                                        text = reasoning_content.get("text", "")
                                        # Stream reasoning text
                                        for chunk in _iter_chunks(text):
                                            seq_num += 1
                                            yield _sse_event(
                                                "response.reasoning_text.delta",
                                                {
                                                    "item_id": item_id,
                                                    "output_index": output_index,
                                                    "content_index": reasoning_idx,
                                                    "delta": chunk,
                                                    "sequence_number": seq_num,
                                                    "type": "response.reasoning_text.delta",
                                                },
                                                seq_num,
                                            )

                                        # Reasoning text done
                                        seq_num += 1
                                        yield _sse_event(
                                            "response.reasoning_text.done",
                                            {
                                                "item_id": item_id,
                                                "output_index": output_index,
                                                "content_index": reasoning_idx,
                                                "text": text,
                                                "sequence_number": seq_num,
                                                "type": "response.reasoning_text.done",
                                            },
                                            seq_num,
                                        )

                            # Handle reasoning summary if present
                            if output_item.get("summary"):
                                for summary_index, summary_part in enumerate(
                                    output_item.get("summary", [])
                                ):
                                    # Add summary part
                                    seq_num += 1
                                    yield _sse_event(
                                        "response.reasoning_summary_part.added",
                                        {
                                            "item_id": item_id,
                                            "output_index": output_index,
                                            "summary_index": summary_index,
                                            "part": summary_part,
                                            "sequence_number": seq_num,
                                            "type": "response.reasoning_summary_part.added",
                                        },
                                        seq_num,
                                    )

                                    if summary_part.get("type") == "summary_text":
                                        text = summary_part.get("text", "")
                                        # Stream summary text
                                        for chunk in _iter_chunks(text):
                                            seq_num += 1
                                            yield _sse_event(
                                                "response.reasoning_summary_text.delta",
                                                {
                                                    "item_id": item_id,
                                                    "output_index": output_index,
                                                    "summary_index": summary_index,
                                                    "delta": chunk,
                                                    "sequence_number": seq_num,
                                                    "type": "response.reasoning_summary_text.delta",
                                                },
                                                seq_num,
                                            )

                                        # Summary text done
                                        seq_num += 1
                                        yield _sse_event(
                                            "response.reasoning_summary_text.done",
                                            {
                                                "item_id": item_id,
                                                "output_index": output_index,
                                                "summary_index": summary_index,
                                                "text": text,
                                                "sequence_number": seq_num,
                                                "type": "response.reasoning_summary_text.done",
                                            },
                                            seq_num,
                                        )

                                    # Summary part done
                                    seq_num += 1
                                    yield _sse_event(
                                        "response.reasoning_summary_part.done",
                                        {
                                            "item_id": item_id,
                                            "output_index": output_index,
                                            "summary_index": summary_index,
                                            "part": summary_part,
                                            "sequence_number": seq_num,
                                            "type": "response.reasoning_summary_part.done",
                                        },
                                        seq_num,
                                    )

                        elif item_type == "file_search_call":
                            # File search events
                            seq_num += 1
                            yield _sse_event(
                                "response.file_search_call.in_progress",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.file_search_call.in_progress",
                                },
                                seq_num,
                            )

                            seq_num += 1
                            yield _sse_event(
                                "response.file_search_call.searching",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.file_search_call.searching",
                                },
                                seq_num,
                            )

                            seq_num += 1
                            yield _sse_event(
                                "response.file_search_call.completed",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.file_search_call.completed",
                                },
                                seq_num,
                            )

                        elif item_type == "web_search_call":
                            # Web search events
                            seq_num += 1
                            yield _sse_event(
                                "response.web_search_call.in_progress",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.web_search_call.in_progress",
                                },
                                seq_num,
                            )

                            seq_num += 1
                            yield _sse_event(
                                "response.web_search_call.searching",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.web_search_call.searching",
                                },
                                seq_num,
                            )

                            seq_num += 1
                            yield _sse_event(
                                "response.web_search_call.completed",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.web_search_call.completed",
                                },
                                seq_num,
                            )

                        elif item_type == "image_generation_call":
                            # Image generation events
                            seq_num += 1
                            yield _sse_event(
                                "response.image_generation_call.in_progress",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.image_generation_call.in_progress",
                                },
                                seq_num,
                            )

                            seq_num += 1
                            yield _sse_event(
                                "response.image_generation_call.generating",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.image_generation_call.generating",
                                },
                                seq_num,
                            )

                            # Could simulate partial images here if result is available

                            seq_num += 1
                            yield _sse_event(
                                "response.image_generation_call.completed",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.image_generation_call.completed",
                                },
                                seq_num,
                            )

                        elif item_type == "code_interpreter_call":
                            # Code interpreter events
                            seq_num += 1
                            yield _sse_event(
                                "response.code_interpreter_call.in_progress",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.code_interpreter_call.in_progress",
                                },
                                seq_num,
                            )

                            # Stream code if available
                            code = item_dict.get("code", "")
                            if code:
                                for chunk in _iter_chunks(code):
                                    seq_num += 1
                                    yield _sse_event(
                                        "response.code_interpreter_call_code.delta",
                                        {
                                            "output_index": output_index,
                                            "item_id": item_id,
                                            "delta": chunk,
                                            "sequence_number": seq_num,
                                            "type": "response.code_interpreter_call_code.delta",
                                        },
                                        seq_num,
                                    )

                                seq_num += 1
                                yield _sse_event(
                                    "response.code_interpreter_call_code.done",
                                    {
                                        "output_index": output_index,
                                        "item_id": item_id,
                                        "code": code,
                                        "sequence_number": seq_num,
                                        "type": "response.code_interpreter_call_code.done",
                                    },
                                    seq_num,
                                )

                            seq_num += 1
                            yield _sse_event(
                                "response.code_interpreter_call.interpreting",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.code_interpreter_call.interpreting",
                                },
                                seq_num,
                            )

                            seq_num += 1
                            yield _sse_event(
                                "response.code_interpreter_call.completed",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.code_interpreter_call.completed",
                                },
                                seq_num,
                            )

                        elif item_type == "mcp_call":
                            # MCP call events
                            seq_num += 1
                            yield _sse_event(
                                "response.mcp_call.in_progress",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.mcp_call.in_progress",
                                },
                                seq_num,
                            )

                            # Stream MCP arguments
                            arguments = item_dict.get("arguments", "")
                            for chunk in _iter_chunks(arguments, max_len=32):
                                seq_num += 1
                                yield _sse_event(
                                    "response.mcp_call_arguments.delta",
                                    {
                                        "output_index": output_index,
                                        "item_id": item_id,
                                        "delta": chunk,
                                        "sequence_number": seq_num,
                                        "type": "response.mcp_call_arguments.delta",
                                    },
                                    seq_num,
                                )

                            seq_num += 1
                            yield _sse_event(
                                "response.mcp_call_arguments.done",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "arguments": arguments,
                                    "sequence_number": seq_num,
                                    "type": "response.mcp_call_arguments.done",
                                },
                                seq_num,
                            )

                            # Complete or fail based on error
                            if item_dict.get("error"):
                                seq_num += 1
                                yield _sse_event(
                                    "response.mcp_call.failed",
                                    {
                                        "output_index": output_index,
                                        "item_id": item_id,
                                        "sequence_number": seq_num,
                                        "type": "response.mcp_call.failed",
                                    },
                                    seq_num,
                                )
                            else:
                                seq_num += 1
                                yield _sse_event(
                                    "response.mcp_call.completed",
                                    {
                                        "output_index": output_index,
                                        "item_id": item_id,
                                        "sequence_number": seq_num,
                                        "type": "response.mcp_call.completed",
                                    },
                                    seq_num,
                                )

                        elif item_type == "mcp_list_tools":
                            # MCP list tools events
                            seq_num += 1
                            yield _sse_event(
                                "response.mcp_list_tools.in_progress",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "sequence_number": seq_num,
                                    "type": "response.mcp_list_tools.in_progress",
                                },
                                seq_num,
                            )

                            # Complete or fail based on error
                            if item_dict.get("error"):
                                seq_num += 1
                                yield _sse_event(
                                    "response.mcp_list_tools.failed",
                                    {
                                        "output_index": output_index,
                                        "item_id": item_id,
                                        "sequence_number": seq_num,
                                        "type": "response.mcp_list_tools.failed",
                                    },
                                    seq_num,
                                )
                            else:
                                seq_num += 1
                                yield _sse_event(
                                    "response.mcp_list_tools.completed",
                                    {
                                        "output_index": output_index,
                                        "item_id": item_id,
                                        "sequence_number": seq_num,
                                        "type": "response.mcp_list_tools.completed",
                                    },
                                    seq_num,
                                )

                        elif item_type == "custom_tool_call":
                            # Custom tool call events
                            input_data = item_dict.get("input", "")

                            # Stream custom tool input
                            for chunk in _iter_chunks(input_data, max_len=32):
                                seq_num += 1
                                yield _sse_event(
                                    "response.custom_tool_call_input.delta",
                                    {
                                        "output_index": output_index,
                                        "item_id": item_id,
                                        "delta": chunk,
                                        "sequence_number": seq_num,
                                        "type": "response.custom_tool_call_input.delta",
                                    },
                                    seq_num,
                                )

                            seq_num += 1
                            yield _sse_event(
                                "response.custom_tool_call_input.done",
                                {
                                    "output_index": output_index,
                                    "item_id": item_id,
                                    "input": input_data,
                                    "sequence_number": seq_num,
                                    "type": "response.custom_tool_call_input.done",
                                },
                                seq_num,
                            )

                        # 3d. response.output_item.done
                        seq_num += 1
                        # Update status to completed
                        item_dict_completed = dict(output_item)
                        if "status" in item_dict_completed:
                            item_dict_completed["status"] = "completed"

                        yield _sse_event(
                            "response.output_item.done",
                            {
                                "item": item_dict_completed,
                                "output_index": output_index,
                                "sequence_number": seq_num,
                                "type": "response.output_item.done",
                            },
                            seq_num,
                        )

                    # 4. response.completed event
                    seq_num += 1
                    completed_resp = dict(resp)
                    completed_resp["status"] = "completed"
                    yield _sse_event(
                        "response.completed",
                        {
                            "response": completed_resp,
                            "sequence_number": seq_num,
                            "type": "response.completed",
                        },
                        seq_num,
                    )

                return {
                    "status": 200,
                    "body_iter": stream_response(),
                    "headers": {
                        "Content-Type": "text/event-stream; charset=utf-8",
                        "Cache-Control": "no-cache",
                    },
                    "chunked": True,
                }
            else:
                return {"status": 200, "body": completion}

        except Exception as ex:
            _handle_model_proxy_error(ex)
            os._exit(1)

    @server.route("/v1/chat/completions", method="POST")
    async def chat_completions(request: dict[str, Any]) -> dict[str, Any]:
        try:
            json_body = request.get("json", {}) or {}
            stream = json_body.get("stream", False)

            # the openai codex cli seems to have a bug that causes
            # it to concatenate the 'arguments' of multiple tool_calls
            # when receiving them w/ stream=True (reproduced this as
            # well w/ the SDK going live against the ChatCompletion
            # API). Disable so we can side-step the bug.
            json_body["parallel_tool_calls"] = False

            completion = await call_bridge_model_service_async(
                "generate_completions", json_data=json_body
            )

            if stream:

                async def stream_response() -> AsyncIterator[bytes]:
                    # Parse the completion as a dict
                    chat_completion = (
                        completion
                        if isinstance(completion, dict)
                        else json.loads(completion)
                    )

                    comp_id = chat_completion.get("id")
                    created = chat_completion.get("created")
                    model = chat_completion.get("model")
                    sys_fp = chat_completion.get("system_fingerprint")

                    def base_chunk() -> dict[str, Any]:
                        obj: dict[str, Any] = {
                            "id": comp_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "choices": [],
                        }
                        if sys_fp is not None:
                            obj["system_fingerprint"] = sys_fp
                        return obj

                    # Stream each choice independently (common clients support this).
                    for choice_idx, choice in enumerate(
                        chat_completion.get("choices", [])
                    ):
                        msg = choice.get("message")
                        role = msg.get("role") if msg else "assistant"

                        # 1) Initial role chunk
                        chunk = base_chunk()
                        chunk["choices"] = [
                            {
                                "index": choice_idx,
                                "delta": {
                                    "role": role
                                },  # spec: role appears once at start
                                "finish_reason": None,
                            }
                        ]
                        yield _sse_bytes(chunk)

                        # 2) Text content chunks
                        content = msg.get("content") if msg else None
                        if isinstance(content, str) and content:
                            for piece in _iter_chunks(content):
                                chunk = base_chunk()
                                chunk["choices"] = [
                                    {
                                        "index": choice_idx,
                                        "delta": {"content": piece},
                                        "finish_reason": None,
                                    }
                                ]
                                yield _sse_bytes(chunk)
                                # Optional tiny yield to event loop; uncomment if you want pacing
                                # await asyncio.sleep(0)

                        # 3) Legacy function_call streaming (older models/libs)
                        fn_call = msg.get("function_call") if msg else None
                        if fn_call:
                            fn_name = fn_call.get("name", "")
                            fn_args = fn_call.get("arguments", "")

                            # name first
                            chunk = base_chunk()
                            chunk["choices"] = [
                                {
                                    "index": choice_idx,
                                    "delta": {"function_call": {"name": fn_name}},
                                    "finish_reason": None,
                                }
                            ]
                            yield _sse_bytes(chunk)

                            # arguments as incremental deltas
                            for piece in _iter_chunks(fn_args):
                                chunk = base_chunk()
                                chunk["choices"] = [
                                    {
                                        "index": choice_idx,
                                        "delta": {
                                            "function_call": {"arguments": piece}
                                        },
                                        "finish_reason": None,
                                    }
                                ]
                                yield _sse_bytes(chunk)

                        # 4) Modern tool_calls streaming (fixed: repeat id/type on every delta)
                        tool_calls = msg.get("tool_calls") if msg else None
                        if tool_calls:
                            for tc_i, tc in enumerate(tool_calls):
                                tc_id = tc.get("id")
                                tc_type = tc.get("type")
                                # Handle both function and custom tool calls
                                fn = tc.get("function")
                                fn_name = fn.get("name", "") if fn else ""
                                fn_args = fn.get("arguments", "") if fn else ""

                                # Emit initial tool_call with id/type/name
                                chunk = base_chunk()
                                chunk["choices"] = [
                                    {
                                        "index": choice_idx,
                                        "delta": {
                                            "tool_calls": [
                                                {
                                                    "index": tc_i,
                                                    "id": tc_id,
                                                    "type": tc_type,
                                                    "function": {"name": fn_name},
                                                }
                                            ]
                                        },
                                        "finish_reason": None,
                                    }
                                ]
                                yield _sse_bytes(chunk)

                                # Emit arguments in pieces — NOTE: repeat id/type every time
                                for piece in _iter_chunks(
                                    fn_args, max_len=len(fn_args) or 1
                                ):
                                    chunk = base_chunk()
                                    chunk["choices"] = [
                                        {
                                            "index": choice_idx,
                                            "delta": {
                                                "tool_calls": [
                                                    {
                                                        "index": tc_i,
                                                        "id": tc_id,  # ← repeat
                                                        "type": tc_type,  # ← repeat
                                                        "function": {
                                                            "arguments": piece
                                                        },
                                                    }
                                                ]
                                            },
                                            "finish_reason": None,
                                        }
                                    ]
                                    yield _sse_bytes(chunk)

                        # 5) Final chunk for this choice with finish_reason
                        finish_reason = choice.get(
                            "finish_reason"
                        )  # e.g., "stop", "length", "tool_calls"
                        chunk = base_chunk()
                        chunk["choices"] = [
                            {
                                "index": choice_idx,
                                "delta": {},  # end-of-stream sentinel for this choice
                                "finish_reason": finish_reason,
                            }
                        ]
                        yield _sse_bytes(chunk)

                    # 6) Optional usage chunk (if client requested include_usage and we have it)
                    stream_opts = json_body.get("stream_options") or {}
                    usage = chat_completion.get("usage")
                    if stream_opts.get("include_usage") and usage:
                        chunk = base_chunk()
                        chunk[
                            "choices"
                        ] = []  # per OpenAI: last chunk contains only usage
                        chunk["usage"] = usage
                        yield _sse_bytes(chunk)

                    # 7) Overall terminal sentinel
                    yield b"data: [DONE]\n\n"

                return {
                    "status": 200,
                    "body_iter": stream_response(),
                    "headers": {
                        "Content-Type": "text/event-stream; charset=utf-8",
                        "Cache-Control": "no-cache",
                    },
                    "chunked": True,
                }
            else:
                return {"status": 200, "body": completion}
        except Exception as ex:
            _handle_model_proxy_error(ex)
            os._exit(1)

    @server.route("/v1/messages", method="POST")
    async def anthropic(request: dict[str, Any]) -> dict[str, Any]:
        try:
            json_body = request.get("json", {}) or {}
            stream = json_body.get("stream", False)

            completion = await call_bridge_model_service_async(
                "generate_anthropic", json_data=json_body
            )

            if stream:

                async def stream_response() -> AsyncIterator[bytes]:
                    try:
                        # Parse the completion as a dict
                        message = (
                            completion
                            if isinstance(completion, dict)
                            else json.loads(completion)
                        )
                    except (json.JSONDecodeError, TypeError) as e:
                        # Send error event if we can't parse the response
                        error_event = {
                            "type": "error",
                            "error": {
                                "type": "invalid_response_error",
                                "message": f"Failed to parse response: {str(e)}",
                            },
                        }
                        yield f"event: error\ndata: {json.dumps(error_event)}\n\n".encode(
                            "utf-8"
                        )
                        return

                    def _sse_anthropic(event_type: str, data: dict[str, Any]) -> bytes:
                        # Anthropic uses both event: and data: lines
                        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode(
                            "utf-8"
                        )

                    # 1. message_start event
                    message_start = {
                        "type": "message_start",
                        "message": {
                            "id": message.get("id"),
                            "type": "message",
                            "role": message.get("role", "assistant"),
                            "content": [],
                            "model": message.get("model"),
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": {
                                "input_tokens": message.get("usage", {}).get(
                                    "input_tokens", 0
                                ),
                                "output_tokens": 1,
                            },
                        },
                    }
                    yield _sse_anthropic("message_start", message_start)

                    # 2. Process content blocks
                    content = message.get("content", [])
                    for index, block in enumerate(content):
                        # Optionally send ping events between blocks
                        if index > 0 and index % 3 == 0:
                            yield _sse_anthropic("ping", {"type": "ping"})
                        block_type = block.get("type")

                        if block_type == "text":
                            # content_block_start
                            yield _sse_anthropic(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": index,
                                    "content_block": {"type": "text", "text": ""},
                                },
                            )

                            # Stream text in chunks
                            text = block.get("text", "")
                            for chunk in _iter_chunks(text):
                                yield _sse_anthropic(
                                    "content_block_delta",
                                    {
                                        "type": "content_block_delta",
                                        "index": index,
                                        "delta": {"type": "text_delta", "text": chunk},
                                    },
                                )
                                await asyncio.sleep(0)  # Yield to event loop

                            # content_block_stop
                            yield _sse_anthropic(
                                "content_block_stop",
                                {"type": "content_block_stop", "index": index},
                            )

                        elif block_type in ["tool_use", "server_tool_use"]:
                            # content_block_start for tool_use or server_tool_use
                            content_block = {
                                "type": block_type,
                                "id": block.get("id"),
                                "name": block.get("name"),
                                "input": {},
                            }

                            yield _sse_anthropic(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": index,
                                    "content_block": content_block,
                                },
                            )

                            # Stream input as partial JSON
                            input_data = block.get("input", {})
                            input_json = json.dumps(input_data, ensure_ascii=False)

                            # Stream the JSON in chunks
                            for i in range(0, len(input_json), 20):
                                chunk = input_json[i : i + 20]
                                yield _sse_anthropic(
                                    "content_block_delta",
                                    {
                                        "type": "content_block_delta",
                                        "index": index,
                                        "delta": {
                                            "type": "input_json_delta",
                                            "partial_json": chunk,
                                        },
                                    },
                                )
                                await asyncio.sleep(0)

                            # content_block_stop
                            yield _sse_anthropic(
                                "content_block_stop",
                                {"type": "content_block_stop", "index": index},
                            )

                        elif block_type == "web_search_tool_result":
                            # Handle web search tool result blocks
                            yield _sse_anthropic(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": index,
                                    "content_block": {
                                        "type": "web_search_tool_result",
                                        "tool_use_id": block.get("tool_use_id"),
                                        "content": block.get("content", []),
                                    },
                                },
                            )

                            # Web search results are not streamed as deltas
                            yield _sse_anthropic(
                                "content_block_stop",
                                {"type": "content_block_stop", "index": index},
                            )

                        elif block_type == "thinking":
                            # content_block_start for thinking
                            yield _sse_anthropic(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": index,
                                    "content_block": {
                                        "type": "thinking",
                                        "thinking": "",
                                    },
                                },
                            )

                            # Stream thinking text
                            thinking_text = block.get("thinking", "")
                            for chunk in _iter_chunks(thinking_text):
                                yield _sse_anthropic(
                                    "content_block_delta",
                                    {
                                        "type": "content_block_delta",
                                        "index": index,
                                        "delta": {
                                            "type": "thinking_delta",
                                            "thinking": chunk,
                                        },
                                    },
                                )
                                await asyncio.sleep(0)

                            # Add signature if present
                            if block.get("signature"):
                                yield _sse_anthropic(
                                    "content_block_delta",
                                    {
                                        "type": "content_block_delta",
                                        "index": index,
                                        "delta": {
                                            "type": "signature_delta",
                                            "signature": block.get("signature"),
                                        },
                                    },
                                )

                            # content_block_stop
                            yield _sse_anthropic(
                                "content_block_stop",
                                {"type": "content_block_stop", "index": index},
                            )

                        elif block_type == "compaction":
                            # Compaction blocks stream differently - a single delta
                            # with the complete content (no intermediate streaming)
                            yield _sse_anthropic(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": index,
                                    "content_block": {
                                        "type": "compaction",
                                        "content": "",
                                    },
                                },
                            )

                            # Single delta with complete content
                            content_value = block.get("content", "")
                            yield _sse_anthropic(
                                "content_block_delta",
                                {
                                    "type": "content_block_delta",
                                    "index": index,
                                    "delta": {
                                        "type": "compaction_delta",
                                        "content": content_value,
                                    },
                                },
                            )

                            # content_block_stop
                            yield _sse_anthropic(
                                "content_block_stop",
                                {"type": "content_block_stop", "index": index},
                            )

                    # 3. message_delta event with cumulative usage
                    usage = message.get("usage", {})
                    message_delta_data: dict[str, Any] = {
                        "type": "message_delta",
                        "delta": {
                            "stop_reason": message.get("stop_reason"),
                            "stop_sequence": message.get("stop_sequence"),
                        },
                        "usage": {
                            "output_tokens": usage.get("output_tokens", 0),
                        },
                    }

                    # Add optional usage fields if present
                    if "input_tokens" in usage:
                        message_delta_data["usage"]["input_tokens"] = usage[
                            "input_tokens"
                        ]
                    if "cache_creation_input_tokens" in usage:
                        message_delta_data["usage"]["cache_creation_input_tokens"] = (
                            usage["cache_creation_input_tokens"]
                        )
                    if "cache_read_input_tokens" in usage:
                        message_delta_data["usage"]["cache_read_input_tokens"] = usage[
                            "cache_read_input_tokens"
                        ]

                    # Add server_tool_use if applicable (e.g., for web search)
                    if "server_tool_use" in usage:
                        message_delta_data["usage"]["server_tool_use"] = usage[
                            "server_tool_use"
                        ]

                    yield _sse_anthropic("message_delta", message_delta_data)

                    # 4. message_stop event
                    yield _sse_anthropic("message_stop", {"type": "message_stop"})

                return {
                    "status": 200,
                    "body_iter": stream_response(),
                    "headers": {
                        "Content-Type": "text/event-stream; charset=utf-8",
                        "Cache-Control": "no-cache",
                    },
                    "chunked": True,
                }
            else:
                return {"status": 200, "body": completion}
        except Exception as ex:
            _handle_model_proxy_error(ex)
            os._exit(1)

    # ---------- Google Gemini API routes ----------
    # Route patterns for Google's Gemini API using wildcard matching
    # Supports: /v1beta/models/{model}:generateContent and /models/{model}:generateContent

    def _extract_model_from_google_path(path: str) -> str:
        """Extract model name from Google API path.

        Examples:
            /v1beta/models/gemini-2.5-pro:generateContent -> gemini-2.5-pro
            /models/gemini-2.5-flash:streamGenerateContent -> gemini-2.5-flash
        """
        match = re.search(r"models/([^/:]+)", path)
        return match.group(1) if match else "inspect"

    @server.route("/v1beta/models/*", method="POST")
    @server.route("/models/*", method="POST")
    async def google_generate_content(request: dict[str, Any]) -> dict[str, Any]:
        try:
            path = request.get("path", "")
            json_body = request.get("json", {}) or {}

            is_streaming = ":streamGenerateContent" in path

            model_name = _extract_model_from_google_path(path)
            json_body["model"] = model_name

            completion = await call_bridge_model_service_async(
                "generate_google", json_data=json_body
            )

            resp = (
                completion if isinstance(completion, dict) else json.loads(completion)
            )

            if not is_streaming:
                return {"status": 200, "body": resp}

            async def single_chunk_stream() -> AsyncIterator[bytes]:
                yield f"data: {json.dumps(resp)}\n\n".encode("utf-8")

            return {
                "status": 200,
                "body_iter": single_chunk_stream(),
                "headers": {
                    "Content-Type": "text/event-stream; charset=utf-8",
                    "Cache-Control": "no-cache",
                },
                "chunked": True,
            }

        except Exception as ex:
            _handle_model_proxy_error(ex)
            os._exit(1)

    # return configured server
    return server


async def run_model_proxy_server(port: int) -> None:
    """Run the model proxy server.

    Args:
        port: Port to run the server on
    """
    # Create server
    server = await model_proxy_server(port)

    # Run server
    try:
        await server.start()
    except Exception as ex:
        sys.stderr.write(f"Unexpected error running model proxy: {ex}")
        sys.stderr.flush()
        os._exit(1)


def _handle_model_proxy_error(ex: Exception) -> None:
    # Any error that occurs in here is essentially fatal to the entire
    # agent. The exception results either from:
    #
    #  - The call to generate (which already benefits from Inspect's std
    #    model retry behavior). In normal Inspect agents if generate fails
    #    after requisite retries the sample fails, same here
    #  - A logic error or unexpected data condition in our simulated
    #    streaming -- if we are unable to stream a request back then
    #    the agent can't proceed, so we fail the script hard
    #
    # Writing to stderr and exiting the script is seen as preferable to
    # returning 500 to the proxied agent. This is because we are in a
    # hard failure anyway so we need the user to see the error message
    # and have the task fail (the 500 error would just result in retries)
    sys.stderr.write(f"Unexpected error during model proxy call: {ex}")
    sys.stderr.flush()


async def _call_bridge_model_service_async(method: str, **params: Any) -> Any:
    from asyncio import sleep

    request_id = _write_bridge_model_service_request(method, **params)
    while True:
        await sleep(0.1)
        success, result = _read_bridge_model_service_response(request_id, method)
        if success:
            return result


def _write_bridge_model_service_request(method: str, **params: Any) -> str:
    from json import dump
    from uuid import uuid4

    requests_dir = _bridge_model_service_service_dir("requests")
    request_id = str(uuid4())
    request_data = dict(id=request_id, method=method, params=params)
    request_path = requests_dir / (request_id + ".json")
    with open(request_path, "w") as f:
        dump(request_data, f)
    return request_id


def _read_bridge_model_service_response(
    request_id: str, method: str
) -> tuple[bool, Any]:
    from json import JSONDecodeError, load

    responses_dir = _bridge_model_service_service_dir("responses")
    response_path = responses_dir / (request_id + ".json")
    if response_path.exists():
        # read and remove the file
        with open(response_path, "r") as f:
            # it's possible the file is still being written so
            # just catch and wait for another retry if this occurs
            try:
                response = load(f)
            except JSONDecodeError:
                return False, None
        response_path.unlink()

        # raise error if we have one
        if response.get("error", None) is not None:
            raise Exception(response["error"])

        # return response if we have one
        elif "result" in response:
            return True, response["result"]

        # invalid response
        else:
            raise RuntimeError(
                "No error or result field in response for method " + method
            )
    else:
        return False, None


def _bridge_model_service_service_dir(subdir: str) -> Any:
    import os
    from pathlib import Path

    service_dir = Path("/var/tmp/sandbox-services/bridge_model_service")
    instance = os.environ.get("BRIDGE_MODEL_SERVICE_INSTANCE", None)
    if instance is not None:
        service_dir = service_dir / instance
    return service_dir / subdir


if __name__ == "__main__":
    DEFAULT_PROXY_PORT = 13131
    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PROXY_PORT
    asyncio.run(run_model_proxy_server(port=port_arg))
