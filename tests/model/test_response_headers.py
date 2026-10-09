"""The model layer keeps the headers of each attempt's latest HTTP response."""

import json
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from contextvars import ContextVar
from typing import Any

import anyio
import httpx2
import pytest

import inspect_ai.model._model as model_module
from inspect_ai.model import GenerateConfig, Model, get_model
from inspect_ai.model._response_headers import (
    ResponseHeaders,
    track_response_headers,
)

_ANTHROPIC_EVENTS: list[dict[str, Any]] = [
    {
        "type": "message_start",
        "message": {
            "id": "test",
            "type": "message",
            "role": "assistant",
            "model": "test-model",
            "content": [],
            "stop_reason": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "ok"},
    },
    {"type": "content_block_stop", "index": 0},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": 1},
    },
    {"type": "message_stop"},
]

_OPENAI_COMPLETION = {
    "id": "test",
    "object": "chat.completion",
    "created": 0,
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "ok"},
        }
    ],
}

Reply = Callable[[str], httpx2.Response]


_ANTHROPIC_THINKING: list[dict[str, Any]] = [
    {
        "type": "content_block_start",
        "index": 1,
        "content_block": {"type": "thinking", "thinking": "", "signature": ""},
    },
    {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "thinking_delta", "thinking": "Let me think."},
    },
    {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "signature_delta", "signature": "sig"},
    },
    {"type": "content_block_stop", "index": 1},
]


def _anthropic_reply(served_by: str, thinking: bool = False) -> httpx2.Response:
    # the Anthropic provider streams
    events = _ANTHROPIC_EVENTS
    if thinking:
        events = [*events[:4], *_ANTHROPIC_THINKING, *events[4:]]
    return httpx2.Response(
        200,
        headers={"content-type": "text/event-stream", "X-Served-By": served_by},
        text="".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
        ),
    )


def _openai_reply(served_by: str) -> httpx2.Response:
    return httpx2.Response(
        200, headers={"X-Served-By": served_by}, json=_OPENAI_COMPLETION
    )


def _failure(status: int, served_by: str) -> httpx2.Response:
    return httpx2.Response(
        status,
        headers={"X-Served-By": served_by},
        json={"type": "error", "error": {"type": "api_error", "message": "no"}},
    )


PROVIDERS = pytest.mark.parametrize(
    ("name", "base_url", "reply"),
    [
        ("anthropic/claude-sonnet-4-6", "https://example.com", _anthropic_reply),
        ("openai/gpt-4o", "https://example.com/v1", _openai_reply),
    ],
    ids=["anthropic", "openai"],
)


def _model(
    name: str, base_url: str, *responses: httpx2.Response, max_retries: int = 0
) -> Model:
    script = list(responses)

    async def respond(request: httpx2.Request) -> httpx2.Response:
        await anyio.sleep(0)
        return script.pop(0)

    return get_model(
        name,
        api_key="key",
        base_url=base_url,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
        max_retries=max_retries,
        memoize=False,
    )


_caller: ContextVar[str] = ContextVar("_caller", default="")


@pytest.fixture
def attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[tuple[str, ResponseHeaders]]]:
    """What the model layer keeps for each attempt, in order, with who called."""
    kept: list[tuple[str, ResponseHeaders]] = []

    def tracking(headers: ResponseHeaders) -> AbstractContextManager[None]:
        kept.append((_caller.get(), headers))
        return track_response_headers(headers)

    monkeypatch.setattr(model_module, "track_response_headers", tracking)
    yield kept


def _served_by(headers: ResponseHeaders) -> str | None:
    return (headers.latest or {}).get("x-served-by")


@PROVIDERS
async def test_headers_of_a_reply_are_kept(
    attempts: list[tuple[str, ResponseHeaders]], name: str, base_url: str, reply: Reply
) -> None:
    await _model(name, base_url, reply("gateway-1")).generate("hello")

    assert [_served_by(headers) for _, headers in attempts] == ["gateway-1"]


@PROVIDERS
async def test_headers_of_a_failed_call_are_kept(
    attempts: list[tuple[str, ResponseHeaders]], name: str, base_url: str, reply: Reply
) -> None:
    model = _model(name, base_url, _failure(400, "gateway-1"))

    with pytest.raises(Exception):
        await model.generate("hello", config=GenerateConfig(max_retries=0))

    assert [_served_by(headers) for _, headers in attempts] == ["gateway-1"]


@PROVIDERS
async def test_each_attempt_keeps_only_its_own_headers(
    attempts: list[tuple[str, ResponseHeaders]], name: str, base_url: str, reply: Reply
) -> None:
    model = _model(name, base_url, _failure(503, "first"), reply("second"))

    await model.generate("hello", config=GenerateConfig(max_retries=1))

    assert [_served_by(headers) for _, headers in attempts] == ["first", "second"]


@PROVIDERS
async def test_latest_response_of_an_attempt_wins(
    attempts: list[tuple[str, ResponseHeaders]], name: str, base_url: str, reply: Reply
) -> None:
    # the SDK retries the 503 itself, inside one attempt
    model = _model(
        name, base_url, _failure(503, "first"), reply("second"), max_retries=1
    )

    await model.generate("hello")

    assert [_served_by(headers) for _, headers in attempts] == ["second"]


@PROVIDERS
async def test_concurrent_calls_keep_their_own_headers(
    attempts: list[tuple[str, ResponseHeaders]], name: str, base_url: str, reply: Reply
) -> None:
    async def call(caller: str) -> None:
        _caller.set(caller)
        await _model(name, base_url, reply(caller)).generate("hello")

    async with anyio.create_task_group() as tg:
        for caller in ("a", "b", "c"):
            tg.start_soon(call, caller)

    assert sorted((caller, _served_by(headers)) for caller, headers in attempts) == [
        ("a", "a"),
        ("b", "b"),
        ("c", "c"),
    ]


async def test_side_request_does_not_replace_the_replys_headers(
    attempts: list[tuple[str, ResponseHeaders]],
) -> None:
    # the Anthropic provider counts a thinking block's tokens with a request
    # of its own when the reply doesn't report them
    asked: list[str] = []

    async def respond(request: httpx2.Request) -> httpx2.Response:
        asked.append(request.url.path)
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(
                200, headers={"X-Served-By": "side"}, json={"input_tokens": 3}
            )
        return _anthropic_reply("reply", thinking=True)

    model = get_model(
        "anthropic/claude-sonnet-4-6",
        api_key="key",
        base_url="https://example.com",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
        max_retries=0,
        memoize=False,
    )

    await model.generate("hello")

    assert [path.rsplit("/", 1)[-1] for path in asked] == ["messages", "count_tokens"]
    assert [_served_by(headers) for _, headers in attempts] == ["reply"]
