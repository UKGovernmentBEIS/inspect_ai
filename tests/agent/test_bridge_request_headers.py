"""Tests for `BridgeRequest.headers`: the client's request headers on the host."""

from typing import Any, Awaitable, Callable, Mapping, cast

import httpx2
import pytest
from pydantic import JsonValue

from inspect_ai.agent import BridgeRequest, current_bridge_request
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.context import (
    bridged_request_scope,
    client_request_headers_scope,
    sanitize_client_headers,
)
from inspect_ai.agent._bridge.sandbox.service import (
    generate_anthropic,
    generate_completions,
    generate_responses,
)
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.event._model import ModelEvent
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.model._model import GenerateFilter, use_model_event_sink
from inspect_ai.tool._tools._code_execution import CodeExecutionProviders
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders

# What Claude Code sends on a nested sub-agent's request, plus credentials
_CLIENT_HEADERS = {
    "X-Claude-Code-Agent-Id": "a1b2c3",
    "x-claude-code-parent-agent-id": "p9",
    "x-claude-code-session-id": "s1",
    "x-app": "cli",
    "Authorization": "Bearer sandbox-token",
    "x-api-key": "sandbox-key",
    "Api-Key": "sandbox-key",
    "x-goog-api-key": "sandbox-key",
    "Proxy-Authorization": "Basic abc",
    "Cookie": "a=b",
    "X-Amz-Security-Token": "sandbox-token",
    "x-custom-auth-token": "secret",
    "Ocp-Apim-Subscription-Key": "secret",
}

_EXPOSED = {
    "x-claude-code-agent-id": "a1b2c3",
    "x-claude-code-parent-agent-id": "p9",
    "x-claude-code-session-id": "s1",
    "x-app": "cli",
}


def test_sanitize_lowercases_and_drops_credentials() -> None:
    headers = sanitize_client_headers(_CLIENT_HEADERS)
    assert dict(headers) == _EXPOSED
    with pytest.raises(TypeError):
        cast(dict[str, str], headers)["x-app"] = "other"


def test_sanitize_joins_repeated_names_and_drops_non_strings() -> None:
    headers = sanitize_client_headers({"X-A": "1", "x-a": "2", "x-b": 3, 4: "x"})
    assert dict(headers) == {"x-a": "1, 2"}


@pytest.mark.parametrize("headers", [None, {}, "not-a-mapping"])
def test_sanitize_empty(headers: object) -> None:
    assert dict(sanitize_client_headers(headers)) == {}


def test_bridge_request_headers_default_empty_and_hashable() -> None:
    request = BridgeRequest(model="m")
    assert dict(request.headers) == {}
    hash(request)
    assert request == BridgeRequest(model="m", headers={})


def test_bridge_request_copies_pickles_and_is_read_only() -> None:
    import copy
    import dataclasses
    import pickle

    request = BridgeRequest(model="m", headers={"x-app": "cli"})
    assert copy.deepcopy(request) == request
    assert pickle.loads(pickle.dumps(request)) == request
    assert dataclasses.asdict(request)["headers"] == {"x-app": "cli"}
    with pytest.raises(TypeError):
        cast(dict[str, str], request.headers)["x-app"] = "other"


def test_scope_carries_headers_and_resets() -> None:
    with client_request_headers_scope({"X-App": "cli"}):
        with bridged_request_scope("slug"):
            request = current_bridge_request()
            assert request is not None
            assert dict(request.headers) == {"x-app": "cli"}
    with bridged_request_scope("slug"):
        request = current_bridge_request()
        assert request is not None and dict(request.headers) == {}


# --- sandbox model service --------------------------------------------------


