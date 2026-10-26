"""A stand-in for a model proxy with a sentinel sidecar behind it, for the sidecar client's tests.

The provider SDKs are given an httpx2 client whose transport answers here, so nothing leaves the process.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx2


@dataclass
class StandInSidecar:
    """Answers the probe and the endpoint for evals as a sidecar does, and records every request."""

    info: dict[str, Any] | None = field(
        default_factory=lambda: {
            "service": "inspect_sentinel",
            "versions": [1],
            "release": "whole",
        }
    )
    """The probe's answer, or None to answer it with a 404, as a proxy with no sidecar does."""

    probe_status: int = 200
    methods: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = field(
        default_factory=dict
    )
    """Answers to the endpoint's methods, by name: each returns the JSON-RPC result, or an `error` object to answer with."""

    requests: list[httpx2.Request] = field(default_factory=list)

    @property
    def probes(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path == "/sentinel/info"]

    @property
    def calls(self) -> list[dict[str, Any]]:
        return [
            json.loads(r.content) for r in self.requests if r.url.path == "/sentinel/v1"
        ]

    def http_client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle))

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path == "/sentinel/info":
            if self.info is None:
                return httpx2.Response(404, json={"error": "not found"})
            return httpx2.Response(self.probe_status, json=self.info)
        if request.url.path == "/sentinel/v1":
            call = json.loads(request.content)
            answer = self.methods.get(call["method"], lambda params: {})(call["params"])
            body: dict[str, Any] = {"jsonrpc": "2.0", "id": call["id"]}
            if "error" in answer:
                body["error"] = answer["error"]
            else:
                body["result"] = answer
            return httpx2.Response(200, json=body)
        return httpx2.Response(404, json={"error": f"no route {request.url.path}"})
