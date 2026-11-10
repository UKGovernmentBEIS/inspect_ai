"""A stand-in for a model proxy with a sentinel sidecar behind it, for the sidecar client's tests.

The provider SDKs are given an httpx2 client whose transport answers here, so nothing leaves the process. Model calls are answered in the provider's own format, streamed when the request asks, and `request_result` answers with what was decided of each, by its `x-irid`.

It checks credentials as the sidecar does: it keeps the token an eval's first registration sends, never hands one back, and refuses a call or a model request whose signature doesn't match that token or whose timestamp is outside its window. A model request's signature covers its `x-irid`, and one without an `x-irid` is refused. The signatures are checked here with the standard library, not with Inspect's own signing, so the two are checked against each other.
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx2

ENDPOINT = "/sentinel/v1"
"""Where the endpoint for evals is served."""

WINDOW = 300
"""How far a signature's timestamp may be from the sidecar's clock, in seconds."""

INVALID_PARAMS = -32602
UNKNOWN_SAMPLE = -32002
UNKNOWN_TASK = -32009
UNAUTHORIZED = -32010

_SIGNED_CONTEXT = (
    "task",
    "sample_id",
    "epoch",
    "sample_uuid",
    "attempt",
    "attempt_number",
)


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

    later: float = 0.0
    """How many seconds the stand-in's clock moves on once the turn is answered, as during a long backoff before a retry. It needs `StandInSidecar.now` set."""

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

    echoed: dict[str, int] = field(default_factory=dict)
    """The methods answered with an HTTP error of this status whose body repeats the request, as a proxy's error page may."""

    turns: list[Turn] = field(default_factory=list)
    """The replies to model calls, in order. A call past the last is answered with a plain `Turn()`."""

    tokens: dict[str, str] = field(default_factory=dict)
    """The token kept for each eval, by its id, from its first registration. Clearing it is a restart that lost them."""

    now: float | None = None
    """The stand-in's clock, in seconds since the epoch, or None to read the real one."""

    requests: list[httpx2.Request] = field(default_factory=list)

    refused: list[str] = field(default_factory=list)
    """Why each call or model request refused for its credentials was refused, in order."""

    judgments: dict[str, dict[str, Any]] = field(default_factory=dict)
    """What was decided of each model call whose turn says, by its `x-irid`: the latest attempt's."""

    @property
    def probes(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path == "/sentinel/info"]

    @property
    def calls(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == ENDPOINT]

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
        if path == ENDPOINT:
            call = json.loads(request.content)
            method, params = call["method"], call["params"]
            if method in self.echoed:
                return httpx2.Response(
                    self.echoed[method],
                    json={
                        "error": {"type": "error", "message": request.content.decode()}
                    },
                )
            refused = self._unaccepted(method, params)
            if refused is not None:
                answer = refused
            elif method == "request_result" and params["id"] in self.judgments:
                # a turn that says what was decided of it is answered so
                answer = self._default("request_result")(params)
            else:
                answer = self.methods.get(method, self._default(method))(params)
            if method == "register_task" and "error" not in answer:
                # kept only once the registration succeeds
                token = params.get("token")
                if token is not None:
                    self.tokens.setdefault(params["eval_id"], token)
            body: dict[str, Any] = {"jsonrpc": "2.0", "id": call["id"]}
            if "error" in answer:
                body["error"] = answer["error"]
            else:
                body["result"] = answer
            return httpx2.Response(200, json=body)
        if path in _MODEL_ROUTES:
            asked = json.loads(request.content)
            context = request.headers.get("x-inspect-context")
            if context is not None:
                unread = self._unread(context, request.headers.get("x-irid"))
                if unread is not None:
                    # refused and not judged, as the sidecar does
                    self.refused.append(unread)
                    return httpx2.Response(
                        400, json={"error": {"type": "error", "message": unread}}
                    )
            turn = self.turns.pop(0) if self.turns else Turn()
            irid = request.headers.get("x-irid")
            if irid is not None and turn.judgment is not None:
                self.judgments[irid] = turn.judgment
            answered = _MODEL_ROUTES[path](turn, bool(asked.get("stream")), asked)
            if turn.later:
                assert self.now is not None, "a turn's `later` needs `now` set"
                self.now += turn.later
            return answered
        return httpx2.Response(404, json={"error": f"no route {path}"})

    def clock(self) -> float:
        """The stand-in's time, in seconds since the epoch."""
        return self.now if self.now is not None else time.time()

    def _signed(
        self, token: str, values: list[Any], timestamp: Any, mac: Any
    ) -> str | None:
        # why a signature isn't accepted, or None when it is
        if not isinstance(timestamp, int) or not isinstance(mac, str):
            return "the timestamp or the mac is missing"
        off = timestamp - self.clock()
        if abs(off) > WINDOW:
            return f"the timestamp is {off:+.0f} seconds from the sidecar's clock"
        message = json.dumps([str(v) for v in values], separators=(",", ":"))
        expected = hmac.new(token.encode(), message.encode(), hashlib.sha256)
        if not hmac.compare_digest(expected.hexdigest(), mac):
            return "the mac doesn't match"
        return None

    def _unaccepted(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        # the answer to a call whose credentials aren't accepted, as the
        # sidecar gives it, or None for one that goes on to the method
        eval_id = params.get("eval_id")
        held = self.tokens.get(eval_id) if isinstance(eval_id, str) else None
        signed = "timestamp" in params and "mac" in params
        partly = ("timestamp" in params) != ("mac" in params)
        if method == "register_task":
            # exactly one of a token and a signature
            token = params.get("token")
            if (token is not None) == signed or partly:
                return self._refuse(INVALID_PARAMS, "send a token or a signature")
            if token is not None:
                if not isinstance(token, str) or len(token) < 32:
                    return self._refuse(INVALID_PARAMS, "the token is too short")
                if held is not None and not hmac.compare_digest(held, token):
                    return self._refuse(UNAUTHORIZED, "another token")
                return None
            if held is None:
                return self._refuse(UNKNOWN_TASK, "no token held for the eval")
        else:
            if "token" in params or not signed:
                return self._refuse(INVALID_PARAMS, "send a signature, not a token")
            if held is None:
                # a sidecar that holds no token for the eval holds nothing of it
                return _holds_nothing(method, params)
        assert held is not None
        why = self._signed(
            held,
            [method, eval_id, params["timestamp"]],
            params["timestamp"],
            params["mac"],
        )
        return self._refuse(UNAUTHORIZED, why) if why is not None else None

    def _refuse(self, code: int, message: str) -> dict[str, Any]:
        self.refused.append(message)
        return {"error": {"code": code, "message": message}}

    def _unread(self, header: str, irid: str | None) -> str | None:
        # why a model request's `x-inspect-context` isn't accepted, or None
        # when it is; its signature covers the request's `x-irid`
        try:
            context = json.loads(header)
        except ValueError:
            return "the header isn't JSON"
        if not isinstance(context, dict) or context.get("version") != 1:
            return "the header isn't version 1"
        if "token" in context:
            return "the header carries a token"
        held = self.tokens.get(context.get("eval_id", ""))
        if held is None:
            return "the sidecar holds no registration of the eval"
        if any(name not in context for name in _SIGNED_CONTEXT):
            return "the header lacks a field"
        if irid is None:
            return "the request has no x-irid"
        values = [
            "model-request",
            *(context[name] for name in _SIGNED_CONTEXT),
            irid,
            context.get("timestamp"),
        ]
        return self._signed(held, values, context.get("timestamp"), context.get("mac"))

    def _default(self, method: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        # a registration never gives a token; a call whose turn says what was
        # decided is answered with it
        if method == "register_task":
            return lambda params: {
                "eval_id": params.get("eval_id"),
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


def _holds_nothing(method: str, params: dict[str, Any]) -> dict[str, Any]:
    # the answer of a sidecar that holds no token for the eval, as after a
    # restart: it holds nothing of the eval for anyone
    if method == "complete_registration":
        return {"error": {"code": UNKNOWN_TASK, "message": "no token for the eval"}}
    if method == "request_result":
        return {"id": params.get("id"), "records": "unknown"}
    if method == "sample_result":
        return {"error": {"code": UNKNOWN_SAMPLE, "message": "nothing for the sample"}}
    if method == "end_sample":
        return {"sample_uuid": params.get("sample_uuid"), "state": "unknown"}
    return {"error": {"code": INVALID_PARAMS, "message": f"no method {method}"}}


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
