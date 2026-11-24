"""The model layer keeps the headers of each attempt's latest HTTP response."""

import json
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractContextManager
from contextvars import ContextVar
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anyio
import httpx
import httpx2
import pytest

import inspect_ai.model._model as model_module
from inspect_ai._util._async import current_async_backend
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


def _mistral_reply(served_by: str) -> httpx2.Response:
    return httpx2.Response(
        200,
        headers={"X-Served-By": served_by},
        json={
            "object": "conversation.response",
            "conversation_id": "conv_test",
            "outputs": [
                {
                    "object": "entry",
                    "type": "message.output",
                    "id": "msg_test",
                    "role": "assistant",
                    "content": "ok",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def _openai_background(status: str, served_by: str) -> httpx2.Response:
    output = [
        {
            "type": "message",
            "id": "msg_test",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "ok", "annotations": []}],
        }
    ]
    return httpx2.Response(
        200,
        headers={"X-Served-By": served_by},
        json={
            "id": "resp_test",
            "object": "response",
            "created_at": 0,
            "status": status,
            "model": "test-model",
            "output": output if status == "completed" else [],
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
        },
    )


class _CutShort(httpx2.AsyncByteStream):
    """A body the connection closes part-way through."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"id": "te'
        raise httpx2.ReadError("the connection closed part-way through the body")


class _CutShortHttpx(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"id": "te'
        raise httpx.ReadError("the connection closed part-way through the body")


def _cut_short_reply(served_by: str) -> httpx2.Response:
    return httpx2.Response(200, headers={"X-Served-By": served_by}, stream=_CutShort())


def _failure(status: int, served_by: str) -> httpx2.Response:
    return httpx2.Response(
        status,
        # an SDK that retries waits only as long as it is told to
        headers={"X-Served-By": served_by, "Retry-After-Ms": "1"},
        json={"type": "error", "error": {"type": "api_error", "message": "no"}},
    )


_PROVIDERS = {
    "anthropic": (
        "anthropic/claude-sonnet-4-6",
        "https://example.com",
        _anthropic_reply,
    ),
    "openai": ("openai/gpt-4o", "https://example.com/v1", _openai_reply),
    "openai-compatible": (
        "openai-api/example/test-model",
        "https://example.com/v1",
        _openai_reply,
    ),
    "groq": ("groq/test-model", "https://example.com", _openai_reply),
    "mistral": ("mistral/test-model", "https://example.com", _mistral_reply),
}


def _providers(*ids: str) -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        ("name", "base_url", "reply"), [_PROVIDERS[id] for id in ids], ids=ids
    )


PROVIDERS = _providers(*_PROVIDERS)

# the Mistral SDK doesn't retry a response unless it is configured to
SDK_RETRYING_PROVIDERS = _providers("anthropic", "openai", "openai-compatible", "groq")

# the Groq provider returns a status error instead of raising it, and the model
# layer then doesn't make a second attempt
RETRIED_PROVIDERS = _providers("anthropic", "openai", "openai-compatible", "mistral")

# statuses the SDKs retry themselves
SDK_RETRIED = pytest.mark.parametrize("status", [429, 503])


def _model(
    name: str,
    base_url: str,
    *responses: httpx2.Response | Exception,
    max_retries: int = 0,
    response_hook: Callable[[Any], Any] | None = None,
    **model_args: Any,
) -> Model:
    script = list(responses)
    # a hook of the caller's own, already on the client it hands over
    caller_hooks = {"response": [response_hook]} if response_hook else None

    async def respond(request: httpx2.Request) -> httpx2.Response:
        await anyio.sleep(0)
        response = script.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def respond_httpx(request: httpx.Request) -> httpx.Response:
        await anyio.sleep(0)
        response = script.pop(0)
        if isinstance(response, Exception):
            raise httpx.ConnectError(str(response))
        if isinstance(response.stream, _CutShort):
            return httpx.Response(
                response.status_code,
                headers=dict(response.headers),
                stream=_CutShortHttpx(),
            )
        return httpx.Response(
            response.status_code,
            headers=dict(response.headers),
            content=response.content,
        )

    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(respond), event_hooks=caller_hooks
    )
    client_args: dict[str, Any]
    if name.startswith("groq/"):
        # the Groq SDK is built on httpx, the others on httpx2
        client_args = {
            "http_client": httpx.AsyncClient(
                transport=httpx.MockTransport(respond_httpx),
                event_hooks=caller_hooks,
            ),
            "max_retries": max_retries,
        }
    elif name.startswith("mistral/"):
        if current_async_backend() == "trio":
            pytest.skip("the Mistral SDK needs an asyncio event loop")
        client_args = {"async_client": client}
    else:
        client_args = {"http_client": client, "max_retries": max_retries}

    return get_model(
        name,
        api_key="key",
        base_url=base_url,
        memoize=False,
        **client_args,
        **model_args,
    )


def _background_model(*responses: httpx2.Response, max_retries: int = 0) -> Model:
    return _model(
        "openai/gpt-4o",
        "https://example.com/v1",
        *responses,
        max_retries=max_retries,
        responses_api=True,
        background=True,
    )


@pytest.fixture
def no_polling_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "inspect_ai.model._providers.openai_responses.anyio.sleep", AsyncMock()
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


@RETRIED_PROVIDERS
async def test_each_attempt_keeps_only_its_own_headers(
    attempts: list[tuple[str, ResponseHeaders]], name: str, base_url: str, reply: Reply
) -> None:
    model = _model(name, base_url, _failure(503, "first"), reply("second"))

    await model.generate("hello", config=GenerateConfig(max_retries=1))

    assert [_served_by(headers) for _, headers in attempts] == ["first", "second"]


@SDK_RETRYING_PROVIDERS
@SDK_RETRIED
async def test_latest_response_of_an_attempt_wins(
    attempts: list[tuple[str, ResponseHeaders]],
    name: str,
    base_url: str,
    reply: Reply,
    status: int,
) -> None:
    # the SDK retries the failure itself, inside one attempt
    model = _model(
        name, base_url, _failure(status, "first"), reply("second"), max_retries=1
    )

    await model.generate("hello")

    assert [_served_by(headers) for _, headers in attempts] == ["second"]


@SDK_RETRYING_PROVIDERS
@SDK_RETRIED
async def test_latest_response_is_kept_when_the_sdks_retry_gets_none(
    attempts: list[tuple[str, ResponseHeaders]],
    name: str,
    base_url: str,
    reply: Reply,
    status: int,
) -> None:
    model = _model(
        name,
        base_url,
        _failure(status, "first"),
        httpx2.ConnectError("no route"),
        max_retries=1,
    )

    with pytest.raises(Exception, match="APIConnectionError"):
        await model.generate("hello", config=GenerateConfig(max_retries=0))

    assert [_served_by(headers) for _, headers in attempts] == ["first"]


# a caller can hand over a client with hooks of its own, which run in the order
# they were added and may read the body or raise
@PROVIDERS
async def test_headers_are_kept_when_the_callers_own_hook_raises(
    attempts: list[tuple[str, ResponseHeaders]], name: str, base_url: str, reply: Reply
) -> None:
    async def raising(response: Any) -> None:
        raise RuntimeError("the caller's hook")

    model = _model(name, base_url, reply("gateway-1"), response_hook=raising)

    with pytest.raises(Exception):
        await model.generate("hello", config=GenerateConfig(max_retries=0))

    assert [_served_by(headers) for _, headers in attempts] == ["gateway-1"]


@PROVIDERS
async def test_headers_are_kept_when_the_callers_own_hook_cannot_read_the_body(
    attempts: list[tuple[str, ResponseHeaders]], name: str, base_url: str, reply: Reply
) -> None:
    async def reading(response: Any) -> None:
        await response.aread()

    model = _model(name, base_url, _cut_short_reply("gateway-1"), response_hook=reading)

    with pytest.raises(Exception):
        await model.generate("hello", config=GenerateConfig(max_retries=0))

    assert [_served_by(headers) for _, headers in attempts] == ["gateway-1"]


@PROVIDERS
async def test_concurrent_calls_keep_their_own_headers(
    attempts: list[tuple[str, ResponseHeaders]], name: str, base_url: str, reply: Reply
) -> None:
    # built here rather than in the tasks, so that a skip isn't wrapped in the
    # task group's exception group
    models = {caller: _model(name, base_url, reply(caller)) for caller in "abc"}

    async def call(caller: str) -> None:
        _caller.set(caller)
        await models[caller].generate("hello")

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


async def test_background_call_keeps_the_headers_of_the_poll_that_completed_it(
    attempts: list[tuple[str, ResponseHeaders]],
    no_polling_delay: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_http_retry = MagicMock()
    monkeypatch.setattr(
        "inspect_ai.model._providers.util.hooks.report_http_retry", report_http_retry
    )
    model = _background_model(
        _openai_background("queued", "submit"),
        _openai_background("in_progress", "poll-1"),
        _openai_background("completed", "poll-2"),
    )

    output = await model.generate("hello")

    assert output.completion == "ok"
    assert [_served_by(headers) for _, headers in attempts] == ["poll-2"]
    # a poll is not a retry
    report_http_retry.assert_not_called()


async def test_background_call_keeps_the_headers_of_the_poll_that_failed_it(
    attempts: list[tuple[str, ResponseHeaders]], no_polling_delay: None
) -> None:
    model = _background_model(
        _openai_background("queued", "submit"), _failure(500, "poll")
    )

    with pytest.raises(Exception):
        await model.generate("hello", config=GenerateConfig(max_retries=0))

    assert [_served_by(headers) for _, headers in attempts] == ["poll"]


@SDK_RETRIED
async def test_background_call_keeps_the_headers_of_the_poll_an_sdk_retry_completed(
    attempts: list[tuple[str, ResponseHeaders]],
    no_polling_delay: None,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    report_http_retry = MagicMock()
    monkeypatch.setattr(
        "inspect_ai.model._providers.util.hooks.report_http_retry", report_http_retry
    )
    model = _background_model(
        _openai_background("queued", "submit"),
        _failure(status, "poll-1"),
        _openai_background("completed", "poll-2"),
        max_retries=1,
    )

    output = await model.generate("hello")

    assert output.completion == "ok"
    assert [_served_by(headers) for _, headers in attempts] == ["poll-2"]
    # a poll is not a retry, nor is the SDK's retry of one
    report_http_retry.assert_not_called()


@SDK_RETRIED
async def test_background_call_keeps_the_headers_of_a_poll_the_sdk_retried(
    attempts: list[tuple[str, ResponseHeaders]],
    no_polling_delay: None,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    report_http_retry = MagicMock()
    monkeypatch.setattr(
        "inspect_ai.model._providers.util.hooks.report_http_retry", report_http_retry
    )
    # the SDK retries the poll's failure itself, and never gets another response
    script = [_openai_background("queued", "submit"), _failure(status, "poll")]

    async def respond(request: httpx2.Request) -> httpx2.Response:
        await anyio.sleep(0)
        if not script:
            raise httpx2.ConnectError("no route", request=request)
        return script.pop(0)

    model = get_model(
        "openai/gpt-4o",
        api_key="key",
        base_url="https://example.com/v1",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
        max_retries=1,
        memoize=False,
        responses_api=True,
        background=True,
    )

    with pytest.raises(Exception, match="APIConnectionError"):
        await model.generate("hello", config=GenerateConfig(max_retries=0))

    assert [_served_by(headers) for _, headers in attempts] == ["poll"]
    # a poll is not a retry, nor is the SDK's retry of one
    report_http_retry.assert_not_called()


async def test_background_call_cancelled_in_the_sdks_backoff_keeps_the_polls_headers(
    attempts: list[tuple[str, ResponseHeaders]], monkeypatch: pytest.MonkeyPatch
) -> None:
    retry_after = 30
    backing_off = anyio.Event()

    async def sleep(delay: float) -> None:
        # the SDK waits out the 429's Retry-After before it retries the poll
        if delay == retry_after:
            backing_off.set()
            await anyio.sleep_forever()

    monkeypatch.setattr(
        "inspect_ai.model._providers.openai_responses.anyio.sleep", sleep
    )
    script = [
        _openai_background("queued", "submit"),
        httpx2.Response(
            429,
            headers={"X-Served-By": "poll", "Retry-After": str(retry_after)},
            json={"error": {"type": "rate_limit_error", "message": "slow down"}},
        ),
        _openai_background("cancelled", "cancel"),
    ]
    asked: list[str] = []

    async def respond(request: httpx2.Request) -> httpx2.Response:
        asked.append(f"{request.method} {request.url.path}")
        return script.pop(0)

    model = get_model(
        "openai/gpt-4o",
        api_key="key",
        base_url="https://example.com/v1",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
        max_retries=1,
        memoize=False,
        responses_api=True,
        background=True,
    )

    async with anyio.create_task_group() as tg:
        tg.start_soon(model.generate, "hello")
        # fail, don't hang, if the SDK stops waiting the way this test expects
        with anyio.fail_after(10):
            await backing_off.wait()
        tg.cancel_scope.cancel()

    # the provider tells OpenAI to stop the work; that reply is not the call's
    assert asked == [
        "POST /v1/responses",
        "GET /v1/responses/resp_test",
        "POST /v1/responses/resp_test/cancel",
    ]
    assert [_served_by(headers) for _, headers in attempts] == ["poll"]
