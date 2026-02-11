"""mitmproxy addon that intercepts and remaps HTTP requests.

Remapped requests are forwarded to the sandbox_agent_bridge model proxy on
localhost, which routes them to the host. The host calls the real model API
with its own credentials — no API keys are needed in the container.
"""

import json
import os

from mitmproxy import http

BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "13131"))
FAKE_API_HOST = os.environ.get("FAKE_API_HOST", "api.futuremodel.ai")
FAKE_MODEL = os.environ.get("FAKE_MODEL", "futuremodel-1")


def request(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host

    if host == FAKE_API_HOST:
        flow.metadata["remapped_from"] = FAKE_API_HOST

        flow.request.scheme = "http"
        flow.request.host = "localhost"
        flow.request.port = BRIDGE_PORT
        flow.request.headers["host"] = f"localhost:{BRIDGE_PORT}"
        return

    # Reject all other requests
    flow.response = http.Response.make(
        403,
        json.dumps({"error": f"Access to {host} is not allowed"}).encode(),
        {"Content-Type": "application/json"},
    )


def response(flow: http.HTTPFlow) -> None:
    # For remapped requests, rewrite the model name in responses so the
    # agent sees the fake model name it expects.
    if not flow.metadata.get("remapped_from"):
        return

    if flow.response and flow.response.content:
        try:
            body = json.loads(flow.response.content)
            if "model" in body:
                body["model"] = FAKE_MODEL
                flow.response.content = json.dumps(body).encode()
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
