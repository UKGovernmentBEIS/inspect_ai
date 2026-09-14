"""Host-side tests for agent-bridge provider-error forwarding.

Covers the pieces that let the sandbox model proxy forward a provider error
instead of crashing: the `ModelGenerateError` wrapper (which preserves the
provider HTTP status), the `status_code_of` / `provider_error_payload`
extractors, and the `service.py` wrapper that turns an exception into a
`PROVIDER_ERROR_KEY` result.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import httpx2
import pytest
from anthropic import APIStatusError
from pydantic import JsonValue

import inspect_ai
from inspect_ai._util.http import status_code_of
from inspect_ai._util.registry import _registry
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge._errors import (
    PROVIDER_ERROR_KEY,
    provider_error_payload,
)
from inspect_ai.agent._bridge.sandbox import service as bridge_service
from inspect_ai.agent._bridge.sandbox.service import _forward_provider_errors
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelOutput, get_model
from inspect_ai.model._model import ModelAPI, ModelGenerateError, ModelRefusalError
from inspect_ai.model._providers.anthropic import (
    _ANTHROPIC_ERROR_TYPE_STATUS,
    AnthropicAPI,
    _normalize_stream_error,
)
from inspect_ai.model._registry import modelapi
from inspect_ai.util._limit import LimitExceededError


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
        ex = _anthropic_stream_error(error_type, "x")
        _normalize_stream_error(ex)
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
    ex = _anthropic_stream_error("some_future_error", "provider said no")
    _normalize_stream_error(ex)
    assert ex.status_code == 500
    assert ex.message == "provider said no"
    assert provider_error_payload(ex)["status"] == 500
    assert bool(api.should_retry(ex)) is False


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
    ex = APIStatusError(
        "mid-stream error",
        response=httpx2.Response(
            status_code=200,
            request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
        ),
        body=body,
    )
    _normalize_stream_error(ex)
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


def _bridge() -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
    )


async def test_forward_provider_errors_passes_success_through() -> None:
    async def ok(json_data: dict[str, Any]) -> dict[str, Any]:
        return {"id": "x", "choices": []}

    wrapped = _forward_provider_errors(ok, _bridge())
    assert await wrapped({}) == {"id": "x", "choices": []}


async def test_forward_provider_errors_returns_marker_on_exception() -> None:
    async def boom(json_data: dict[str, Any]) -> dict[str, Any]:
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

    async def boom(json_data: dict[str, Any]) -> dict[str, Any]:
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

    async def boom(json_data: dict[str, Any]) -> dict[str, Any]:
        raise ModelGenerateError("debug", status_code=503, provider_message="x")

    result = await _forward_provider_errors(boom, _bridge())({})
    assert result == {PROVIDER_ERROR_KEY: {"status": 503, "message": "x"}}
    assert warnings == []


async def test_forward_provider_errors_reraises_limit_exceeded_error() -> None:
    """A message/token/cost limit hit during generation must end the sample.

    Previously swallowed into a normal-looking provider-error response, which
    meant a sandboxed bridge's limit hits during model generation silently
    never terminated the sample.
    """

    async def boom(json_data: dict[str, Any]) -> dict[str, Any]:
        raise LimitExceededError("message", value=2, limit=1)

    with pytest.raises(LimitExceededError):
        await _forward_provider_errors(boom, _bridge())({})


async def test_forward_provider_errors_signals_refusal_to_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fail_on_refusal error ends the sample via the bridge, not via a raise.

    The sandbox service dispatcher would swallow a re-raise into an RPC error, so
    the wrapper hands the error to `bridge.request_fail` (raised on the agent's
    side by the bridge's monitor task) and still answers the scaffold with a
    provider error payload. It is not logged as a non-provider error, since the
    sample error is the report.
    """
    warnings: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        bridge_service.logger, "warning", lambda *a, **k: warnings.append((a, k))
    )
    refusal = ModelRefusalError(
        ModelOutput.from_content(
            model="mockllm/model", content="No.", stop_reason="content_filter"
        ),
        "mockllm/model",
    )

    async def boom(json_data: dict[str, Any]) -> dict[str, Any]:
        raise refusal

    bridge = _bridge()
    result = await _forward_provider_errors(boom, bridge)({})
    assert result == {PROVIDER_ERROR_KEY: {"status": None, "message": str(refusal)}}
    assert bridge._failure_requested.is_set()
    assert bridge._failure is refusal
    assert warnings == []


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
