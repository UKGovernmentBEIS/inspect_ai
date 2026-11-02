"""Host-side tests for agent-bridge provider-error forwarding.

Covers the pieces that let the sandbox model proxy forward a provider error
instead of crashing: the `ModelGenerateError` wrapper (which preserves the
provider HTTP status), the `status_code_of` / `provider_error_payload`
extractors, and the `service.py` wrapper that turns an exception into a
`PROVIDER_ERROR_KEY` result.
"""

from __future__ import annotations

import ast
import gc
import weakref
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, NamedTuple, cast
from unittest.mock import AsyncMock

import anyio
import httpx2
import pytest
from anthropic import APIStatusError
from pydantic import JsonValue
from test_helpers.service_dispatch import (
    REQUEST_FILE,
    REQUEST_ID,
    dispatching_service,
)

import inspect_ai
from inspect_ai import Task, eval
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.http import status_code_of
from inspect_ai._util.registry import _registry
from inspect_ai.agent import Agent, agent, run
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge import bridge as bridge_module
from inspect_ai.agent._bridge._errors import (
    PROVIDER_ERROR_KEY,
    ResponseFilterError,
    provider_error_payload,
)
from inspect_ai.agent._bridge.sandbox import bridge as sandbox_bridge_module
from inspect_ai.agent._bridge.sandbox import service as bridge_service
from inspect_ai.agent._bridge.sandbox.bridge import sandbox_agent_bridge
from inspect_ai.agent._bridge.sandbox.service import _forward_provider_errors
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalSample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    ModelUsage,
    get_model,
)
from inspect_ai.model._model import (
    GenerateInput,
    Model,
    ModelAPI,
    ModelGenerateError,
    ModelGenerateFilter,
    ModelRefusalError,
    ModelResponseFilter,
)
from inspect_ai.model._model_data.model_data import ModelCost, ModelInfo
from inspect_ai.model._model_info import clear_model_info_cache, set_model_info
from inspect_ai.model._providers.anthropic import (
    _ANTHROPIC_ERROR_TYPE_STATUS,
    AnthropicAPI,
    _normalize_stream_error,
    _UnclassifiedStreamError,
)
from inspect_ai.model._registry import modelapi
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.tool._tools._code_execution import CodeExecutionProviders
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders
from inspect_ai.util import (
    cost_limit,
    message_limit,
    time_limit,
    token_limit,
    turn_limit,
)
from inspect_ai.util._limit import Limit, LimitExceededError
from inspect_ai.util._sandbox.service import SandboxService, find_control_flow


