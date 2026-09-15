import json
from typing import Any, Literal, cast

import pytest
from azure.ai.inference.models import (
    AsyncStreamingChatCompletions,
    StreamingChatCompletionsUpdate,
)
from azure.core.exceptions import (
    HttpResponseError,
    IncompleteReadError,
    ServiceRequestError,
)
from test_helpers.tasks import minimal_task
from test_helpers.utils import skip_if_no_azureai

from inspect_ai import eval_async
from inspect_ai.model import GenerateConfig, Model, RetryDecision, get_model
from inspect_ai.model._providers.azureai import (
    AZURE_API_KEY,
    AZUREAI_API_KEY,
    AzureAIAPI,
    AzureAIStreamError,
    azureai_completion_from_stream,
    chat_complection_choice,
)
from inspect_ai.model._stream import (
    ModelStreamObserver,
    StreamTextEvent,
    StreamToolCallEvent,
    model_stream_observer,
)


def test_explicit_api_key_takes_precedence_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AZURE_API_KEY, "legacy-env-key")
    monkeypatch.setenv(AZUREAI_API_KEY, "env-key")

    api = AzureAIAPI(
        model_name="test-model",
        base_url="https://example.com/models",
        api_key="explicit-key",
    )

    assert api.api_key == "explicit-key"
    assert api.token_provider is None


def test_azureai_api_key_is_offered_to_override_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str]] = []

    def override_api_key(env_var_name: str, value: str) -> str:
        seen.append((env_var_name, value))
        return "overridden-key"

    monkeypatch.delenv(AZURE_API_KEY, raising=False)
    monkeypatch.setenv(AZUREAI_API_KEY, "source-key")
    monkeypatch.setattr(
        "inspect_ai.hooks._hooks.override_api_key",
        override_api_key,
    )

    api = AzureAIAPI(
        model_name="test-model",
        base_url="https://example.com/models",
    )

    assert seen == [(AZUREAI_API_KEY, "source-key")]
    assert api.api_key == "overridden-key"


@pytest.mark.anyio
@skip_if_no_azureai
async def test_azureai_api() -> None:
    model = get_azureai_model()
    message = "This is a test string. What are you?"
    response = await model.generate(input=message)
    assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_no_azureai
async def test_azureai_api_repeat_eval() -> None:
    model = get_azureai_model()
    _ = await eval_async(tasks=minimal_task, model=model)
    eval_log = await eval_async(tasks=minimal_task, model=model)
    assert eval_log[0].error is None, "Error on running consecutive evaluations"


def get_azureai_model() -> Model:
    return get_model(
        model="azureai/Llama-3.3-70B-Instruct",
        azure=True,
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=2,
            presence_penalty=0.0,
            seed=None,
            temperature=0.0,
            top_p=1.0,
        ),
    )


# -- Streaming (on_stream) ------------------------------------------------------


class _StreamCollector:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def __call__(self, event: Any) -> None:
        self.events.append(event)


def _azureai_api(streaming: bool | str = "auto") -> AzureAIAPI:
    # -M args arrive untyped, so the helper takes any string and casts at the
    # boundary; tests below rely on that to exercise the runtime guard.
    return AzureAIAPI(
        model_name="test-model",
        base_url="https://example.com/models",
        api_key="test",
        streaming=cast(bool | Literal["auto"], streaming),
    )


def test_azureai_resolve_streaming_honors_on_stream() -> None:
    """Unset streaming is "auto": stream iff the caller passed on_stream."""
    collector = _StreamCollector()

    api = _azureai_api()
    assert api.streaming is None
    assert api.resolve_streaming() is False
    with model_stream_observer(ModelStreamObserver("test", collector)):
        assert api.resolve_streaming() is True

        # explicit opt-out wins over an on_stream callback
        assert _azureai_api(streaming=False).resolve_streaming() is False

    # explicit opt-in streams without a callback
    assert _azureai_api(streaming=True).resolve_streaming() is True

    # -M args are YAML-parsed so "auto" arrives as a string; a typo'd value
    # raises rather than silently forcing streaming on or off
    assert _azureai_api(streaming="auto").streaming is None
    with pytest.raises(ValueError, match="streaming"):
        _azureai_api(streaming="always")


