"""A stand-in for a model proxy with a sentinel sidecar behind it, for the sidecar client's tests.

The provider SDKs are given an httpx2 client whose transport answers here, so nothing leaves the process. Model calls are answered in the provider's own format, streamed when the request asks, with the `sentinel` field where a sidecar puts it.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx2


@dataclass
class Turn:
    """One model reply, as the proxy hands it to the client."""

    text: str = "Done."
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    """Tool calls, each as its id, function and arguments."""

    sentinel: dict[str, Any] | None = None
    """The `sentinel` field, or None to send none."""

    status: int = 200
    """An error status refuses the call, with the field beside the error, as Envoy puts it."""

    nested: bool = False
    """Put the field of an error at `error.provider_specific_fields.sentinel`, as LiteLLM does."""


@dataclass
class StandInSidecar:
    """Answers the probe, the endpoint for evals and model calls as a proxy with a sidecar does, and records every request."""

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

    turns: list[Turn] = field(default_factory=list)
    """The replies to model calls, in order. A call past the last is answered with a plain `Turn()`."""

    requests: list[httpx2.Request] = field(default_factory=list)

    @property
    def probes(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path == "/sentinel/info"]

    @property
    def calls(self) -> list[dict[str, Any]]:
        return [
            json.loads(r.content) for r in self.requests if r.url.path == "/sentinel/v1"
        ]

    @property
    def model_calls(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path in _MODEL_ROUTES]

    def http_client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle))

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/sentinel/info":
            if self.info is None:
                return httpx2.Response(404, json={"error": "not found"})
            return httpx2.Response(self.probe_status, json=self.info)
        if path == "/sentinel/v1":
            call = json.loads(request.content)
            answer = self.methods.get(call["method"], lambda params: {})(call["params"])
            body: dict[str, Any] = {"jsonrpc": "2.0", "id": call["id"]}
            if "error" in answer:
                body["error"] = answer["error"]
            else:
                body["result"] = answer
            return httpx2.Response(200, json=body)
        if path in _MODEL_ROUTES:
            asked = json.loads(request.content)
            turn = self.turns.pop(0) if self.turns else Turn()
            return _MODEL_ROUTES[path](turn, bool(asked.get("stream")), asked)
        return httpx2.Response(404, json={"error": f"no route {path}"})


def _anthropic(turn: Turn, stream: bool, asked: dict[str, Any]) -> httpx2.Response:
    if turn.status != 200:
        error: dict[str, Any] = {"type": "invalid_request_error", "message": "Refused."}
        return _error(turn, {"type": "error", "error": error}, error)
    content: list[dict[str, Any]] = [{"type": "text", "text": turn.text}]
    content += [
        {"type": "tool_use", "id": id, "name": name, "input": arguments}
        for id, name, arguments in turn.calls
    ]
    stop = "tool_use" if turn.calls else "end_turn"
    message = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": asked["model"],
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }
    if not stream:
        return httpx2.Response(200, json=_with_field(message, turn))
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "message_start",
            {"type": "message_start", "message": {**message, "content": []}},
        )
    ]
    for index, block in enumerate(content):
        start: dict[str, Any]
        if block["type"] == "text":
            start = {"type": "text", "text": ""}
            delta = {"type": "text_delta", "text": block["text"]}
        else:
            start = {**block, "input": {}}
            delta = {
                "type": "input_json_delta",
                "partial_json": json.dumps(block["input"]),
            }
        events += [
            (
                "content_block_start",
                {"type": "content_block_start", "index": index, "content_block": start},
            ),
            (
                "content_block_delta",
                {"type": "content_block_delta", "index": index, "delta": delta},
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": index}),
        ]
    events += [
        (
            "message_delta",
            _with_field(
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop, "stop_sequence": None},
                    "usage": {"output_tokens": 2},
                },
                turn,
            ),
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return _sse(events)


def _responses(turn: Turn, stream: bool, asked: dict[str, Any]) -> httpx2.Response:
    if turn.status != 200:
        error: dict[str, Any] = {
            "message": "Refused.",
            "type": "invalid_request_error",
            "param": None,
            "code": None,
        }
        return _error(turn, {"error": error}, error)
    output: list[dict[str, Any]] = [
        {
            "type": "message",
            "id": "msg_1",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": turn.text, "annotations": []}],
        }
    ]
    output += [
        {
            "type": "function_call",
            "id": f"fc_{id}",
            "call_id": id,
            "name": name,
            "arguments": json.dumps(arguments),
            "status": "completed",
        }
        for id, name, arguments in turn.calls
    ]
    response = {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": asked["model"],
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 5,
            "output_tokens": 2,
            "total_tokens": 7,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }
    if not stream:
        return httpx2.Response(200, json=_with_field(response, turn))
    return _sse(
        [
            (
                "response.created",
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {**response, "status": "in_progress", "output": []},
                },
            ),
            (
                "response.completed",
                _with_field(
                    {
                        "type": "response.completed",
                        "sequence_number": 1,
                        "response": response,
                    },
                    turn,
                ),
            ),
        ]
    )


def _chat(turn: Turn, stream: bool, asked: dict[str, Any]) -> httpx2.Response:
    if turn.status != 200:
        error: dict[str, Any] = {
            "message": "Refused.",
            "type": "invalid_request_error",
            "param": None,
            "code": None,
        }
        return _error(turn, {"error": error}, error)
    calls = [
        {
            "id": id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }
        for id, name, arguments in turn.calls
    ]
    message: dict[str, Any] = {"role": "assistant", "content": turn.text}
    if calls:
        message["tool_calls"] = calls
    finish = "tool_calls" if calls else "stop"
    usage = {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
    completion = {
        "id": "chatcmpl_1",
        "object": "chat.completion",
        "created": 0,
        "model": asked["model"],
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": usage,
    }
    if not stream:
        return httpx2.Response(200, json=_with_field(completion, turn))
    chunk = {
        "id": "chatcmpl_1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": asked["model"],
    }
    delta: dict[str, Any] = {"role": "assistant", "content": turn.text}
    if calls:
        delta["tool_calls"] = [{"index": i, **call} for i, call in enumerate(calls)]
    return _sse(
        [
            (
                "",
                {
                    **chunk,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                },
            ),
            (
                "",
                _with_field(
                    {
                        **chunk,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                        "usage": usage,
                    },
                    turn,
                ),
            ),
        ]
    )


_MODEL_ROUTES = {
    "/v1/messages": _anthropic,
    "/v1/responses": _responses,
    "/v1/chat/completions": _chat,
}


def _with_field(data: dict[str, Any], turn: Turn) -> dict[str, Any]:
    return {**data, "sentinel": turn.sentinel} if turn.sentinel is not None else data


def _error(turn: Turn, body: dict[str, Any], error: dict[str, Any]) -> httpx2.Response:
    if turn.sentinel is not None and turn.nested:
        error["provider_specific_fields"] = {"sentinel": turn.sentinel}
    elif turn.sentinel is not None:
        body["sentinel"] = turn.sentinel
    return httpx2.Response(turn.status, json=body)


def _sse(events: list[tuple[str, dict[str, Any]]]) -> httpx2.Response:
    lines = []
    for name, data in events:
        if name:
            lines.append(f"event: {name}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")
    if not events or not events[0][0]:
        lines += ["data: [DONE]", ""]
    return httpx2.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="\n".join(lines).encode(),
    )