class _ProviderError(Exception):
    """Stand-in for an SDK exception exposing a `.status_code`."""

    def __init__(self, message: str, status_code: int | None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------- status_code_of ----------


def test_status_code_of_reads_status_code_attr() -> None:
    assert status_code_of(_ProviderError("rate limited", 429)) == 429


def test_status_code_of_reads_code_attr() -> None:
    # google-genai APIError exposes the HTTP status as `.code`
    class _GoogleError(Exception):
        code = 503

    assert status_code_of(_GoogleError()) == 503


def test_status_code_of_reads_model_generate_error() -> None:
    ex = ModelGenerateError("debug", status_code=400)
    assert status_code_of(ex) == 400


def test_status_code_of_returns_none_when_absent() -> None:
    assert status_code_of(ValueError("boom")) is None
    # non-int attrs are ignored
    assert status_code_of(_ProviderError("x", 0)) == 0  # falsy-but-valid status


def _anthropic_stream_error(error_type: str, message: str) -> APIStatusError:
    """Build the SDK's generic exception for an SSE error event."""
    return APIStatusError(
        message,
        response=httpx2.Response(
            status_code=200,
            request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
        ),
        body={"type": "error", "error": {"type": error_type, "message": message}},
    )


def test_status_code_of_preserves_declared_stream_response_status() -> None:
    """Generic HTTP extraction must not interpret provider-specific error bodies."""
    assert (
        status_code_of(
            _anthropic_stream_error("invalid_request_error", "provider said 400")
        )
        == 200
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error_type", "status", "retry"),
    [
        ("invalid_request_error", 400, False),
        ("billing_error", 402, False),
        ("conflict_error", 409, False),
        ("rate_limit_error", 429, True),
        ("timeout_error", 504, True),
        ("overloaded_error", 529, True),
        # a type the provider cannot classify: reported as a 500, not retried
        ("some_future_error", 500, False),
    ],
)
async def test_anthropic_stream_error_is_normalized_for_retry(
    monkeypatch: pytest.MonkeyPatch, error_type: str, status: int, retry: bool
) -> None:
    """SSE errors must use their actual status before retry classification."""
    message = f"provider said {status}"
    api = AnthropicAPI(model_name="claude-test", api_key="test-key")

    async def fail_request(*args: object, **kwargs: object) -> object:
        raise _anthropic_stream_error(error_type, message)

    monkeypatch.setattr(api, "_perform_request_and_continuations", fail_request)

    with pytest.raises(APIStatusError) as exc_info:
        await api.generate(
            input=[ChatMessageUser(content="hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(max_tokens=8),
        )

    assert exc_info.value.status_code == status
    assert exc_info.value.message == message
    assert isinstance(exc_info.value, _UnclassifiedStreamError) is (
        error_type not in _ANTHROPIC_ERROR_TYPE_STATUS
    )
    assert bool(api.should_retry(exc_info.value)) is retry


def _dict_literal(source: Path, name: str) -> dict[int, str]:
    """Read the module-level `{int: str}` literal named `name` in `source`."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if name in targets:
            literal = ast.literal_eval(node.value)
            assert isinstance(literal, dict), f"{name} in {source} is not a dict"
            return {int(status): str(kind) for status, kind in literal.items()}
    raise AssertionError(
        f"{name} not found in {source}; the table was renamed or moved"
    )


def test_every_recognized_error_type_survives_the_proxy_round_trip() -> None:
    """An error type the provider decodes must come back out of the proxy unchanged.

    `_normalize_stream_error` turns a mid-stream provider error body into an HTTP
    status, and the proxy turns that status back into an Anthropic error body. On
    the streaming route the status is already 200 by the time the error is known,
    so the error `type` in that body is the client's only machine-readable signal:
    a type the host recognizes but the proxy cannot invert degrades to `api_error`,
    reclassifying a client error (a 409 conflict) as a server one.

    The proxy ships in `inspect_sandbox_tools`, a separate distribution that
    deliberately does not depend on `inspect_ai`, so neither side can import the
    other's table. Reading its literal is therefore the only way to hold the two
    halves together in one assertion, and it is worth holding: iterating the
    provider's own table means the next status added there fails here until the
    proxy learns it.
    """
    proxy_source = (
        Path(inspect_ai.__file__).parents[1]
        / "inspect_sandbox_tools"
        / "src"
        / "inspect_sandbox_tools"
        / "_agent_bridge"
        / "proxy.py"
    )
    if not proxy_source.is_file():
        pytest.skip(
            f"no sibling inspect_sandbox_tools source at {proxy_source} (not a "
            "src-layout checkout)"
        )
    proxy_types = _dict_literal(proxy_source, "_ANTHROPIC_ERROR_TYPES")

    lost: dict[str, str] = {}
    for error_type, status in _ANTHROPIC_ERROR_TYPE_STATUS.items():
        ex = _normalize_stream_error(_anthropic_stream_error(error_type, "x"))
        assert not isinstance(ex, _UnclassifiedStreamError), error_type
        derived = status_code_of(ex)
        assert derived == status, f"{error_type} derived {derived}, expected {status}"
        returned = proxy_types.get(derived, "api_error")
        if returned != error_type:
            lost[error_type] = returned

    assert lost == {}, (
        "these error types do not survive the round trip through the proxy, so a "
        f"streaming client sees the wrong classification: {lost}"
    )

    # And the other direction: a status the proxy can name must be one the
    # provider derives, or the proxy carries a classification nothing produces
    # and a type dropped from the provider table goes unnoticed above.
    unproduced = {
        status: kind
        for status, kind in proxy_types.items()
        if kind not in _ANTHROPIC_ERROR_TYPE_STATUS
        or _ANTHROPIC_ERROR_TYPE_STATUS[kind] != status
    }
    assert unproduced == {}, (
        "the proxy names these statuses but the provider table does not derive "
        f"them, so the two tables have drifted: {unproduced}"
    )


def test_unknown_stream_error_type_is_a_server_error_not_a_success() -> None:
    # An SSE error event whose type this provider does not know is still an
    # error the provider reported. It must not keep the stream's 200: the bridge
    # would forward it as a success and a client would read the envelope as a
    # (malformed) reply instead of raising. The 500 is for reporting only: an
    # error nobody classified is not known to be transient, so it is not
    # retried (before normalization it kept the 200 and was not retried either).
    api = AnthropicAPI(model_name="claude-test", api_key="test-key")
    raw = _anthropic_stream_error("some_future_error", "provider said no")
    ex = _normalize_stream_error(raw)
    assert isinstance(ex, _UnclassifiedStreamError)
    assert ex.status_code == 500
    assert ex.message == "provider said no"
    assert provider_error_payload(ex)["status"] == 500
    assert bool(api.should_retry(ex)) is False
    # the SDK's own exception, which the raised one chains to, is not left
    # half-rewritten: its status agrees with the response it shares
    assert raw.status_code == raw.response.status_code == 500


def test_unclassified_stream_error_still_retries_on_overload_text() -> None:
    # The message-text fallback predates normalization and still applies: a
    # mid-stream error the table cannot classify whose text says the provider
    # is overloaded is transient, exactly as it was when it carried a 200.
    api = AnthropicAPI(model_name="claude-test", api_key="test-key")
    ex = _anthropic_stream_error("some_future_error", "Overloaded, try later")
    decision = api.should_retry(ex)
    assert not isinstance(decision, bool)
    assert decision.kind == "transient"


@pytest.mark.parametrize(
    ("body", "retry"),
    [
        pytest.param("event: error\ndata: not json", False, id="undecodable-string"),
        # the message-text fallback still reads the raw body, as it always has
        pytest.param(
            {"type": "error", "error": "overloaded"}, True, id="error-not-a-mapping"
        ),
        pytest.param({"type": "error"}, False, id="no-error-member"),
        pytest.param(None, False, id="no-body"),
    ],
)
def test_malformed_stream_error_is_a_server_error_not_a_success(
    body: object, retry: bool
) -> None:
    # The SDK raised, so the provider failed the request; whatever shape the
    # event data took, a 200 must not survive normalization. The body stays as
    # captured so the operator can still see what the provider sent. The 500 is
    # for reporting, not a transient-failure claim: retry classification is what
    # it was when the error carried a 200 (only the text fallback can retry it).
    ex = _normalize_stream_error(
        APIStatusError(
            "mid-stream error",
            response=httpx2.Response(
                status_code=200,
                request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
            ),
            body=body,
        )
    )
    assert isinstance(ex, _UnclassifiedStreamError)
    assert ex.status_code == 500
    assert ex.body == body
    assert provider_error_payload(ex)["status"] == 500
    api = AnthropicAPI(model_name="claude-test", api_key="test-key")
    assert bool(api.should_retry(ex)) is retry


def test_stream_rate_limit_outranks_an_overloaded_message() -> None:
    # The provider's own classification wins over message text: a
    # rate_limit_error whose message mentions overload is a rate limit, the
    # one kind adaptive concurrency acts on, not a generic transient failure.
    api = AnthropicAPI(model_name="claude-test", api_key="test-key")
    ex = _anthropic_stream_error("rate_limit_error", "overloaded, slow down")
    decision = api.should_retry(ex)
    assert not isinstance(decision, bool)
    assert decision.kind == "rate_limit"


# ---------- ModelGenerateError ----------


def test_model_generate_error_is_runtime_error_and_carries_fields() -> None:
    ex = ModelGenerateError(
        "verbose debug message",
        status_code=400,
        provider_message="Could not process image",
    )
    assert isinstance(ex, RuntimeError)
    assert ex.status_code == 400
    assert ex.provider_message == "Could not process image"
    # the human-readable message stays the verbose debug string
    assert str(ex) == "verbose debug message"


# ---------- provider_error_payload ----------


def test_provider_error_payload_prefers_provider_message() -> None:
    ex = ModelGenerateError(
        "verbose debug", status_code=400, provider_message="clean provider message"
    )
    assert provider_error_payload(ex) == {
        "status": 400,
        "message": "clean provider message",
    }


def test_provider_error_payload_raw_sdk_exception() -> None:
    assert provider_error_payload(_ProviderError("rate limited", 429)) == {
        "status": 429,
        "message": "rate limited",
    }


def test_provider_error_payload_bare_exception() -> None:
    assert provider_error_payload(ValueError("boom")) == {
        "status": None,
        "message": "boom",
    }


@pytest.mark.parametrize("via_cause", [False, True], ids=("last_attempt", "cause"))
def test_provider_error_payload_unwraps_openai_retry_error(
    via_cause: bool,
) -> None:
    """A retried OpenAI failure retains its provider-native error body."""
    import httpx2
    from openai import RateLimitError
    from tenacity import Future, RetryError

    message = "You have no credits remaining..."
    body = {
        "message": message,
        "type": "insufficient_quota",
        "code": "credit_balance_exhausted",
    }
    provider_error = RateLimitError(
        message=message,
        response=httpx2.Response(
            429,
            request=httpx2.Request("POST", "https://api.openai.com/v1/responses"),
        ),
        body=body,
    )
    attempt = Future(1)
    if via_cause:
        retry_error = RetryError(attempt)
        retry_error.__cause__ = provider_error
    else:
        attempt.set_exception(provider_error)
        retry_error = RetryError(attempt)

    assert provider_error_payload(retry_error) == {
        "status": 429,
        "message": message,
        "body": body,
    }


def test_provider_error_payload_handles_retry_error_with_successful_attempt() -> None:
    """A RetryError with no underlying exception retains generic formatting."""
    from tenacity import Future, RetryError

    attempt = Future(1)
    attempt.set_result(None)
    retry_error = RetryError(attempt)

    assert provider_error_payload(retry_error) == {
        "status": None,
        "message": str(retry_error),
    }


# ---------- _forward_provider_errors (service.py) ----------


def _bridge(
    forward_client_headers: dict[str, list[str]] | None = None,
) -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        forward_client_headers=forward_client_headers,
    )


async def test_forward_provider_errors_passes_success_through() -> None:
    async def ok(
        json_data: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return {"id": "x", "choices": []}

    wrapped = _forward_provider_errors(ok, _bridge())
    assert await wrapped({}) == {"id": "x", "choices": []}


async def test_forward_provider_errors_returns_marker_on_exception() -> None:
    async def boom(
        json_data: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        raise ModelGenerateError(
            "debug", status_code=503, provider_message="overloaded"
        )

    wrapped = _forward_provider_errors(boom, _bridge())
    result = await wrapped({})
    assert result == {PROVIDER_ERROR_KEY: {"status": 503, "message": "overloaded"}}


async def test_forward_provider_errors_warns_on_non_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error with no recoverable status (likely our own bug) is logged."""
    warnings: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        bridge_service.logger, "warning", lambda *a, **k: warnings.append((a, k))
    )

    async def boom(
        json_data: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        raise ValueError("our own translation bug")

    result = await _forward_provider_errors(boom, _bridge())({})
    assert result == {
        PROVIDER_ERROR_KEY: {"status": None, "message": "our own translation bug"}
    }
    assert len(warnings) == 1


async def test_forward_provider_errors_no_warn_on_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine provider error (carries a status) is forwarded without warning."""
    warnings: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        bridge_service.logger, "warning", lambda *a, **k: warnings.append((a, k))
    )

    async def boom(
        json_data: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        raise ModelGenerateError("debug", status_code=503, provider_message="x")

    result = await _forward_provider_errors(boom, _bridge())({})
    assert result == {PROVIDER_ERROR_KEY: {"status": 503, "message": "x"}}
    assert warnings == []


class _SandboxCompletion:
    def model_dump(self, *, mode: str, warnings: bool) -> dict[str, JsonValue]:
        return {"id": "completion"}


async def test_sandbox_generation_filters_and_forwards_client_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_headers: list[dict[str, str] | None] = []

    async def request(
        json_data: dict[str, JsonValue],
        headers: dict[str, str] | None,
        bridge: SandboxAgentBridge,
    ) -> _SandboxCompletion:
        received_headers.append(headers)
        return _SandboxCompletion()

    monkeypatch.setattr(bridge_service, "inspect_completions_api_request", request)
    generate = bridge_service.generate_completions(
        _bridge({"anthropic-beta": ["code-execution-2025-08-25"]})
    )

    await generate(
        {"model": "inspect"},
        {
            "authorization": "Bearer secret",
            "anthropic-beta": "code-execution-2025-08-25",
            "x-claude-code-agent-id": "toolu_x",
        },
    )

    assert received_headers == [{"anthropic-beta": "code-execution-2025-08-25"}]


async def test_sandbox_responses_filters_and_forwards_client_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_headers: list[dict[str, str] | None] = []

    async def request(
        json_data: dict[str, JsonValue],
        headers: dict[str, str] | None,
        web_search: WebSearchProviders,
        code_execution: CodeExecutionProviders,
        bridge: SandboxAgentBridge,
    ) -> _SandboxCompletion:
        received_headers.append(headers)
        return _SandboxCompletion()

    monkeypatch.setattr(bridge_service, "inspect_responses_api_request", request)
    generate = bridge_service.generate_responses(
        cast(WebSearchProviders, None),
        cast(CodeExecutionProviders, None),
        _bridge({"anthropic-beta": ["code-execution-2025-08-25"]}),
    )

    await generate(
        {"model": "inspect"},
        {
            "authorization": "Bearer secret",
            "anthropic-beta": "code-execution-2025-08-25",
            "x-claude-code-agent-id": "toolu_x",
        },
    )

    assert received_headers == [{"anthropic-beta": "code-execution-2025-08-25"}]


async def test_sandbox_anthropic_filters_and_forwards_client_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_headers: list[dict[str, str] | None] = []

    async def request(
        json_data: dict[str, JsonValue],
        headers: dict[str, str] | None,
        web_search: WebSearchProviders,
        code_execution: CodeExecutionProviders,
        bridge: SandboxAgentBridge,
    ) -> _SandboxCompletion:
        received_headers.append(headers)
        return _SandboxCompletion()

    monkeypatch.setattr(bridge_service, "inspect_anthropic_api_request", request)
    generate = bridge_service.generate_anthropic(
        cast(WebSearchProviders, None),
        cast(CodeExecutionProviders, None),
        _bridge({"anthropic-beta": ["code-execution-2025-08-25"]}),
    )

    await generate(
        {"model": "inspect"},
        {
            "authorization": "Bearer secret",
            "anthropic-beta": "code-execution-2025-08-25",
            "x-claude-code-agent-id": "toolu_x",
        },
    )

    assert received_headers == [{"anthropic-beta": "code-execution-2025-08-25"}]


async def test_sandbox_anthropic_forwards_only_allowed_client_betas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client headers reach the host request only when the eval author lists them."""
    bridge_module._logged_client_header_drops.clear()
    received_headers: list[dict[str, str] | None] = []

    async def request(
        json_data: dict[str, JsonValue],
        headers: dict[str, str] | None,
        web_search: WebSearchProviders,
        code_execution: CodeExecutionProviders,
        bridge: SandboxAgentBridge,
    ) -> _SandboxCompletion:
        received_headers.append(headers)
        return _SandboxCompletion()

    monkeypatch.setattr(bridge_service, "inspect_anthropic_api_request", request)
    client_headers = {
        "accept-encoding": "gzip, br",
        "anthropic-beta": "allowed-beta-2026-01-01,unlisted-beta-2026-01-01",
    }

    # default: the sandboxed client cannot choose any beta
    default_generate = bridge_service.generate_anthropic(
        cast(WebSearchProviders, None),
        cast(CodeExecutionProviders, None),
        _bridge(),
    )
    await default_generate({"model": "inspect"}, client_headers)

    # listed betas are forwarded, the others are dropped
    listed_generate = bridge_service.generate_anthropic(
        cast(WebSearchProviders, None),
        cast(CodeExecutionProviders, None),
        _bridge({"anthropic-beta": ["allowed-beta-2026-01-01"]}),
    )
    await listed_generate({"model": "inspect"}, client_headers)

    assert received_headers == [
        {"accept-encoding": "gzip, br"},
        {"accept-encoding": "gzip, br", "anthropic-beta": "allowed-beta-2026-01-01"},
    ]
    assert [
        m for m in bridge_module._logged_client_header_drops if "unlisted-beta" in m
    ] == [
        "Agent bridge dropped 'unlisted-beta-2026-01-01' from the sandboxed "
        "agent's 'anthropic-beta' header. To forward it, add it to "
        "sandbox_agent_bridge(forward_client_headers=...)."
    ]


def test_sandbox_bridge_validates_forward_client_headers() -> None:
    """Invalid allowlists fail when the bridge is constructed."""
    with pytest.raises(TypeError, match="forward_client_headers"):
        _bridge({"anthropic-beta": cast(list[str], "context-1m-2025-08-07")})
    with pytest.raises(ValueError, match="Authorization"):
        _bridge({"Authorization": ["Bearer x"]})


async def test_sandbox_google_generation_accepts_service_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def request(
        json_data: dict[str, JsonValue],
        web_search: WebSearchProviders,
        code_execution: CodeExecutionProviders,
        bridge: SandboxAgentBridge,
    ) -> dict[str, JsonValue]:
        return {"id": "completion"}

    monkeypatch.setattr(bridge_service, "inspect_google_api_request", request)
    generate = bridge_service.generate_google(
        cast(WebSearchProviders, None),
        cast(CodeExecutionProviders, None),
        cast(SandboxAgentBridge, None),
    )

    result = await generate({"model": "inspect"}, {"x-claude-code-agent-id": "toolu_x"})

    assert result == {"id": "completion"}


def _refusal() -> ModelRefusalError:
    return ModelRefusalError(
        ModelOutput.from_content(
            model="mockllm/model", content="No.", stop_reason="content_filter"
        ),
        "mockllm/model",
    )


@pytest.mark.parametrize(
    "make_error",
    [
        pytest.param(_refusal, id="refusal"),
        pytest.param(
            lambda: ResponseFilterError("ValueError: filter is broken"),
            id="response_filter",
        ),
    ],
)
async def test_forward_provider_errors_signals_sample_failure_to_bridge(
    monkeypatch: pytest.MonkeyPatch, make_error: Callable[[], Exception]
) -> None:
    """An error that must end the sample does so via the bridge, not via a raise.

    Covers a fail_on_refusal refusal and a `ResponseFilterError`. The sandbox
    service dispatcher would turn a re-raise into an RPC error, so the wrapper
    hands the error to `bridge.request_fail` (raised on the agent's side by the
    bridge's monitor task) and still answers the scaffold with a provider error
    payload. It is not logged as a non-provider error, since the sample error is
    the report.
    """
    warnings: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        bridge_service.logger, "warning", lambda *a, **k: warnings.append((a, k))
    )
    error = make_error()

    async def boom(
        json_data: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        raise error

    bridge = _bridge()
    result = await _forward_provider_errors(boom, bridge)({})
    assert result == {PROVIDER_ERROR_KEY: {"status": None, "message": str(error)}}
    assert bridge._failure_requested.is_set()
    assert bridge._failure is error
    assert warnings == []


async def test_forward_provider_errors_records_a_limit_and_replies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A limit is answered with an error reply and recorded for the bridge to raise.

    `sandbox_agent_bridge` raises it once the agent has unwound, so the scope
    that applied it handles it. The bridge's monitor is not signalled, and
    nothing is logged.
    """
    warnings: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        bridge_service.logger, "warning", lambda *a, **k: warnings.append((a, k))
    )
    error = LimitExceededError("message", value=2, limit=1)

    async def boom(
        json_data: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        raise error

    bridge = _bridge()
    result = await _forward_provider_errors(boom, bridge)({})
    assert result == {PROVIDER_ERROR_KEY: {"status": None, "message": str(error)}}
    assert bridge.generation_limit is error
    assert not bridge._failure_requested.is_set()
    assert warnings == []


async def test_forward_provider_errors_logs_other_errors_beside_a_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Other errors in a group a limit is selected from are logged with their traceback.

    The limit is still recorded and answered with the group's error reply.
    """
    warnings: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        bridge_service.logger, "warning", lambda *a, **k: warnings.append((a, k))
    )
    error = LimitExceededError("message", value=2, limit=1)
    bug = RuntimeError("judge bug")
    group = ExceptionGroup("judges", [error, bug])

    async def boom(
        json_data: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        raise group

    bridge = _bridge()
    result = await _forward_provider_errors(boom, bridge)({})
    assert result == {PROVIDER_ERROR_KEY: {"status": None, "message": str(group)}}
    assert bridge.generation_limit is error
    assert not bridge._failure_requested.is_set()
    [(args, kwargs)] = warnings
    logged = kwargs["exc_info"]
    assert isinstance(logged, ExceptionGroup) and logged.exceptions == (bug,)
    assert logged.__traceback__ is not None


async def test_forward_provider_errors_keeps_only_the_first_limit() -> None:
    """Only the first limit is recorded; later ones are released once answered.

    A scaffold can keep sending requests after its error reply. Their limit
    errors, with the request frames in their tracebacks, are not kept until
    the agent unwinds.
    """
    errors = [LimitExceededError("message", value=2, limit=1) for _ in range(2)]
    first = errors[0]
    later = weakref.ref(errors[1])

    async def over_limit(
        json_data: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        raise errors.pop(0)

    bridge = _bridge()
    forward = _forward_provider_errors(over_limit, bridge)
    for _ in range(2):
        assert PROVIDER_ERROR_KEY in await forward({})
    gc.collect()
    assert bridge.generation_limit is first
    assert later() is None


@pytest.mark.parametrize("wrapper", ["bare", "grouped", "limit"])
async def test_forward_provider_errors_leaves_termination_to_the_dispatcher(
    wrapper: str,
) -> None:
    """A `TerminateSampleError` (e.g. from a request or response filter) is re-raised.

    The sandbox service dispatcher answers the RPC and propagates a termination
    out of the service task, which ends the sample, so the wrapper neither
    forwards it as a provider error nor signals the bridge's monitor task. This
    holds for a termination in a group or in the history of a limit too.
    """
    error = TerminateSampleError("Judge said stop.")

    async def boom(
        json_data: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        if wrapper == "grouped":
            raise ExceptionGroup("judge", [error])
        if wrapper == "limit":
            raise LimitExceededError("token", value=2, limit=1) from error
        raise error

    bridge = _bridge()
    with pytest.raises(
        (TerminateSampleError, ExceptionGroup, LimitExceededError)
    ) as excinfo:
        await _forward_provider_errors(boom, bridge)({})
    assert find_control_flow(excinfo.value) is error
    assert not bridge._failure_requested.is_set()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mid_stream", [False, True], ids=["http-status", "sse-error-event"]
)
@pytest.mark.parametrize(
    ("error_type", "status"),
    [
        ("rate_limit_error", 429),
        ("overloaded_error", 529),
        ("timeout_error", 504),
    ],
)
async def test_bridge_forwards_retry_exhausted_anthropic_http_error(
    monkeypatch: pytest.MonkeyPatch, error_type: str, status: int, mid_stream: bool
) -> None:
    """Retry exhaustion preserves the provider's failure for the bridge client.

    With a finite retry budget the provider's error surfaces from `Model.generate()`
    as a tenacity `RetryError`; the bridge must still forward the status and message
    of the failure that exhausted it. Covered for an error carried on the HTTP
    status and for one delivered as a mid-stream SSE `error` event (status 200 until
    the provider normalizes it).
    """
    message = f"provider said {status}"
    raised_status = 200 if mid_stream else status
    model = get_model(
        "anthropic/claude-test",
        api_key="test-key",
        config=GenerateConfig(max_retries=1),
        memoize=False,
    )
    assert isinstance(model.api, AnthropicAPI)
    model.api.streaming = True
    attempts = 0

    async def fail_stream_request(*args: object, **kwargs: object) -> object:
        nonlocal attempts
        assert args[1] is True
        attempts += 1
        raise APIStatusError(
            "mid-stream error" if mid_stream else message,
            response=httpx2.Response(
                status_code=raised_status,
                request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
            ),
            body={
                "type": "error",
                "error": {"type": error_type, "message": message},
            },
        )

    monkeypatch.setattr(
        model.api, "_perform_request_and_continuations", fail_stream_request
    )

    async def generate_anthropic(
        json_data: dict[str, JsonValue],
        headers: dict[str, str] | None = None,
        *,
        metadata_headers: dict[str, str] | None = None,
    ) -> dict[str, JsonValue]:
        await model.generate(input="hello")
        raise AssertionError("model generation unexpectedly succeeded")

    result = await _forward_provider_errors(generate_anthropic, _bridge())({})

    assert attempts == 2
    assert result == {PROVIDER_ERROR_KEY: {"status": status, "message": message}}


# ---------- _model.py wrap path (end to end) ----------


class _ReturnsExceptionAPI(ModelAPI):
    """ModelAPI whose generate *returns* an exception (the wrapped `_model.py` path)."""

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[],
            config=config,
        )
        self._status_code = model_args.get("status_code")
        self._message = model_args.get("message", "error")

    async def generate(self, *args: Any, **kwargs: Any) -> Any:
        return _ProviderError(self._message, self._status_code), None


async def test_model_generate_wraps_returned_exception_with_status() -> None:
    @modelapi(name="returnsexc")
    def returnsexc() -> type[ModelAPI]:
        return _ReturnsExceptionAPI

    try:
        model = get_model(
            "returnsexc/x", status_code=400, message="Could not process image"
        )
        with pytest.raises(ModelGenerateError) as excinfo:
            await model.generate(input="hello")
        assert excinfo.value.status_code == 400
        assert "Could not process image" in (excinfo.value.provider_message or "")
        # the original provider exception is chained as the cause
        assert excinfo.value.__cause__ is not None
    finally:
        del _registry["modelapi:returnsexc"]


# ---------- limits reached in a sandbox-bridged generation ----------


@dataclass
class _Request:
    """One chat completion request the scaffold makes, and how it is held.

    `messages` is the number of messages it carries. With `after_first`, it
    waits for the scaffold's first request to be replied to before it
    generates. With `during_shutdown`, the agent returns once it starts and it
    generates once the bridge is killing the model proxy. A `held` reply write
    begins and then waits until it is cancelled.
    """

    messages: int = 1
    after_first: bool = False
    during_shutdown: bool = False
    held: bool = False

    def arm(self) -> None:
        """Make the events, in the event loop that waits on them."""
        self.generating = anyio.Event()
        self.writing = anyio.Event()
        self.replied = anyio.Event()


@dataclass
class _Scaffold:
    """The requests a bridged scaffold makes concurrently, and how it exits.

    Once every reply has been written, the scaffold exits: cleanly, or with
    `fails` as a CLI wrapper does when the CLI exits unsuccessfully. The
    bridge applies `filter` and `response_filter` to its generations. With
    `slow_kill`, killing the model proxy lasts until an enclosing scope has
    cancelled the model service. With `cancel_on_kill`, killing it cancels the
    scope enclosing the bridge (`enclosing`), as an enclosing time limit
    expiring then would.
    """

    requests: list[_Request]
    fails: bool = False
    filter: ModelGenerateFilter | None = None
    response_filter: ModelResponseFilter | None = None
    slow_kill: bool = False
    cancel_on_kill: bool = False
    enclosing: anyio.CancelScope = field(init=False)

    def arm(self) -> None:
        self.killing = anyio.Event()
        self.service_cancelled = anyio.Event()
        for request in self.requests:
            request.arm()

    @property
    def during_shutdown(self) -> _Request | None:
        return next((r for r in self.requests if r.during_shutdown), None)


class _ExitedProxy:
    """A model proxy process that has already exited cleanly.

    Killing it lets a request held for the bridge's shutdown go on, and waits
    for its reply to be written or, for a held reply, begun.
    """

    def __init__(self, scaffold: _Scaffold) -> None:
        self._scaffold = scaffold

    def __aiter__(self) -> _ExitedProxy:
        return self

    async def __anext__(self) -> object:
        raise StopAsyncIteration

    async def kill(self) -> None:
        if self._scaffold.cancel_on_kill:
            self._scaffold.enclosing.cancel()
        if self._scaffold.slow_kill:
            with anyio.fail_after(10):
                await self._scaffold.service_cancelled.wait()
            # let the bridge's other cancelled tasks finish too
            for _ in range(10):
                await anyio.lowlevel.checkpoint()
        request = self._scaffold.during_shutdown
        if request is not None:
            self._scaffold.killing.set()
            with anyio.fail_after(10):
                await (request.writing if request.held else request.replied).wait()


class _ProxySandbox:
    def __init__(self, scaffold: _Scaffold) -> None:
        self.exec_remote = AsyncMock(return_value=_ExitedProxy(scaffold))
        self._tools_user: str | None = None


Reply = tuple[JsonValue | None, str | None]


def _serve_generations(
    monkeypatch: pytest.MonkeyPatch, scaffold: _Scaffold, replies: list[Reply]
) -> None:
    """Make `sandbox_agent_bridge` serve the scaffold's requests, without a sandbox.

    The bridge, its model service methods and the sandbox service dispatcher
    are real; the sandbox, the model proxy process and the request transport
    (`dispatching_service`) are faked. The requests are handled concurrently,
    as the dispatcher handles them. Each reply the dispatcher writes, as
    (result, error), is appended to `replies` once the scaffold can read it;
    the write then waits a little longer, as request removal does, so a
    scaffold that exits on reading it can end the agent first.
    """
    monkeypatch.setattr(
        sandbox_bridge_module,
        "sandbox_with_injected_tools",
        AsyncMock(return_value=_ProxySandbox(scaffold)),
    )

    async def serve(
        *,
        methods: dict[str, Callable[..., Any]],
        started: anyio.Event,
        **kwargs: Any,
    ) -> None:
        scaffold.arm()
        generate = methods["generate_completions"]

        def service_for(request: _Request) -> SandboxService:
            async def held_generate(**params: Any) -> JsonValue:
                if request.after_first:
                    await scaffold.requests[0].replied.wait()
                if request.during_shutdown:
                    request.generating.set()
                    await scaffold.killing.wait()
                return cast(JsonValue, await generate(**params))

            service = dispatching_service(
                monkeypatch,
                "generate_completions",
                held_generate,
                {
                    "json_data": {
                        "model": "inspect",
                        "messages": [{"role": "user", "content": "Say hi."}]
                        * request.messages,
                    }
                },
                [],
            )

            async def write_response(
                request_file: str,
                request_id: str,
                result: JsonValue | None,
                error: str | None = None,
            ) -> None:
                request.writing.set()
                if request.held:
                    await anyio.sleep_forever()
                replies.append((result, error))
                request.replied.set()
                await anyio.sleep(0.01)

            monkeypatch.setattr(service, "_write_response", write_response)
            return service

        services = [service_for(request) for request in scaffold.requests]
        started.set()
        async with anyio.create_task_group() as tg:
            for service in services:
                tg.start_soon(service._handle_request_tracked, REQUEST_FILE, REQUEST_ID)
        try:
            await anyio.sleep_forever()
        finally:
            scaffold.service_cancelled.set()

    monkeypatch.setattr(bridge_service, "sandbox_service", serve)


@agent
def _bridged_agent(scaffold: _Scaffold) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        with anyio.CancelScope() as scaffold.enclosing:
            async with sandbox_agent_bridge(
                state, filter=scaffold.filter, response_filter=scaffold.response_filter
            ) as bridge:
                request = scaffold.during_shutdown
                if request is not None:
                    # complete while that generation is in flight
                    await request.generating.wait()
                else:
                    # the scaffold, waiting on its model requests
                    with anyio.fail_after(10):
                        for request in scaffold.requests:
                            await request.replied.wait()
                    if scaffold.fails:
                        raise RuntimeError("The scaffold exited with an error.")
        return bridge.state

    return execute


class _Outcome(NamedTuple):
    sample: EvalSample
    errors: list[LimitExceededError | None]
    """The limit errors the `run()` of the bridged agent returned."""
    outer_errors: list[LimitExceededError | None]
    """The limit errors an enclosing `run()` returned."""
    replies: list[Reply]


def _run_bridged_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: Limit,
    scaffold: _Scaffold | None = None,
    sample_token_limit: int | None = None,
    outer_limit: Limit | None = None,
) -> _Outcome:
    """Run a bridged agent under `run(limits=[limit])` in a one-sample eval.

    The agent's scaffold makes one request by default. With `outer_limit`,
    that `run()` is inside another `run()` applying it. The solver marks the
    sample's store once the outermost `run()` returns, so a sample that
    continued past the agent has `store["continued"]` set.
    """
    scaffold = scaffold or _Scaffold([_Request()])
    replies: list[Reply] = []
    _serve_generations(monkeypatch, scaffold, replies)
    output = ModelOutput.from_content(model="mockllm/model", content="hi")
    output.usage = ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7)
    errors: list[LimitExceededError | None] = []
    outer_errors: list[LimitExceededError | None] = []

    @agent
    def outer_agent() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            state, error = await run(_bridged_agent(scaffold), state, limits=[limit])
            errors.append(error)
            return state

        return execute

    @solver
    def run_bridged() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if outer_limit is None:
                _, error = await run(
                    _bridged_agent(scaffold), state.messages, limits=[limit]
                )
                errors.append(error)
            else:
                _, error = await run(
                    outer_agent(), state.messages, limits=[outer_limit]
                )
                outer_errors.append(error)
            state.store.set("continued", True)
            return state

        return solve

    log = eval(
        Task(
            dataset=[Sample(input="Say hi.")],
            solver=run_bridged(),
            token_limit=sample_token_limit,
        ),
        model=get_model("mockllm/model", custom_outputs=[output] * 3),
        log_dir=str(tmp_path),
        display="none",
    )[0]
    assert log.samples is not None
    return _Outcome(log.samples[0], errors, outer_errors, replies)


def _assert_error_replies(replies: list[Reply], count: int = 1) -> None:
    assert len(replies) == count
    for result, error in replies:
        assert error is None
        assert isinstance(result, dict) and PROVIDER_ERROR_KEY in result


def _assert_agent_limit(outcome: _Outcome, limit: Limit) -> LimitExceededError:
    sample = outcome.sample
    assert sample.error is None, sample.error
    assert sample.limit is None
    assert sample.store.get("continued") is True
    [error] = outcome.errors
    assert error is not None and error.source is limit
    return error


def _assert_sample_token_limit(outcome: _Outcome, limit: int = 5) -> None:
    sample = outcome.sample
    assert sample.error is None, sample.error
    assert sample.limit is not None
    assert (sample.limit.type, sample.limit.limit) == ("token", limit)
    assert "continued" not in sample.store
    assert outcome.errors == []


@pytest.fixture
def _model_cost() -> Iterator[None]:
    set_model_info(
        "model",
        ModelInfo(
            cost=ModelCost(
                input=1000.0, output=1000.0, input_cache_write=0.0, input_cache_read=0.0
            )
        ),
    )
    yield
    clear_model_info_cache()


@pytest.mark.parametrize(
    ("make_limit", "limit_type"),
    [
        # one generation of 7 tokens
        pytest.param(lambda: token_limit(5), "token", id="token"),
        # $0.007 at $1000 per million tokens
        pytest.param(lambda: cost_limit(0.001), "cost", id="cost"),
        # the request carries one message: no room for the reply
        pytest.param(lambda: message_limit(1), "message", id="message"),
        pytest.param(lambda: turn_limit(0), "turn", id="turn"),
    ],
)
@pytest.mark.usefixtures("_model_cost")
def test_agent_limit_in_a_bridged_generation_ends_only_the_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_limit: Callable[[], Limit],
    limit_type: str,
) -> None:
    """A limit `run()` applied, reached in a bridged generation, ends only the agent.

    The scaffold gets an error reply and exits. As for a native agent, `run()`
    returns the limit error and the sample continues without a limit.
    """
    limit = make_limit()

    outcome = _run_bridged_agent(tmp_path, monkeypatch, limit)

    error = _assert_agent_limit(outcome, limit)
    assert error.type == limit_type
    _assert_error_replies(outcome.replies)