def _update(payload: dict[str, Any]) -> StreamingChatCompletionsUpdate:
    return StreamingChatCompletionsUpdate(
        dict(id="cmpl-1", created=123, model="test-model") | payload
    )


async def _updates(items: list[StreamingChatCompletionsUpdate]) -> Any:
    for item in items:
        yield item


async def test_azureai_completion_from_stream() -> None:
    """The stream accumulator reconstructs the completion and reports deltas."""
    updates = [
        _update(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(role="assistant", content="hel"),
                        finish_reason=None,
                    )
                ]
            )
        ),
        # tool call fragments carry no index: an id starts a new call and
        # bare argument fragments extend the latest one
        _update(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(
                            tool_calls=[
                                dict(
                                    id="call_1",
                                    function=dict(name="bash", arguments="{"),
                                )
                            ]
                        ),
                        finish_reason=None,
                    )
                ]
            )
        ),
        _update(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(
                            tool_calls=[dict(function=dict(arguments='"cmd": "ls"}'))]
                        ),
                        finish_reason="tool_calls",
                        content_filter_results=dict(
                            hate=dict(filtered=False, severity="safe")
                        ),
                    )
                ]
            )
        ),
        _update(
            dict(
                choices=[],
                usage=dict(prompt_tokens=3, completion_tokens=7, total_tokens=10),
            )
        ),
    ]

    collector = _StreamCollector()
    with model_stream_observer(ModelStreamObserver("test", collector)):
        response = await azureai_completion_from_stream(_updates(updates))

    # final completion accumulated from the updates
    choice = response.choices[0]
    assert choice.message.content == "hel"
    assert choice.finish_reason == "tool_calls"
    tool_calls = choice.message.tool_calls
    assert tool_calls is not None and tool_calls[0].id == "call_1"
    assert tool_calls[0].function.name == "bash"
    assert tool_calls[0].function.arguments == '{"cmd": "ls"}'
    assert response.usage.total_tokens == 10
    # undeclared per-choice fields carry into the synthesized response
    assert choice.get("content_filter_results") == dict(
        hate=dict(filtered=False, severity="safe")
    )

    # deltas were reported to on_stream (with tool fragments attributed)
    assert [type(e) for e in collector.events] == [
        StreamTextEvent,
        StreamToolCallEvent,
        StreamToolCallEvent,
    ]
    assert collector.events[0].text == "hel"
    assert collector.events[1].id == "call_1"
    assert collector.events[2].id == "call_1"
    assert collector.events[2].function == "bash"
    assert collector.events[2].arguments == '"cmd": "ls"}'


