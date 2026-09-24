"""Fake upstream providers for offline LiteLLM proxy tests.

One HTTP server on the test host serves every provider format, routed by
path; the proxy container reaches it at `host.docker.internal`. Responses are
deterministic functions of the request (the `*_response` functions), carrying
recognizable reasoning, signatures and encrypted content, so a test can
recompute what was served on a turn and check what LiteLLM sent back on the
next one. Streaming requests get the same response encoded as that provider's
server-sent events.

Each response depends only on the conversation so far:

- First turn with tools: reasoning plus a tool call (two parallel calls for
  Gemini).
- First turn without tools: reasoning plus text.
- Later turns: reasoning plus a final answer.
"""

import base64
import json
import threading
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, NamedTuple

from .proxy import DOCKER_HOST_ALIAS

TOOL_ARGS = {"city": "Paris"}
FIRST_TEXT = "Hello! Ask me about the weather."
FINAL_TEXT = "It is sunny in Paris."
USAGE_TOKENS = 10


class StubRequest(NamedTuple):
    path: str
    body: Any


class SSE(NamedTuple):
    """A streamed response: (event name or None, data) pairs."""

    events: list[tuple[str | None, Any]]


class Reply(NamedTuple):
    """A JSON response with a status other than 200, or extra headers."""

    status: int
    body: Any
    headers: dict[str, str] = {}


Router = Callable[[StubRequest], dict[str, Any] | SSE | Reply | None]