def test_sample_limit_in_a_bridged_generation_ends_the_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sample limit reached in a bridged generation ends the sample with that limit.

    The error propagates out of the agent, past the `run()` limits that do not
    own it, to the sample runner, which records it as for a native agent.
    """
    outcome = _run_bridged_agent(
        tmp_path, monkeypatch, token_limit(1000), sample_token_limit=5
    )

    _assert_sample_token_limit(outcome)
    _assert_error_replies(outcome.replies)


@pytest.mark.parametrize("owner", ["agent", "sample"])
def test_limit_in_a_bridged_generation_outlasts_a_failed_scaffold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: str
) -> None:
    """A scaffold that exits with an error after reading a limit's reply leaves the limit.

    CLI wrappers raise when the CLI exits unsuccessfully, which it can do as
    soon as it has read the error reply. The limit is raised in place of that
    error, so the scope that applied it handles it.
    """
    limit = token_limit(5 if owner == "agent" else 1000)

    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        limit,
        scaffold=_Scaffold([_Request()], fails=True),
        sample_token_limit=5 if owner == "sample" else None,
    )

    if owner == "agent":
        _assert_agent_limit(outcome, limit)
    else:
        _assert_sample_token_limit(outcome)
    _assert_error_replies(outcome.replies)


@pytest.mark.parametrize("reply", ["written", "cancelled"])
@pytest.mark.parametrize("owner", ["agent", "sample"])
def test_limit_in_a_bridged_generation_during_shutdown_is_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: str, reply: str
) -> None:
    """A limit reached after the agent completed, while the bridge shuts down, is raised.

    It is not a cleanup error to log: the scope that applied it handles it, as
    when the agent is still running. A `run()` limit ends the agent; a sample
    limit ends the sample. This holds when the bridge's own cleanup cancels
    the reply too.
    """
    limit = token_limit(5 if owner == "agent" else 1000)
    request = _Request(during_shutdown=True, held=reply == "cancelled")

    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        limit,
        scaffold=_Scaffold([request]),
        sample_token_limit=5 if owner == "sample" else None,
    )

    if owner == "agent":
        _assert_agent_limit(outcome, limit)
    else:
        _assert_sample_token_limit(outcome)
    if reply == "written":
        _assert_error_replies(outcome.replies)
    else:
        assert outcome.replies == []


@pytest.mark.parametrize("first", ["sample", "agent"])
def test_concurrent_bridged_generations_raise_the_first_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: str
) -> None:
    """Of limits reached by concurrent bridged generations, the first is raised.

    One request reaches the sample's token limit, another the `run()` message
    limit, in either order. A native agent stops at the first limit it reaches,
    so the scope that applied the first one handles it. When that is the
    `run()` limit, the sample's limit reached after the error reply is not
    raised, since nothing generates again in the sample.
    """
    # 7 tokens: over the sample's token limit
    sample_request = _Request(after_first=first == "agent")
    # 2 messages: no room for a reply under the run() limit
    agent_request = _Request(messages=2, after_first=first == "sample")
    requests = [sample_request, agent_request]
    if first == "agent":
        requests.reverse()
    limit = message_limit(2)

    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        limit,
        scaffold=_Scaffold(requests),
        sample_token_limit=5,
    )

    if first == "sample":
        _assert_sample_token_limit(outcome)
    else:
        _assert_agent_limit(outcome, limit)
    _assert_error_replies(outcome.replies, count=2)


@pytest.mark.parametrize("owner", ["agent", "sample"])
def test_limit_in_a_bridged_filter_task_group_is_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: str
) -> None:
    """A limit a generate filter's task group reaches is raised, though grouped.

    The filter generates in a task group, which raises the generation's token
    limit in an exception group. The scope that applied the limit handles it.
    """
    limit = token_limit(5 if owner == "agent" else 1000)

    async def generates_in_a_task_group(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        outputs: list[ModelOutput] = []

        async def generate() -> None:
            outputs.append(await model.generate(messages, tools, tool_choice, config))

        async with anyio.create_task_group() as tg:
            tg.start_soon(generate)
        return outputs[0]

    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        limit,
        scaffold=_Scaffold([_Request()], filter=generates_in_a_task_group),
        sample_token_limit=5 if owner == "sample" else None,
    )

    if owner == "agent":
        _assert_agent_limit(outcome, limit)
    else:
        _assert_sample_token_limit(outcome)
    _assert_error_replies(outcome.replies)


def test_refusal_before_a_limit_in_a_response_filter_group_fails_the_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal first in a response filter's group fails the sample, as natively.

    The filter's judge generation reaches the `run()` token limit, and the
    filter raises a refusal and that limit together. The bridge reduces the
    group to the refusal, which fails the sample; the limit behind it is not
    raised.
    """

    async def refuses_over_a_limit(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        try:
            await model.generate("Judge this.")
        except LimitExceededError as ex:
            raise ExceptionGroup("judges", [_refusal(), ex])
        raise AssertionError("The judge's generation is within the limit.")

    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        # 7 tokens each for the agent's generation and the judge's
        token_limit(10),
        # the reply never completes: only the failure ends the agent
        scaffold=_Scaffold([_Request(held=True)], response_filter=refuses_over_a_limit),
    )

    sample = outcome.sample
    assert sample.error is not None
    assert "refus" in sample.error.message.lower(), sample.error.message
    assert sample.limit is None
    assert "continued" not in sample.store
    assert outcome.errors == []


