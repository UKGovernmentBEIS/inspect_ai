"""A stand-in for a model proxy with a sentinel sidecar behind it, for the sidecar client's tests.

The provider SDKs are given an httpx2 client whose transport answers here, so nothing leaves the process. Model calls are answered in the provider's own format, streamed when the request asks, and `request_result` answers with what was decided of each, by its `x-irid`.
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

    judgment: dict[str, Any] | None = None
    """What the sidecar decided of the call, which `request_result` answers with by the call's `x-irid`, before `methods` is asked; or None to leave `request_result` to `methods`."""

    status: int = 200
    """An error status refuses the call, with an error in the provider's format."""

    stop_reason: str | None = None
    """An Anthropic stop reason in place of the one the turn's content gives, such as `pause_turn`."""


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
    probe_statuses: list[int] = field(default_factory=list)
    """The status of each probe in turn, before `probe_status` answers the rest."""
    methods: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = field(
        default_factory=dict
    )
    """Answers to the endpoint's methods, by name: each returns the JSON-RPC result, or an `error` object to answer with."""

    turns: list[Turn] = field(default_factory=list)
    """The replies to model calls, in order. A call past the last is answered with a plain `Turn()`."""

    token: str = "token-1"
    """The token `register_task` gives the eval, unless `methods` answers it."""

    requests: list[httpx2.Request] = field(default_factory=list)

    judgments: dict[str, dict[str, Any]] = field(default_factory=dict)
    """What was decided of each model call whose turn says, by its `x-irid`: the latest attempt's."""

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
            status = (
                self.probe_statuses.pop(0) if self.probe_statuses else self.probe_status
            )
            return httpx2.Response(status, json=self.info)
        if path == "/sentinel/v1":
            call = json.loads(request.content)
            params = call["params"]
            if call["method"] == "request_result" and params["id"] in self.judgments:
                # a turn that says what was decided of it is answered so
                answer = self._default("request_result")(params)
            else:
                answer = self.methods.get(
                    call["method"], self._default(call["method"])
                )(params)
            body: dict[str, Any] = {"jsonrpc": "2.0", "id": call["id"]}
            if "error" in answer:
                body["error"] = answer["error"]
            else:
                body["result"] = answer
            return httpx2.Response(200, json=body)
        if path in _MODEL_ROUTES:
            asked = json.loads(request.content)
            turn = self.turns.pop(0) if self.turns else Turn()
            irid = request.headers.get("x-irid")
            if irid is not None and turn.judgment is not None:
                self.judgments[irid] = turn.judgment
            return _MODEL_ROUTES[path](turn, bool(asked.get("stream")), asked)
        return httpx2.Response(404, json={"error": f"no route {path}"})

    def _default(self, method: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        # a registration gives the token; a call whose turn says what was
        # decided is answered with it
        if method == "register_task":
            return lambda params: {
                "eval_id": params.get("eval_id"),
                "token": self.token,
                "task": params.get("task"),
                "samples": len(params.get("sample_ids", [])),
                "fixed": False,
            }
        if method == "request_result":
            return lambda params: (
                {
                    "id": params["id"],
                    "records": "held",
                    "state": "decided",
                    "judgment": self.judgments[params["id"]],
                }
                if params["id"] in self.judgments
                else {}
            )
        if method == "sample_result":
            # a sidecar's answer always holds the store, if only an empty one
            return lambda params: {
                "sample_uuid": params.get("sample_uuid"),
                "outcome": "proceed",
                "store": {},
            }
        return lambda params: {}


def _anthropic(turn: Turn, stream: bool, asked: dict[str, Any]) -> httpx2.Response:
    if turn.status != 200:
        error: dict[str, Any] = {"type": "invalid_request_error", "message": "Refused."}
        return _error(turn, {"type": "error", "error": error})
    content: list[dict[str, Any]] = [{"type": "text", "text": turn.text}]
    content += [
        {"type": "tool_use", "id": id, "name": name, "input": arguments}
        for id, name, arguments in turn.calls
    ]
    stop = turn.stop_reason or ("tool_use" if turn.calls else "end_turn")
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
        return httpx2.Response(200, json=message)
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
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop, "stop_sequence": None},
                "usage": {"output_tokens": 2},
            },
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
        return _error(turn, {"error": error})
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
        return httpx2.Response(200, json=response)
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
                {
                    "type": "response.completed",
                    "sequence_number": 1,
                    "response": response,
                },
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
        return _error(turn, {"error": error})
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
        return httpx2.Response(200, json=completion)
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
                {
                    **chunk,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                    "usage": usage,
                },
            ),
        ]
    )


_MODEL_ROUTES = {
    "/v1/messages": _anthropic,
    "/v1/responses": _responses,
    "/v1/chat/completions": _chat,
}


def _error(turn: Turn, body: dict[str, Any]) -> httpx2.Response:
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
