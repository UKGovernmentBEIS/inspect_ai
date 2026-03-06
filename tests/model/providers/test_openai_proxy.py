import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from inspect_ai.model._openai import OpenAIAsyncHttpxClient


class _EchoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args) -> None:  # pragma: no cover
        # Silence noisy server logs for the test run.
        pass


@contextmanager
def _http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.anyio
async def test_openai_async_client_respects_http_proxy(monkeypatch: pytest.MonkeyPatch):
    # Configure fake proxy env vars that point to a closed port so requests
    # should fail fast if the client attempts to tunnel through a proxy.
    proxy_url = "http://127.0.0.1:9"
    for key in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
        monkeypatch.setenv(key, proxy_url)

    with _http_server() as port:
        async with OpenAIAsyncHttpxClient() as client:
            with pytest.raises(httpx.TransportError):
                await client.get(f"http://127.0.0.1:{port}/")