def test_handled_limit_behind_a_provider_error_is_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A limit a generate filter handled is not raised for the provider error after it.

    The filter generates under its own token limit, catches the limit error
    after that limit's scope has exited, and its fallback fails with a
    provider error. The scaffold gets that error's 500 reply; the agent and
    the sample are not limited.
    """

    async def falls_back(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        try:
            with token_limit(5):
                return await model.generate(messages, tools, tool_choice, config)
        except LimitExceededError:
            raise APIStatusError(
                "The fallback failed.",
                response=httpx2.Response(
                    status_code=500,
                    request=httpx2.Request("POST", "https://api.example.com"),
                ),
                body=None,
            )

    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        token_limit(1000),
        scaffold=_Scaffold([_Request()], filter=falls_back),
    )

    sample = outcome.sample
    assert sample.error is None, sample.error
    assert sample.limit is None
    assert sample.store.get("continued") is True
    assert outcome.errors == [None]
    _assert_error_replies(outcome.replies)
    [(result, _)] = outcome.replies
    assert isinstance(result, dict)
    payload = result[PROVIDER_ERROR_KEY]
    assert isinstance(payload, dict) and payload["status"] == 500


def test_first_limit_in_a_bridged_filter_group_is_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Of the limits in a generate filter's group, the first in the group is raised.

    The group holds the bridged agent's `run()` message limit, then the
    enclosing `run()`'s token limit. The agent's `run()` handles its limit and
    the enclosing one returns none.
    """
    inner = message_limit(10)
    outer = token_limit(1000)

    async def over_limits(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        raise ExceptionGroup(
            "generations",
            [
                LimitExceededError("message", value=11, limit=10, source=inner),
                LimitExceededError("token", value=1001, limit=1000, source=outer),
            ],
        )

    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        inner,
        scaffold=_Scaffold([_Request()], filter=over_limits),
        outer_limit=outer,
    )

    _assert_agent_limit(outcome, inner)
    assert outcome.outer_errors == [None]
    _assert_error_replies(outcome.replies)


