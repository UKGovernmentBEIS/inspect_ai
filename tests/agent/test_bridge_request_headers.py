"""Tests for `BridgeRequest.headers`: the client's request headers on the host."""

import copy
import dataclasses
import json
import pickle
from typing import Any, Awaitable, Callable, Sequence, cast

import httpx2
import pytest
from pydantic import JsonValue, TypeAdapter

from inspect_ai.agent import BridgeRequest, current_bridge_request
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.bridge import resolve_expose_client_headers
from inspect_ai.agent._bridge.context import (
    bridged_request_scope,
    client_request_headers_scope,
)
from inspect_ai.agent._bridge.sandbox.service import (
    generate_anthropic,
    generate_completions,
    generate_responses,
)
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.event._info import InfoEvent
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
    "CF-Access-Jwt-Assertion": "eyJhbGciOiJSUzI1NiJ9.payload.signature",
}

_EXPOSE = ["x-claude-code-agent-id", "X-Claude-Code-Parent-Agent-Id"]

_EXPOSED = {
    "x-claude-code-agent-id": "a1b2c3",
    "x-claude-code-parent-agent-id": "p9",
}

_NAMES = resolve_expose_client_headers(_EXPOSE)


def _exposed(headers: object, names: frozenset[str] = _NAMES) -> dict[str, str]:
    with client_request_headers_scope(headers, names):
        with bridged_request_scope("slug"):
            request = current_bridge_request()
            assert request is not None
            return request.headers


def test_exposes_only_listed_headers() -> None:
    assert _exposed(_CLIENT_HEADERS) == _EXPOSED


def test_exposes_nothing_by_default() -> None:
    assert resolve_expose_client_headers(None) == frozenset()
    assert _exposed(_CLIENT_HEADERS, frozenset()) == {}


def test_joins_repeated_names_and_drops_non_strings() -> None:
    names = frozenset({"x-a", "x-b"})
    assert _exposed({"X-A": "1", "x-a": "2", "x-b": 3, 4: "x"}, names) == {
        "x-a": "1, 2"
    }


@pytest.mark.parametrize("headers", [None, {}, "not-a-mapping"])
def test_no_headers(headers: object) -> None:
    assert _exposed(headers) == {}


def test_resolve_normalizes_names() -> None:
    assert resolve_expose_client_headers([" X-Agent-Id ", "x-agent-id"]) == {
        "x-agent-id"
    }


@pytest.mark.parametrize("value", ["x-agent-id", ["x-agent-id", 1], {"x-agent-id"}])
def test_resolve_rejects_non_lists(value: Any) -> None:
    with pytest.raises(TypeError):
        resolve_expose_client_headers(value)


@pytest.mark.parametrize(
    "name", ["Authorization", "x-api-key", "Cookie", "X-Amz-Security-Token"]
)
def test_resolve_refuses_credential_headers(name: str) -> None:
    with pytest.raises(ValueError, match="credentials"):
        resolve_expose_client_headers([name])


def test_bridge_request_headers_default_empty_and_hashable() -> None:
    request = BridgeRequest(model="m")
    assert request.headers == {}
    hash(request)
    assert request == BridgeRequest(model="m", headers={})


@pytest.mark.parametrize("headers", [{}, {"x-agent-id": "a1"}])
def test_bridge_request_serializes(headers: dict[str, str]) -> None:
    request = BridgeRequest(model="m", headers=headers)
    expected = {"model": "m", "headers": headers}
    assert json.loads(json.dumps(dataclasses.asdict(request))) == expected
    assert json.loads(TypeAdapter(BridgeRequest).dump_json(request)) == expected
    event = InfoEvent(data=dataclasses.asdict(request))
    assert json.loads(event.model_dump_json())["data"] == expected
    assert copy.deepcopy(request) == request
    assert pickle.loads(pickle.dumps(request)) == request


def test_scope_carries_headers_and_resets() -> None:
    assert _exposed({"X-Agent-Id": "a"}, frozenset({"x-agent-id"})) == {
        "x-agent-id": "a"
    }
    with bridged_request_scope("slug"):
        request = current_bridge_request()
        assert request is not None and request.headers == {}


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
    model: Any = "mockllm/model",
    filter: GenerateFilter | None = None,
    expose: Sequence[str] | None = _EXPOSE,
    forward: dict[str, list[str]] | None = None,
) -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=filter,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"agent-model": model},
        expose_client_headers=expose,
        forward_client_headers=forward,
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
        assert request.headers == _EXPOSED
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
    assert request is not None and request.headers == _EXPOSED