class FakeUpstream:
    """A running fake upstream: its address and the requests it received."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.requests: list[StubRequest] = []

    @property
    def docker_url(self) -> str:
        """Base URL for the proxy container to reach this server."""
        return f"http://{DOCKER_HOST_ALIAS}:{self.port}"


@contextmanager
def fake_upstream(router: Router | None = None) -> Iterator[FakeUpstream]:
    """Serve all fake providers on an ephemeral port on all interfaces.

    Args:
        router: Response for each request; defaults to `route`.
    """
    upstream: FakeUpstream | None = None

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            assert upstream is not None
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            request = StubRequest(path=self.path, body=json.loads(raw) if raw else None)
            upstream.requests.append(request)
            try:
                response = (router or route)(request)
            except Exception:
                self._send_json(500, {"error": traceback.format_exc()})
                return
            if response is None:
                self._send_json(404, {"error": f"no fake upstream for {self.path}"})
            elif isinstance(response, SSE):
                self._send_sse(response)
            elif isinstance(response, Reply):
                self._send_json(response.status, response.body, response.headers)
            else:
                self._send_json(200, response)

        def _send_json(
            self, status: int, body: Any, headers: dict[str, str] | None = None
        ) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_sse(self, response: SSE) -> None:
            # HTTP/1.0: the connection closes after the stream, ending it
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for event, data in response.events:
                payload = data if isinstance(data, str) else json.dumps(data)
                chunk = f"event: {event}\n" if event else ""
                self.wfile.write(f"{chunk}data: {payload}\n\n".encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    # all interfaces: the proxy container connects via the Docker host gateway
    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    upstream = FakeUpstream(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield upstream
    finally:
        server.shutdown()
        server.server_close()


def route(request: StubRequest) -> dict[str, Any] | SSE | None:
    path = request.path.split("?")[0]
    body = request.body
    if path.endswith("/v1/messages"):
        response = anthropic_response(body)
        return anthropic_sse(response) if body.get("stream") else response
    if ":generateContent" in path or ":streamGenerateContent" in path:
        response = gemini_response(body)
        return SSE([(None, response)]) if "streamGenerateContent" in path else response
    if path.endswith("/responses"):
        response = openai_responses_response(body)
        return openai_responses_sse(response) if body.get("stream") else response
    if path.endswith("/chat/completions"):
        response = reasoning_content_chat_response(body)
        return reasoning_content_chat_sse(response) if body.get("stream") else response
    if path.endswith("/converse"):
        return bedrock_converse_response(body)
    return None


def _turn(prior_turns: int, has_tools: bool) -> str:
    if prior_turns > 0:
        return "final"
    return "tool" if has_tools else "text"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


# Anthropic Messages ---------------------------------------------------------


def anthropic_response(body: dict[str, Any]) -> dict[str, Any]:
    prior = sum(1 for m in body["messages"] if m["role"] == "assistant")
    tools = body.get("tools") or []
    turn = _turn(prior, bool(tools))
    n = prior + 1
    content: list[dict[str, Any]] = [
        {
            "type": "thinking",
            "thinking": f"Anthropic thinking for turn {n}.",
            "signature": f"stub-anthropic-signature-{n}",
        }
    ]
    if turn != "final":
        content.append(
            {"type": "redacted_thinking", "data": f"stub-anthropic-redacted-{n}"}
        )
    if turn == "tool":
        content.append(
            {
                "type": "tool_use",
                "id": f"toolu_stub_{n}",
                "name": tools[0]["name"],
                "input": TOOL_ARGS,
            }
        )
    else:
        content.append(
            {"type": "text", "text": FIRST_TEXT if turn == "text" else FINAL_TEXT}
        )
    return {
        "id": f"msg_stub_{n}",
        "type": "message",
        "role": "assistant",
        "model": body["model"],
        "content": content,
        "stop_reason": "tool_use" if turn == "tool" else "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": USAGE_TOKENS, "output_tokens": USAGE_TOKENS},
    }


def anthropic_sse(response: dict[str, Any]) -> SSE:
    events: list[tuple[str | None, Any]] = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": response
                | {
                    "content": [],
                    "stop_reason": None,
                    "usage": {"input_tokens": USAGE_TOKENS, "output_tokens": 1},
                },
            },
        )
    ]
    for index, block in enumerate(response["content"]):
        kind = block["type"]
        start: dict[str, Any]
        deltas: list[dict[str, Any]] = []
        if kind == "thinking":
            start = {"type": "thinking", "thinking": ""}
            deltas = [
                {"type": "thinking_delta", "thinking": block["thinking"]},
                {"type": "signature_delta", "signature": block["signature"]},
            ]
        elif kind == "redacted_thinking":
            start = block
        elif kind == "text":
            start = {"type": "text", "text": ""}
            deltas = [{"type": "text_delta", "text": block["text"]}]
        else:
            start = block | {"input": {}}
            deltas = [
                {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
            ]
        events.append(
            (
                "content_block_start",
                {"type": "content_block_start", "index": index, "content_block": start},
            )
        )
        for delta in deltas:
            events.append(
                (
                    "content_block_delta",
                    {"type": "content_block_delta", "index": index, "delta": delta},
                )
            )
        events.append(
            ("content_block_stop", {"type": "content_block_stop", "index": index})
        )
    events += [
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": response["stop_reason"],
                    "stop_sequence": None,
                },
                "usage": {"output_tokens": USAGE_TOKENS},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return SSE(events)


# Gemini generateContent -----------------------------------------------------


def gemini_response(body: dict[str, Any]) -> dict[str, Any]:
    prior = sum(1 for c in body["contents"] if c.get("role") == "model")
    # the API accepts both spellings; LiteLLM sends snake case
    declarations = [
        d
        for tool in body.get("tools") or []
        for d in tool.get("functionDeclarations")
        or tool.get("function_declarations")
        or []
    ]
    turn = _turn(prior, bool(declarations))
    n = prior + 1
    parts: list[dict[str, Any]] = [
        {"text": f"Gemini thought summary for turn {n}.", "thought": True}
    ]
    if turn == "tool":
        name = declarations[0]["name"]
        # Gemini signs only the first of parallel function calls
        parts += [
            {
                "functionCall": {"name": name, "args": TOOL_ARGS},
                "thoughtSignature": _b64(f"stub-gemini-signature-{n}"),
            },
            {"functionCall": {"name": name, "args": {"city": "Rome"}}},
        ]
    else:
        parts.append(
            {
                "text": FIRST_TEXT if turn == "text" else FINAL_TEXT,
                "thoughtSignature": _b64(f"stub-gemini-signature-{n}"),
            }
        )
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": parts},
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": USAGE_TOKENS,
            "candidatesTokenCount": USAGE_TOKENS,
            "thoughtsTokenCount": USAGE_TOKENS,
            "totalTokenCount": 3 * USAGE_TOKENS,
        },
        "modelVersion": "stub-gemini",
    }


# OpenAI Responses -----------------------------------------------------------


def openai_responses_response(body: dict[str, Any]) -> dict[str, Any]:
    items = body["input"] if isinstance(body["input"], list) else []
    prior = sum(
        1
        for item in items
        if item.get("type") == "function_call"
        or (
            item.get("type", "message") == "message" and item.get("role") == "assistant"
        )
    )
    tools = [t for t in body.get("tools") or [] if t.get("type") == "function"]
    turn = _turn(prior, bool(tools))
    n = prior + 1
    reasoning: dict[str, Any] = {
        "type": "reasoning",
        "id": f"rs_stub_{n}",
        "summary": [{"type": "summary_text", "text": f"OpenAI summary for turn {n}."}],
    }
    # like OpenAI, return encrypted reasoning only when asked for
    if "reasoning.encrypted_content" in (body.get("include") or []):
        reasoning["encrypted_content"] = f"stub-openai-encrypted-{n}"
    output: list[dict[str, Any]] = [reasoning]
    if turn == "tool":
        output.append(
            {
                "type": "function_call",
                "id": f"fc_stub_{n}",
                "call_id": f"call_stub_{n}",
                "name": tools[0]["name"],
                "arguments": json.dumps(TOOL_ARGS),
                "status": "completed",
            }
        )
    else:
        output.append(
            {
                "type": "message",
                "id": f"msg_stub_{n}",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": FIRST_TEXT if turn == "text" else FINAL_TEXT,
                        "annotations": [],
                    }
                ],
            }
        )
    return {
        "id": f"resp_stub_{n}",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": body["model"],
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "metadata": {},
        "temperature": 1.0,
        "top_p": 1.0,
        "text": {"format": {"type": "text"}},
        "store": False,
        "truncation": "disabled",
        "usage": {
            "input_tokens": USAGE_TOKENS,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": USAGE_TOKENS,
            "output_tokens_details": {"reasoning_tokens": USAGE_TOKENS},
            "total_tokens": 2 * USAGE_TOKENS,
        },
    }


def openai_responses_sse(response: dict[str, Any]) -> SSE:
    events: list[tuple[str | None, Any]] = []

    def add(kind: str, **data: Any) -> None:
        events.append((kind, {"type": kind, "sequence_number": len(events)} | data))

    add(
        "response.created",
        response=response | {"status": "in_progress", "output": [], "usage": None},
    )
    for index, item in enumerate(response["output"]):
        add("response.output_item.added", output_index=index, item=item)
        add("response.output_item.done", output_index=index, item=item)
    add("response.completed", response=response)
    return SSE(events)


# OpenAI-compatible chat with reasoning_content (the open-model shape) --------


def reasoning_content_chat_response(body: dict[str, Any]) -> dict[str, Any]:
    prior = sum(1 for m in body["messages"] if m["role"] == "assistant")
    tools = body.get("tools") or []
    turn = _turn(prior, bool(tools))
    n = prior + 1
    message: dict[str, Any] = {
        "role": "assistant",
        "content": None,
        "reasoning_content": f"Open model reasoning for turn {n}.",
    }
    if turn == "tool":
        message["tool_calls"] = [
            {
                "id": f"call_stub_{n}",
                "type": "function",
                "function": {
                    "name": tools[0]["function"]["name"],
                    "arguments": json.dumps(TOOL_ARGS),
                },
            }
        ]
    else:
        message["content"] = FIRST_TEXT if turn == "text" else FINAL_TEXT
    return {
        "id": f"chatcmpl-stub-{n}",
        "object": "chat.completion",
        "created": 0,
        "model": body["model"],
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if turn == "tool" else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": USAGE_TOKENS,
            "completion_tokens": USAGE_TOKENS,
            "total_tokens": 2 * USAGE_TOKENS,
        },
    }


def reasoning_content_chat_sse(response: dict[str, Any]) -> SSE:
    message = response["choices"][0]["message"]
    base = {k: response[k] for k in ("id", "created", "model")} | {
        "object": "chat.completion.chunk"
    }

    def chunk(delta: dict[str, Any], finish_reason: str | None = None) -> Any:
        return base | {
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]
        }

    events: list[tuple[str | None, Any]] = [
        (
            None,
            chunk(
                {"role": "assistant", "reasoning_content": message["reasoning_content"]}
            ),
        )
    ]
    for index, call in enumerate(message.get("tool_calls") or []):
        events.append((None, chunk({"tool_calls": [call | {"index": index}]})))
    if message.get("content"):
        events.append((None, chunk({"content": message["content"]})))
    events.append((None, chunk({}, response["choices"][0]["finish_reason"])))
    events.append((None, base | {"choices": [], "usage": response["usage"]}))
    events.append((None, "[DONE]"))
    return SSE(events)


# Bedrock Converse (non-streaming only) ---------------------------------------


def bedrock_converse_response(body: dict[str, Any]) -> dict[str, Any]:
    prior = sum(1 for m in body["messages"] if m["role"] == "assistant")
    tools = (body.get("toolConfig") or {}).get("tools") or []
    turn = _turn(prior, bool(tools))
    n = prior + 1
    content: list[dict[str, Any]] = [
        {
            "reasoningContent": {
                "reasoningText": {
                    "text": f"Bedrock reasoning for turn {n}.",
                    "signature": f"stub-bedrock-signature-{n}",
                }
            }
        }
    ]
    if turn != "final":
        content.append(
            {
                "reasoningContent": {
                    "redactedContent": _b64(f"stub-bedrock-redacted-{n}")
                }
            }
        )
    if turn == "tool":
        content.append(
            {
                "toolUse": {
                    "toolUseId": f"tooluse_stub_{n}",
                    "name": tools[0]["toolSpec"]["name"],
                    "input": TOOL_ARGS,
                }
            }
        )
    else:
        content.append({"text": FIRST_TEXT if turn == "text" else FINAL_TEXT})
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": "tool_use" if turn == "tool" else "end_turn",
        "usage": {
            "inputTokens": USAGE_TOKENS,
            "outputTokens": USAGE_TOKENS,
            "totalTokens": 2 * USAGE_TOKENS,
        },
        "metrics": {"latencyMs": 1},
    }