@pytest.mark.parametrize(
    ("first", "held"),
    [
        ("refusal", True),
        ("refusal", False),
        ("limit", False),
        ("nested_refusal", True),
    ],
    ids=["refusal", "refusal_completed", "limit", "nested_refusal"],
)
def test_first_of_a_bridged_filter_group_of_limits_and_refusals_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: str, held: bool
) -> None:
    """A generate filter's group of only limits and refusals counts as its first member.

    As for a response filter's group: a refusal first, also in a nested group,
    fails the sample; a limit first is raised and the agent's `run()` handles
    it. A refusal's reply is held, so only the failure ends the agent, or
    completed, so the scaffold reads it and returns.
    """
    limit = message_limit(10)

    async def over_limit_and_refused(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        error = LimitExceededError("message", value=11, limit=10, source=limit)
        members: list[Exception] = {
            "refusal": [_refusal(), error],
            "limit": [error, _refusal()],
            "nested_refusal": [ExceptionGroup("judges", [_refusal()]), error],
        }[first]
        raise ExceptionGroup("generations", members)

    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        limit,
        scaffold=_Scaffold([_Request(held=held)], filter=over_limit_and_refused),
    )

    if first == "limit":
        _assert_agent_limit(outcome, limit)
        _assert_error_replies(outcome.replies)
    else:
        sample = outcome.sample
        assert sample.error is not None
        assert "refus" in sample.error.message.lower(), sample.error.message
        assert sample.limit is None
        assert "continued" not in sample.store
        assert outcome.errors == []


