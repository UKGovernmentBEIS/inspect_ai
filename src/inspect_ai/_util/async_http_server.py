"""Async HTTP server with minimal dependencies for OpenAI-compatible endpoints."""

import asyncio
import json
from http import HTTPStatus
from typing import Any, Awaitable, Callable, TypeAlias
from urllib.parse import urlparse

RequestHandler: TypeAlias = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
RouteMap: TypeAlias = dict[str, RequestHandler]
MethodRoutes: TypeAlias = dict[str, RouteMap]


class AsyncHTTPServer:
    """Async HTTP server supporting GET/POST requests."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        """Initialize the server.

        Args:
            host: Host to bind to
            port: Port to bind to
        """
        self.host = host
        self.port = port
        self.routes: MethodRoutes = {"GET": {}, "POST": {}}
        self.server: asyncio.Server | None = None

    def route(
        self, path: str, method: str = "GET"
    ) -> Callable[[RequestHandler], RequestHandler]:
        """Decorator to register a route handler.

        Args:
            path: URL path to handle
            method: HTTP method (GET or POST)

        Returns:
            Decorator function
        """

        def decorator(handler: RequestHandler) -> RequestHandler:
            if method not in self.routes:
                raise ValueError(f"Unsupported method: {method}")
            self.routes[method][path] = handler
            return handler

        return decorator

    def add_route(
        self, path: str, handler: RequestHandler, method: str = "GET"
    ) -> None:
        """Add a route handler programmatically.

        Args:
            path: URL path to handle
            handler: Async function to handle requests
            method: HTTP method (GET or POST)
        """
        if method not in self.routes:
            raise ValueError(f"Unsupported method: {method}")
        self.routes[method][path] = handler

    async def _parse_request(
        self, reader: asyncio.StreamReader
    ) -> tuple[str, str, dict[str, str], bytes | None]:
        """Parse HTTP request.

        Args:
            reader: Stream reader

        Returns:
            Tuple of (method, path, headers, body)
        """
        # Read request line
        request_line = await reader.readline()
        if not request_line:
            raise ValueError("Empty request")

        parts = request_line.decode().strip().split()
        if len(parts) != 3:
            raise ValueError("Invalid request line")

        method, full_path, _ = parts

        # Parse path and query params
        parsed = urlparse(full_path)
        path = parsed.path

        # Read headers
        headers: dict[str, str] = {}
        while True:
            header_line = await reader.readline()
            if header_line == b"\r\n" or header_line == b"\n" or not header_line:
                break

            header = header_line.decode().strip()
            if ":" in header:
                key, value = header.split(":", 1)
                headers[key.strip().lower()] = value.strip()

        # Read body if present
        body = None
        if "content-length" in headers:
            content_length = int(headers["content-length"])
            body = await reader.read(content_length)

        return method, path, headers, body

    def _build_response(
        self,
        status: int,
        body: str | bytes | dict[str, Any] | None = None,
        content_type: str = "application/json",
    ) -> bytes:
        """Build HTTP response.

        Args:
            status: HTTP status code
            body: Response body
            content_type: Content type

        Returns:
            Formatted HTTP response
        """
        status_line = f"HTTP/1.1 {status} {HTTPStatus(status).phrase}"

        # Convert body to bytes if needed
        if body is None:
            body_bytes = b""
        elif isinstance(body, dict):
            body_bytes = json.dumps(body).encode()
        elif isinstance(body, str):
            body_bytes = body.encode()
        else:
            body_bytes = body

        headers = [
            status_line,
            f"Content-Type: {content_type}",
            f"Content-Length: {len(body_bytes)}",
            "Connection: close",
            "",
            "",
        ]

        response = "\r\n".join(headers).encode() + body_bytes
        return response

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle client connection.

        Args:
            reader: Stream reader
            writer: Stream writer
        """
        try:
            method, path, headers, body = await self._parse_request(reader)

            # Find handler
            handler = self.routes.get(method, {}).get(path)

            if handler:
                # Prepare request data
                request_data = {
                    "method": method,
                    "path": path,
                    "headers": headers,
                    "body": None,
                }

                if body:
                    # Try to parse as JSON
                    try:
                        request_data["body"] = json.loads(body.decode())
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        request_data["body"] = body.decode("utf-8", errors="replace")

                # Call handler
                response = await handler(request_data)

                # Send response
                status = response.get("status", 200)
                body_data = response.get("body")
                content_type = response.get("content_type", "application/json")

                response_bytes = self._build_response(status, body_data, content_type)
                writer.write(response_bytes)
            else:
                # 404 Not Found
                error_response = {
                    "error": {
                        "message": f"Path {path} not found",
                        "type": "not_found",
                        "code": 404,
                    }
                }
                response_bytes = self._build_response(404, error_response)
                writer.write(response_bytes)

            await writer.drain()
        except Exception as e:
            # Send error response
            error_response = {
                "error": {"message": str(e), "type": "internal_error", "code": 500}
            }
            try:
                response_bytes = self._build_response(500, error_response)
                writer.write(response_bytes)
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def start(self) -> None:
        """Start the server."""
        self.server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )

        print(f"Server running on http://{self.host}:{self.port}")

        async with self.server:
            await self.server.serve_forever()

    async def stop(self) -> None:
        """Stop the server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
