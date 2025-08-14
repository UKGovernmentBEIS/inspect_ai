from __future__ import annotations

import asyncio
import json
import time
from email.utils import formatdate
from http import HTTPStatus
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, TypeAlias
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