async def test_azureai_stream_gated_without_on_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an on_stream consumer only usage/heartbeat progress runs.

    Explicit streaming=true callers stream without asking for stream events,
    so delta construction (on_stream support code) must not run for them.
    """
    import inspect_ai.model._providers.azureai as azureai_module

    async def fail(delta: Any) -> None:
        raise AssertionError("delta reported without an on_stream consumer")

    monkeypatch.setattr(azureai_module, "report_model_stream_delta", fail)

    updates = [
        _update(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(role="assistant", content="hel"),
                        finish_reason=None,
                    )
                ]
            )
        ),
        _update(
            dict(
                choices=[dict(index=0, delta=dict(content="lo"), finish_reason="stop")]
            )
        ),
        _update(
            dict(
                choices=[],
                usage=dict(prompt_tokens=3, completion_tokens=7, total_tokens=10),
            )
        ),
    ]

    observer = ModelStreamObserver("test", None)
    with model_stream_observer(observer):
        response = await azureai_completion_from_stream(_updates(updates))

    # response assembly and the usage progress channel are unaffected
    assert response.choices[0].message.content == "hello"
    assert observer._tokens_current == 7


async def test_azureai_stream_parallel_tool_calls_by_index() -> None:
    """Interleaved fragments with wire indexes attribute to the right call."""
    updates = [
        _update(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(
                            role="assistant",
                            tool_calls=[
                                dict(
                                    index=0,
                                    id="call_a",
                                    function=dict(name="bash", arguments='{"a"'),
                                ),
                                dict(
                                    index=1,
                                    id="call_b",
                                    function=dict(name="python", arguments='{"b"'),
                                ),
                            ],
                        ),
                        finish_reason=None,
                    )
                ]
            )
        ),
        # continuation fragments carry only the index
        _update(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(
                            tool_calls=[
                                dict(index=0, function=dict(arguments=": 1}")),
                                dict(index=1, function=dict(arguments=": 2}")),
                            ]
                        ),
                        finish_reason="tool_calls",
                    )
                ]
            )
        ),
    ]

    response = await azureai_completion_from_stream(_updates(updates))
    tool_calls = response.choices[0].message.tool_calls
    assert tool_calls is not None and len(tool_calls) == 2
    assert tool_calls[0].id == "call_a"
    assert tool_calls[0].function.arguments == '{"a": 1}'
    assert tool_calls[1].id == "call_b"
    assert tool_calls[1].function.arguments == '{"b": 2}'


async def test_azureai_streamed_content_filter_stop_details() -> None:
    """A streamed content-filtered response surfaces stop details.

    The update carrying finish_reason="content_filter" also carries the
    content_filter_results for the filtered content; the accumulator keeps
    them on the synthesized choice where stop-details extraction (which
    reads the raw mapping for dict-backed azure models) finds them.
    """
    updates = [
        _update(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(role="assistant", content="par"),
                        finish_reason=None,
                    )
                ]
            )
        ),
        _update(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(),
                        finish_reason="content_filter",
                        content_filter_results=dict(
                            violence=dict(filtered=True, severity="high")
                        ),
                    )
                ]
            )
        ),
    ]

    response = await azureai_completion_from_stream(_updates(updates))
    choice = chat_complection_choice("test-model", response.choices[0], [], None)
    assert choice.stop_reason == "content_filter"
    assert choice.stop_details is not None
    assert choice.stop_details.type == "content_filter"
    assert choice.stop_details.categories is not None
    assert choice.stop_details.categories[0].category == "violence"
    assert choice.stop_details.categories[0].level == "high"


async def test_azureai_completion_from_stream_empty() -> None:
    """A stream delivering nothing (HTTP 200, then no choices) is retried."""
    with pytest.raises(
        AzureAIStreamError, match="without delivering any choices"
    ) as ex:
        await azureai_completion_from_stream(_updates([]))
    assert bool(_azureai_api().should_retry(ex.value)) is True


class _SSEResponse:
    """Stand-in for the azure-core async response the SDK stream reads from."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def iter_bytes(self) -> Any:
        yield self._body

    async def aclose(self) -> None:
        pass


def _sdk_stream(body: bytes) -> AsyncStreamingChatCompletions:
    """A real SDK update stream over a canned SSE body (HTTP 200)."""
    return AsyncStreamingChatCompletions(cast(Any, _SSEResponse(body)))


def _sse(payload: dict[str, Any], event: str | None = None) -> bytes:
    frame = f"data: {json.dumps(payload)}\n\n"
    return ((f"event: {event}\n" if event else "") + frame).encode()


_CHUNK = dict(
    id="cmpl-1",
    created=123,
    model="test-model",
    choices=[dict(index=0, delta=dict(content="hel"), finish_reason=None)],
)


