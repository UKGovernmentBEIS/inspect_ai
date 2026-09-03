from typing import Any, Literal, cast

import httpx
import pytest
from groq import APIError, APIStatusError, APITimeoutError
from groq.types.chat import ChatCompletionChunk
from pydantic import BaseModel
from test_helpers.utils import skip_if_no_groq

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    ResponseSchema,
    RetryDecision,
    get_model,
)
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._providers.groq import (
    GroqAPI,
    GroqStreamError,
    chat_tool_choice,
    groq_completion_from_stream,
)
from inspect_ai.model._stream import (
    ModelStreamObserver,
    StreamReasoningEvent,
    StreamTextEvent,
    StreamToolCallEvent,
    model_stream_observer,
)
from inspect_ai.tool import ToolFunction
from inspect_ai.util import json_schema


@skip_if_no_groq
async def test_core_groq_api() -> None:
    model = get_model(
        "groq/openai/gpt-oss-20b",
        config=GenerateConfig(
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


def test_chat_tool_choice_any_maps_to_required() -> None:
    # Inspect's tool_choice "any" means "use at least one tool" (force a tool call). Groq is
    # OpenAI-compatible, where the value that forces a call is "required" ("auto" lets the
    # model skip the tool), matching the openai/azureai/bedrock/mistral providers.
    assert chat_tool_choice("any") == "required"


def test_chat_tool_choice_other_values_pass_through() -> None:
    assert chat_tool_choice("auto") == "auto"
    assert chat_tool_choice("none") == "none"
    assert chat_tool_choice(ToolFunction(name="my_tool")) == {
        "type": "function",
        "function": {"name": "my_tool"},
    }


class NounPhrase(BaseModel):
    noun_phrase: str


@skip_if_no_groq
async def test_groq_api_with_response_schema() -> None:
    model = get_model(
        "groq/openai/gpt-oss-20b",
        config=GenerateConfig(
            response_schema=ResponseSchema(
                name="noun_phrase_schema",
                json_schema=json_schema(NounPhrase),
                description="Noun Phrase",
                strict=True,
            ),
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


# -- Streaming (on_stream) ------------------------------------------------------


class _StreamCollector:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def __call__(self, event: Any) -> None:
        self.events.append(event)


def _groq_api(streaming: bool | str = "auto") -> GroqAPI:
    # -M args arrive untyped, so the helper takes any string and casts at the
    # boundary; tests below rely on that to exercise the runtime guard.
    return GroqAPI(
        model_name="llama-3.3-70b",
        api_key="test",
        streaming=cast(bool | Literal["auto"], streaming),
    )


def test_groq_resolve_streaming_honors_on_stream() -> None:
    """Unset streaming is "auto": stream iff the caller passed on_stream."""
    config = GenerateConfig()
    collector = _StreamCollector()

    api = _groq_api()
    assert api.streaming is None
    assert api.resolve_streaming(config) is False
    with model_stream_observer(ModelStreamObserver("test", collector)):
        assert api.resolve_streaming(config) is True

        # auto mode declines requests carrying a response_schema
        schema_config = GenerateConfig(
            response_schema=ResponseSchema(
                name="noun_phrase_schema", json_schema=json_schema(NounPhrase)
            )
        )
        assert api.resolve_streaming(schema_config) is False
        # ...but an explicit opt-in still streams them
        assert _groq_api(streaming=True).resolve_streaming(schema_config) is True

        # auto mode declines compound models (server-side executed_tools are
        # not carried by the stream accumulator)
        compound = GroqAPI(model_name="groq/compound", api_key="test")
        assert compound.resolve_streaming(config) is False

        # explicit opt-out wins over an on_stream callback
        assert _groq_api(streaming=False).resolve_streaming(config) is False

    # explicit opt-in streams without a callback
    assert _groq_api(streaming=True).resolve_streaming(config) is True

    # -M args are YAML-parsed so "auto" arrives as a string; a typo'd value
    # raises rather than silently forcing streaming on or off
    assert _groq_api(streaming="auto").streaming is None
    with pytest.raises(ValueError, match="streaming"):
        _groq_api(streaming="always")


def _groq_chunk(payload: dict[str, Any]) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        dict(
            id="chatcmpl-1",
            object="chat.completion.chunk",
            created=123,
            model="llama-3.3-70b",
        )
        | payload
    )


async def _chunk_iter(chunks: list[ChatCompletionChunk]) -> Any:
    for chunk in chunks:
        yield chunk


async def test_groq_completion_from_stream() -> None:
    """The stream accumulator reconstructs the completion and reports deltas."""
    chunks = [
        _groq_chunk(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(role="assistant", reasoning="hmm"),
                        finish_reason=None,
                    )
                ]
            )
        ),
        _groq_chunk(
            dict(choices=[dict(index=0, delta=dict(content="hel"), finish_reason=None)])
        ),
        _groq_chunk(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(
                            tool_calls=[
                                dict(
                                    index=0,
                                    type="function",
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
        # continuation fragment: id/name arrive only on a call's first fragment
        _groq_chunk(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(
                            tool_calls=[
                                dict(index=0, function=dict(arguments='"cmd": "ls"}'))
                            ]
                        ),
                        finish_reason="tool_calls",
                    )
                ]
            )
        ),
        # final chunk carries usage under x_groq
        _groq_chunk(
            dict(
                choices=[],
                x_groq=dict(
                    id="req_1",
                    usage=dict(prompt_tokens=3, completion_tokens=7, total_tokens=10),
                ),
            )
        ),
    ]

    collector = _StreamCollector()
    with model_stream_observer(ModelStreamObserver("test", collector)):
        completion = await groq_completion_from_stream(_chunk_iter(chunks))

    # final completion accumulated from the chunks
    choice = completion.choices[0]
    assert choice.message.reasoning == "hmm"
    assert choice.message.content == "hel"
    assert choice.finish_reason == "tool_calls"
    tool_calls = choice.message.tool_calls
    assert tool_calls is not None and tool_calls[0].id == "call_1"
    assert tool_calls[0].function.name == "bash"
    assert tool_calls[0].function.arguments == '{"cmd": "ls"}'
    assert completion.usage is not None and completion.usage.total_tokens == 10

    # deltas were reported to on_stream (with tool fragments attributed)
    assert [type(e) for e in collector.events] == [
        StreamReasoningEvent,
        StreamTextEvent,
        StreamToolCallEvent,
        StreamToolCallEvent,
    ]
    assert collector.events[0].reasoning == "hmm"
    assert collector.events[1].text == "hel"
    assert collector.events[2].arguments == "{"
    assert collector.events[3].id == "call_1"
    assert collector.events[3].function == "bash"
    assert collector.events[3].arguments == '"cmd": "ls"}'

    # the accumulated completion flows through existing response parsing
    api = _groq_api()
    choices = api._chat_choices_from_response(completion, [])
    assert choices[0].stop_reason == "tool_calls"


async def test_groq_completion_from_stream_empty() -> None:
    with pytest.raises(RuntimeError, match="without delivering any chunks"):
        await groq_completion_from_stream(_chunk_iter([]))


async def test_groq_completion_from_stream_error() -> None:
    """A chunk-level x_groq.error raises rather than truncating silently."""
    chunks = [
        _groq_chunk(
            dict(choices=[dict(index=0, delta=dict(content="hel"), finish_reason=None)])
        ),
        _groq_chunk(dict(choices=[], x_groq=dict(error="over capacity"))),
    ]
    with pytest.raises(GroqStreamError, match="stopped early: over capacity") as ex:
        await groq_completion_from_stream(_chunk_iter(chunks))

    # a stream stopped early (canonically "over capacity") is the same
    # transient condition a non-streamed request retries as a 429/503 —
    # auto-streaming must not turn it into a permanently failed sample
    decision = _groq_api().should_retry(ex.value)
    assert isinstance(decision, RetryDecision) and decision.retry is True


# -- Mid-stream error payloads (plain APIError) ---------------------------------


def _mid_stream_error(body: object) -> APIError:
    """The exception the SDK's stream iterator raises for an in-band error payload.

    A plain `APIError` with no status code; `body` is the payload's `error`
    value (the inner error object, or a bare string).
    """
    message = body.get("message") if isinstance(body, dict) else None
    return APIError(
        message=str(message) if message else "An error occurred during streaming",
        request=httpx.Request(
            "POST", "https://api.groq.com/openai/v1/chat/completions"
        ),
        body=body,
    )


class _ErroringChunkStream:
    """A chunk stream (as returned by `create(stream=True)`) that raises mid-iteration."""

    def __init__(self, chunks: list[ChatCompletionChunk], error: Exception) -> None:
        self._chunks = chunks
        self._error = error

    async def __aenter__(self) -> "_ErroringChunkStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> Any:
        async def gen() -> Any:
            for chunk in self._chunks:
                yield chunk
            raise self._error

        return gen()


_PARTIAL_CHUNK = _groq_chunk(
    dict(
        choices=[
            dict(
                index=0, delta=dict(role="assistant", content="par"), finish_reason=None
            )
        ]
    )
)


async def _generate_streamed(
    api: GroqAPI, stream: _ErroringChunkStream, monkeypatch: pytest.MonkeyPatch
) -> tuple[ModelOutput | Exception, ModelCall]:
    async def fake_create(**kwargs: Any) -> _ErroringChunkStream:
        assert kwargs.get("stream") is True
        return stream

    monkeypatch.setattr(api.client.chat.completions, "create", fake_create)
    return await api.generate(
        input=[ChatMessageUser(content="hi")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
    )


async def test_groq_mid_stream_transient_error_raises_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient in-band error propagates (not returned) so the retry loop sees it.

    The model layer treats an exception *returned* from generate() as terminal,
    so a retryable condition must be raised, and classified by should_retry.
    """
    api = _groq_api(streaming=True)
    error = _mid_stream_error(
        dict(message="Over capacity", type="internal_server_error")
    )
    try:
        with pytest.raises(APIError) as excinfo:
            await _generate_streamed(
                api, _ErroringChunkStream([_PARTIAL_CHUNK], error), monkeypatch
            )
        assert excinfo.value is error
        decision = api.should_retry(excinfo.value)
        assert isinstance(decision, RetryDecision) and decision.retry is True
    finally:
        await api.aclose()


async def test_groq_mid_stream_context_length_error_converts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A context-length rejection delivered in-band converts like the 400 path."""
    api = _groq_api(streaming=True)
    error = _mid_stream_error(
        dict(
            message="Please reduce the length of the messages or completion.",
            type="invalid_request_error",
            code="context_length_exceeded",
        )
    )
    try:
        output, model_call = await _generate_streamed(
            api, _ErroringChunkStream([], error), monkeypatch
        )
        assert isinstance(output, ModelOutput)
        assert output.choices[0].stop_reason == "model_length"
        assert "reduce the length" in output.completion
        assert model_call.error is True
        assert model_call.response == dict(
            message="Please reduce the length of the messages or completion.",
            type="invalid_request_error",
            code="context_length_exceeded",
        )
    finally:
        await api.aclose()


async def test_groq_mid_stream_unrecognized_error_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An in-band error that is neither transient nor a known rejection still fails."""
    api = _groq_api(streaming=True)
    error = _mid_stream_error(
        dict(
            message="Invalid API key",
            type="invalid_request_error",
            code="invalid_api_key",
        )
    )
    try:
        with pytest.raises(APIError) as excinfo:
            await _generate_streamed(
                api, _ErroringChunkStream([_PARTIAL_CHUNK], error), monkeypatch
            )
        assert excinfo.value is error
        decision = api.should_retry(excinfo.value)
        assert isinstance(decision, RetryDecision) and decision.retry is False
        # the failed request was closed out in the hooks bookkeeping
        assert api._http_hooks._requests == {}
    finally:
        await api.aclose()


async def test_groq_mid_stream_transient_error_drives_retry_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: the model layer retries a mid-stream over-capacity error."""
    from tenacity import wait_none

    model = get_model(
        "groq/llama-3.3-70b",
        api_key="test",
        streaming=True,
        config=GenerateConfig(max_retries=2),
    )
    api = model.api
    assert isinstance(api, GroqAPI)
    attempts: list[int] = []

    async def fake_create(**kwargs: Any) -> _ErroringChunkStream:
        attempts.append(1)
        return _ErroringChunkStream(
            [_PARTIAL_CHUNK],
            _mid_stream_error(
                dict(message="Over capacity", type="internal_server_error")
            ),
        )

    monkeypatch.setattr(api.client.chat.completions, "create", fake_create)
    monkeypatch.setattr(api, "retry_wait", lambda: wait_none())
    try:
        with pytest.raises(Exception):
            await model.generate([ChatMessageUser(content="hi")])
        assert len(attempts) == 3
    finally:
        await api.aclose()


async def test_groq_mid_stream_connection_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection errors raised while streaming keep their own classification."""
    api = _groq_api(streaming=True)
    error = APITimeoutError(
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    )
    try:
        with pytest.raises(APITimeoutError) as excinfo:
            await _generate_streamed(
                api, _ErroringChunkStream([_PARTIAL_CHUNK], error), monkeypatch
            )
        assert excinfo.value is error
        decision = api.should_retry(excinfo.value)
        assert isinstance(decision, RetryDecision) and decision.retry is True
    finally:
        await api.aclose()


def test_groq_handle_bad_request_status_errors() -> None:
    """Status errors: only a 400 is inspected, and its body is the full `{"error": ...}` payload."""
    api = _groq_api()
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    body = dict(
        error=dict(
            message="Please reduce the length of the messages or completion.",
            type="invalid_request_error",
            code="context_length_exceeded",
        )
    )

    def status_error(status: int) -> APIStatusError:
        return APIStatusError(
            message="Error code: 400",
            response=httpx.Response(status_code=status, request=request),
            body=body,
        )

    converted = api.handle_bad_request(status_error(400))
    assert isinstance(converted, ModelOutput)
    assert converted.choices[0].stop_reason == "model_length"
    assert "reduce the length" in converted.completion

    # a 400 that isn't a context-length rejection is returned unchanged
    other = APIStatusError(
        message="Error code: 400",
        response=httpx.Response(status_code=400, request=request),
        body=dict(error=dict(message="bad request", type="invalid_request_error")),
    )
    assert api.handle_bad_request(other) is other

    # conversion is a bad-request concern: other statuses pass through
    # unchanged whatever the body says (their retry handling lives elsewhere)
    unavailable = status_error(503)
    assert api.handle_bad_request(unavailable) is unavailable


async def test_groq_stream_gated_without_on_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an on_stream consumer only usage/heartbeat progress runs.

    Explicit streaming=true callers stream without asking for stream events,
    so delta construction (on_stream support code) must not run for them.
    """
    import inspect_ai.model._providers.groq as groq_module

    async def fail(delta: object) -> None:
        raise AssertionError("delta reported without an on_stream consumer")

    monkeypatch.setattr(groq_module, "report_model_stream_delta", fail)

    chunks = [
        _groq_chunk(
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
        _groq_chunk(
            dict(
                choices=[dict(index=0, delta=dict(content="lo"), finish_reason="stop")]
            )
        ),
        _groq_chunk(
            dict(
                choices=[],
                x_groq=dict(
                    id="req_1",
                    usage=dict(prompt_tokens=3, completion_tokens=7, total_tokens=10),
                ),
            )
        ),
    ]

    observer = ModelStreamObserver("test", None)
    with model_stream_observer(observer):
        completion = await groq_completion_from_stream(_chunk_iter(chunks))

    # response assembly and the usage progress channel are unaffected
    assert completion.choices[0].message.content == "hello"
    assert observer._tokens_current == 7


@skip_if_no_groq
async def test_groq_stream_end_to_end() -> None:
    """Passing on_stream alone enables streaming and reconstructs the output."""
    events: list[Any] = []

    async def collect(event: Any) -> None:
        events.append(event)

    model = get_model(
        "groq/openai/gpt-oss-20b",
        config=GenerateConfig(max_tokens=1024, temperature=0.0),
    )
    response = await model.generate(
        input=[ChatMessageUser(content="This is a test string. What are you?")],
        on_stream=collect,
    )
    assert len(response.completion) >= 1
    streamed = "".join(e.text for e in events if isinstance(e, StreamTextEvent))
    assert streamed == response.completion