def test_request_after_a_bridged_turn_limit_does_not_generate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request after a turn limit was exceeded gets its error reply without a generation."""
    limit = turn_limit(0)

    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        limit,
        scaffold=_Scaffold([_Request(), _Request(after_first=True)]),
    )

    _assert_agent_limit(outcome, limit)
    _assert_error_replies(outcome.replies, count=2)
    # one generation of 7 tokens
    assert outcome.sample.model_usage["mockllm/model"].total_tokens == 7


def test_failure_after_a_bridged_limit_fails_the_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure a later generation requests ends the sample, not the recorded limit.

    The first request reaches the `run()` message limit. The second one's
    response filter fails, which fails the sample.
    """

    async def fails(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        raise ValueError("The response filter failed.")

    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        message_limit(2),
        scaffold=_Scaffold(
            [_Request(messages=2), _Request(after_first=True)],
            response_filter=fails,
        ),
    )

    sample = outcome.sample
    assert sample.error is not None
    assert "The response filter failed." in sample.error.message
    assert sample.limit is None
    assert "continued" not in sample.store
    assert outcome.errors == []


@pytest.mark.parametrize("recorded", [True, False], ids=("recorded", "no_record"))
def test_failure_before_a_cancellation_during_bridge_shutdown_fails_the_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded: bool
) -> None:
    """A requested failure unwinding the agent is not lost to a later cancellation.

    A response filter fails, which unwinds the agent. While the bridge kills
    the model proxy, a scope enclosing it is cancelled. The failure ends the
    sample whether or not an earlier request recorded a limit.
    """

    async def fails(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        raise ValueError("The response filter failed.")

    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        # the first request carries 2 messages: no room for a reply under 2
        message_limit(2 if recorded else 10),
        scaffold=_Scaffold(
            # the second reply never completes: only the failure ends the agent
            [_Request(messages=2), _Request(after_first=True, held=True)],
            response_filter=fails,
            cancel_on_kill=True,
        ),
    )

    sample = outcome.sample
    assert sample.error is not None
    assert "The response filter failed." in sample.error.message
    assert sample.limit is None
    assert "continued" not in sample.store
    assert outcome.errors == []