async def test_azureai_stream_error_event_retries() -> None:
    """An `event: error` frame mid-stream is retried rather than failing.

    azure-ai-inference rejects any non-`data:` SSE line with a bare
    `ValueError` (it has no error-event handling), which `should_retry`
    could not otherwise recognise.
    """
    body = _sse(_CHUNK) + _sse(dict(error=dict(message="over capacity")), event="error")
    with pytest.raises(AzureAIStreamError, match="could not be read") as ex:
        await azureai_completion_from_stream(_sdk_stream(body))
    assert isinstance(ex.value.__cause__, ValueError)

    decision = _azureai_api().should_retry(ex.value)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True and decision.kind == "transient"


@pytest.mark.parametrize(
    ("body", "match"),
    [
        # an SSE comment (keep-alive)
        (b": keep-alive\n\n" + _sse(_CHUNK), "SSE event not supported"),
        # a non-error event name on every frame
        (_sse(_CHUNK, event="message"), "SSE event not supported"),
        # malformed JSON on a complete line
        (_sse(_CHUNK) + b'data: {"id": "cmpl-1", "choi\n', "Unterminated string"),
    ],
)
async def test_azureai_stream_unreadable_line_not_retried(
    body: bytes, match: str
) -> None:
    """An SSE line the SDK cannot read at all fails permanently.

    Retrying would burn the whole retry budget against an endpoint the SDK is
    incompatible with, so the SDK's own error propagates unchanged.
    """
    with pytest.raises(ValueError, match=match) as ex:
        await azureai_completion_from_stream(_sdk_stream(body))
    assert not isinstance(ex.value, AzureAIStreamError)
    assert bool(_azureai_api().should_retry(ex.value)) is False


async def test_azureai_stream_dropped_error_frame_retries() -> None:
    """An OpenAI-style `data: {"error": ...}` frame must not yield empty output.

    The SDK parses the frame and then drops it (no choices, no usage), so the
    accumulator only sees a stream whose choice never reached a finish
    reason — previously returned as a successful, truncated completion.
    """
    body = (
        _sse(_CHUNK)
        + _sse(dict(error=dict(message="over capacity", code=503)))
        + b"data: [DONE]\n"
    )
    with pytest.raises(
        AzureAIStreamError, match="without delivering a finish reason"
    ) as ex:
        await azureai_completion_from_stream(_sdk_stream(body))
    assert bool(_azureai_api().should_retry(ex.value)) is True

    # a stream that does reach a finish reason is unaffected
    finished = dict(_CHUNK, choices=[dict(index=0, delta=dict(), finish_reason="stop")])
    response = await azureai_completion_from_stream(
        _sdk_stream(_sse(_CHUNK) + _sse(finished) + b"data: [DONE]\n")
    )
    assert response.choices[0].message.content == "hel"
    assert response.choices[0].finish_reason == "stop"


def test_azureai_should_retry_stream_connection_drop() -> None:
    """A connection dropped mid-body is an HttpResponseError with no status."""
    api = _azureai_api()
    ex = IncompleteReadError("Connection broken: IncompleteRead")
    assert ex.status_code is None
    decision = api.should_retry(ex)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True and decision.kind == "transient"
    # a server disconnect while streaming maps to ServiceRequestError
    assert bool(api.should_retry(ServiceRequestError("Server disconnected"))) is True
    # unrelated errors stay unretried
    assert bool(api.should_retry(ValueError("unrelated"))) is False
    assert bool(api.should_retry(HttpResponseError("no status"))) is False


@pytest.mark.anyio
@skip_if_no_azureai
async def test_azureai_stream_end_to_end() -> None:
    """Passing on_stream alone enables streaming and reconstructs the output."""
    events: list[Any] = []

    async def collect(event: Any) -> None:
        events.append(event)

    model = get_model(
        model="azureai/Llama-3.3-70B-Instruct",
        azure=True,
        config=GenerateConfig(max_tokens=64, temperature=0.0),
    )
    response = await model.generate(
        input="This is a test string. What are you?", on_stream=collect
    )
    assert len(response.completion) >= 1
    streamed = "".join(e.text for e in events if isinstance(e, StreamTextEvent))
    assert streamed == response.completion