class _CapturingSink:
    """A `ModelEventSink` recording `current_bridge_request()` as it is called."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, BridgeRequest | None]] = []

    def on_pending(self, event: ModelEvent) -> None:
        self.seen.append(("pending", current_bridge_request()))

    def on_complete(self, event: ModelEvent) -> None:
        self.seen.append(("complete", current_bridge_request()))


def _bridge(
    model: Any = "mockllm/model", filter: GenerateFilter | None = None
) -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=filter,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"agent-model": model},
    )


_NO_WEB = cast(WebSearchProviders, None)
_NO_CODE = cast(CodeExecutionProviders, None)

_Generate = Callable[
    [dict[str, JsonValue], dict[str, str] | None], Awaitable[dict[str, JsonValue]]
]

_PROTOCOLS: dict[str, tuple[Callable[[SandboxAgentBridge], _Generate], Any]] = {
    "completions": (
        lambda b: generate_completions(b),
        {"model": "agent-model", "messages": [{"role": "user", "content": "hi"}]},
    ),
    "responses": (
        lambda b: generate_responses(_NO_WEB, _NO_CODE, b),
        {"model": "agent-model", "input": "hi"},
    ),
    "anthropic": (
        lambda b: generate_anthropic(_NO_WEB, _NO_CODE, b),
        {
            "model": "agent-model",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "hi"}],
        },
    ),
}
# Google is left out: the sandbox proxy sends no headers for Gemini requests.


@pytest.mark.anyio
@pytest.mark.parametrize("protocol", list(_PROTOCOLS))
async def test_model_event_sink_sees_client_headers(protocol: str) -> None:
    factory, body = _PROTOCOLS[protocol]
    sink = _CapturingSink()
    with use_model_event_sink(sink):
        await factory(_bridge())(body, dict(_CLIENT_HEADERS))

    assert [phase for phase, _ in sink.seen] == ["pending", "complete"]
    for _, request in sink.seen:
        assert request is not None
        assert request.model == "agent-model"
        assert dict(request.headers) == _EXPOSED
    # nothing leaks past the request
    assert current_bridge_request() is None


@pytest.mark.anyio
async def test_filter_sees_client_headers() -> None:
    seen: list[BridgeRequest | None] = []

    async def capture(*args: Any) -> None:
        seen.append(current_bridge_request())
        return None

    factory, body = _PROTOCOLS["anthropic"]
    await factory(_bridge(filter=capture))(body, dict(_CLIENT_HEADERS))
    [request] = seen
    assert request is not None and dict(request.headers) == _EXPOSED


@pytest.mark.anyio
async def test_sink_sees_no_headers_when_client_sent_none() -> None:
    factory, body = _PROTOCOLS["anthropic"]
    sink = _CapturingSink()
    with use_model_event_sink(sink):
        await factory(_bridge())(body, None)
    for _, request in sink.seen:
        assert request is not None and dict(request.headers) == {}


@pytest.mark.anyio
async def test_exposed_headers_are_not_forwarded_to_provider() -> None:
    """Exposing headers to host code must not widen what the provider receives."""
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-5",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    model = get_model(
        "anthropic/claude-sonnet-4-5",
        api_key="host-key",
        memoize=False,
        streaming=False,
        config=GenerateConfig(max_tokens=64),
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    sink = _CapturingSink()
    try:
        with use_model_event_sink(sink):
            await generate_anthropic(_NO_WEB, _NO_CODE, _bridge(model))(
                _PROTOCOLS["anthropic"][1], dict(_CLIENT_HEADERS)
            )
    finally:
        await model.api.aclose()

    # the sink saw them...
    request_seen = sink.seen[0][1]
    assert request_seen is not None
    assert dict(request_seen.headers) == _EXPOSED
    # ...but the provider did not (none are listed in forward_client_headers)
    [request] = requests
    for name in {name.lower() for name in _CLIENT_HEADERS} - {"x-api-key"}:
        assert name not in request.headers, name
    assert request.headers.get_list("x-api-key") == ["host-key"]


# --- in-process agent_bridge() ----------------------------------------------


@pytest.mark.anyio
async def test_in_process_bridge_exposes_extra_headers() -> None:
    from openai import AsyncOpenAI

    from inspect_ai.agent import agent_bridge

    sink = _CapturingSink()
    async with agent_bridge(AgentState(messages=[]), model_event_sink=sink):
        async with AsyncOpenAI(
            api_key="unused", base_url="http://localhost:1/v1"
        ) as client:
            await client.chat.completions.create(
                model="inspect/mockllm/model",
                messages=[{"role": "user", "content": "hi"}],
                extra_headers={"X-Agent-Id": "sub-1", "Authorization": "Bearer x"},
            )

    assert sink.seen
    for _, request in sink.seen:
        assert request is not None
        headers: Mapping[str, str] = request.headers
        assert headers.get("x-agent-id") == "sub-1"
        assert "authorization" not in headers


def test_sanitize_catches_credential_variants() -> None:
    headers = sanitize_client_headers(
        {
            "x_api_key": "s",
            "x-access-key-id": "a",
            "x-hmac-signature": "sig",
            "x-custom": "Bearer abc",
            "x-other": "sk-ant-123",
            "x-joined": "v, Bearer abc",
            "x-tab": "Bearer\tabc",
            "x-token": "Token abc",
            "x-session-id": "ok",
        }
    )
    assert dict(headers) == {"x-session-id": "ok"}


@pytest.mark.anyio
async def test_headers_survive_refusal_retry_and_spawned_tasks() -> None:
    import anyio

    from inspect_ai.model import ModelOutput

    seen: list[BridgeRequest | None] = []
    calls = 0

    async def filter(*args: Any) -> ModelOutput | None:
        nonlocal calls
        calls += 1
        seen.append(current_bridge_request())

        async def child() -> None:
            seen.append(current_bridge_request())

        async with anyio.create_task_group() as tg:
            tg.start_soon(child)
        if calls == 1:
            return ModelOutput.from_content("m", "no", stop_reason="content_filter")
        return None

    bridge = _bridge(filter=filter)
    bridge.retry_refusals = 2
    factory, body = _PROTOCOLS["anthropic"]
    await factory(bridge)(body, {"x-claude-code-agent-id": "A"})
    assert len(seen) == 4
    for request in seen:
        assert request is not None
        assert request.headers.get("x-claude-code-agent-id") == "A"


@pytest.mark.anyio
async def test_concurrent_requests_see_their_own_headers() -> None:
    import anyio

    seen: dict[str, str] = {}

    async def filter(*args: Any) -> None:
        before = current_bridge_request()
        await anyio.sleep(0.02)
        after = current_bridge_request()
        assert before is not None and after is not None
        seen[before.headers["x-id"]] = after.headers["x-id"]
        return None

    factory, body = _PROTOCOLS["anthropic"]
    generate = factory(_bridge(filter=filter))

    async def run(i: int) -> None:
        await generate(body, {"x-id": str(i)})

    async with anyio.create_task_group() as tg:
        for i in range(5):
            tg.start_soon(run, i)
    assert seen == {str(i): str(i) for i in range(5)}


@pytest.mark.anyio
async def test_in_process_anthropic_exposes_extra_headers() -> None:
    from anthropic import AsyncAnthropic

    from inspect_ai.agent import agent_bridge

    sink = _CapturingSink()
    async with agent_bridge(AgentState(messages=[]), model_event_sink=sink):
        async with AsyncAnthropic(api_key="unused", base_url="http://localhost:1") as c:
            await c.messages.create(
                model="inspect/mockllm/model",
                max_tokens=16,
                messages=[{"role": "user", "content": "hi"}],
                extra_headers={"X-Agent-Id": "s2", "X-Api-Key": "k"},
            )
    assert sink.seen
    for _, request in sink.seen:
        assert request is not None
        assert request.headers.get("x-agent-id") == "s2"
        assert "x-api-key" not in request.headers


@pytest.mark.anyio
async def test_nested_bridged_request_does_not_inherit_outer_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A filter running an in-process Gemini agent (no headers of its own)."""
    monkeypatch.setenv("INSPECT_EVAL_MODEL", "mockllm/model")
    from google import genai

    from inspect_ai.agent import agent_bridge

    inner = _CapturingSink()

    async def outer_filter(*args: Any) -> None:
        async with agent_bridge(AgentState(messages=[]), model_event_sink=inner):
            await genai.Client(api_key="inspect").aio.models.generate_content(
                model="inspect", contents="hi"
            )
        return None

    factory, body = _PROTOCOLS["anthropic"]
    await factory(_bridge(filter=outer_filter))(
        body, {"x-claude-code-agent-id": "OUTER"}
    )
    assert inner.seen
    for _, request in inner.seen:
        assert request is not None
        assert dict(request.headers) == {}


@pytest.mark.anyio
async def test_in_process_responses_exposes_extra_headers() -> None:
    from openai import AsyncOpenAI

    from inspect_ai.agent import agent_bridge

    sink = _CapturingSink()
    async with agent_bridge(AgentState(messages=[]), model_event_sink=sink):
        async with AsyncOpenAI(
            api_key="unused", base_url="http://localhost:1/v1"
        ) as client:
            await client.responses.create(
                model="inspect/mockllm/model",
                input="hi",
                extra_headers={"X-Agent-Id": "r1"},
            )
    assert sink.seen
    for _, request in sink.seen:
        assert request is not None and request.headers.get("x-agent-id") == "r1"


def test_scopes_reset_on_exception() -> None:
    with pytest.raises(RuntimeError):
        with client_request_headers_scope({"x-app": "cli"}):
            with bridged_request_scope("slug"):
                raise RuntimeError("boom")
    assert current_bridge_request() is None
    with bridged_request_scope("slug"):
        request = current_bridge_request()
        assert request is not None and dict(request.headers) == {}