@pytest.mark.anyio
async def test_sink_sees_no_headers_when_client_sent_none() -> None:
    factory, body = _PROTOCOLS["anthropic"]
    sink = _CapturingSink()
    with use_model_event_sink(sink):
        await factory(_bridge())(body, None)
    for _, request in sink.seen:
        assert request is not None and request.headers == {}


@pytest.mark.anyio
async def test_exposed_headers_are_not_forwarded_to_provider() -> None:
    """Exposing a header doesn't forward it; `forward_client_headers` still applies."""
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
            bridge = _bridge(
                model, expose=[*_EXPOSE, "x-app"], forward={"x-app": ["cli"]}
            )
            await generate_anthropic(_NO_WEB, _NO_CODE, bridge)(
                _PROTOCOLS["anthropic"][1], dict(_CLIENT_HEADERS)
            )
    finally:
        await model.api.aclose()

    # the sink saw the exposed headers...
    request_seen = sink.seen[0][1]
    assert request_seen is not None
    assert request_seen.headers == {**_EXPOSED, "x-app": "cli"}
    # ...but the provider got only the forwarded one
    [request] = requests
    assert request.headers.get("x-app") == "cli"
    host_auth = {"x-api-key", "authorization", "x-app"}
    for name in {name.lower() for name in _CLIENT_HEADERS} - host_auth:
        assert name not in request.headers, name
    # the host's key, as x-api-key or (anthropic >= 2) a bearer token, and
    # never the client's value
    assert request.headers.get_list("x-api-key") in ([], ["host-key"])
    assert request.headers.get_list("authorization") in ([], ["Bearer host-key"])
    assert {"x-api-key", "authorization"} & set(request.headers.keys())


# --- in-process agent_bridge() ----------------------------------------------


@pytest.mark.anyio
async def test_in_process_bridge_exposes_extra_headers() -> None:
    from openai import AsyncOpenAI

    from inspect_ai.agent import agent_bridge

    sink = _CapturingSink()
    async with agent_bridge(
        AgentState(messages=[]),
        model_event_sink=sink,
        expose_client_headers=["X-Agent-Id"],
    ):
        async with AsyncOpenAI(
            api_key="unused", base_url="http://localhost:1/v1"
        ) as client:
            await client.chat.completions.create(
                model="inspect/mockllm/model",
                messages=[{"role": "user", "content": "hi"}],
                extra_headers={"X-Agent-Id": "sub-1", "X-Other": "o"},
            )

    assert sink.seen
    for _, request in sink.seen:
        assert request is not None and request.headers == {"x-agent-id": "sub-1"}


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
    generate = factory(_bridge(filter=filter, expose=["x-id"]))

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
    async with agent_bridge(
        AgentState(messages=[]),
        model_event_sink=sink,
        expose_client_headers=["x-agent-id"],
    ):
        async with AsyncAnthropic(api_key="unused", base_url="http://localhost:1") as c:
            await c.messages.create(
                model="inspect/mockllm/model",
                max_tokens=16,
                messages=[{"role": "user", "content": "hi"}],
                extra_headers={"X-Agent-Id": "s2", "X-Other": "o"},
            )
    assert sink.seen
    for _, request in sink.seen:
        assert request is not None and request.headers == {"x-agent-id": "s2"}


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
        async with agent_bridge(
            AgentState(messages=[]),
            model_event_sink=inner,
            expose_client_headers=["x-claude-code-agent-id"],
        ):
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
        assert request.headers == {}


@pytest.mark.anyio
async def test_in_process_responses_exposes_extra_headers() -> None:
    from openai import AsyncOpenAI

    from inspect_ai.agent import agent_bridge

    sink = _CapturingSink()
    async with agent_bridge(
        AgentState(messages=[]),
        model_event_sink=sink,
        expose_client_headers=["x-agent-id"],
    ):
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
        with client_request_headers_scope({"x-app": "cli"}, frozenset({"x-app"})):
            with bridged_request_scope("slug"):
                raise RuntimeError("boom")
    assert current_bridge_request() is None
    with bridged_request_scope("slug"):
        request = current_bridge_request()
        assert request is not None and request.headers == {}