def test_enclosing_time_limit_during_a_bridged_limit_reply_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An enclosing time limit that cancels the agent after a limit's reply wins.

    The generation reaches the inner `run()` token limit, but the enclosing
    `run()` time limit expires while the reply is being written. The
    cancellation passes through unchanged, so the enclosing `run()` returns its
    time limit error; the recorded limit is not raised in its place.
    """
    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        token_limit(5),
        scaffold=_Scaffold([_Request(held=True)]),
        outer_limit=time_limit(0.5),
    )

    sample = outcome.sample
    assert sample.error is None, sample.error
    assert sample.limit is None
    assert sample.store.get("continued") is True
    assert outcome.errors == []
    [error] = outcome.outer_errors
    assert error is not None and error.type == "time"
    assert outcome.replies == []


def test_enclosing_time_limit_during_bridge_shutdown_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An enclosing time limit that expires while the bridge kills the proxy wins.

    The generation reaches the inner `run()` token limit and the agent returns
    after its reply. The enclosing `run()` time limit expires while the bridge
    is killing the model proxy, inside a shielded scope. The cancellation is
    delivered rather than replaced by the recorded limit, so the enclosing
    `run()` returns its time limit error.
    """
    outcome = _run_bridged_agent(
        tmp_path,
        monkeypatch,
        token_limit(5),
        scaffold=_Scaffold([_Request()], slow_kill=True),
        outer_limit=time_limit(0.5),
    )

    sample = outcome.sample
    assert sample.error is None, sample.error
    assert sample.limit is None
    assert sample.store.get("continued") is True
    assert outcome.errors == []
    [error] = outcome.outer_errors
    assert error is not None and error.type == "time"
    _assert_error_replies(outcome.replies)
