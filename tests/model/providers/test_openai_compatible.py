from typing import Any, Literal

import httpx2
import pytest
from openai import (
    APIError,
    APIStatusError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
)
from openai.types.chat import ChatCompletionChunk
from test_helpers.utils import (
    skip_if_no_openai,
    skip_if_no_together,
    skip_if_no_together_base_url,
)

from inspect_ai._util.environ import environ_var
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    StopReason,
    StreamReasoningEvent,
    StreamTextEvent,
    StreamToolCallEvent,
    get_model,
)
from inspect_ai.model._openai import (
    OpenAIResponseError,
    chat_choices_from_openai,
    openai_chat_completion_stream_final,
    openai_handle_stream_error,
)
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI
from inspect_ai.model._providers.together import TogetherAIAPI
from inspect_ai.model._stream import ModelStreamObserver, model_stream_observer
from inspect_ai.tool import ToolInfo


@skip_if_no_together
@skip_if_no_together_base_url
async def test_openai_compatible() -> None:
    model = get_model(
        "openai-api/together/MiniMaxAI/MiniMax-M2.7",
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=50,
            presence_penalty=0.0,
            logit_bias=dict([(42, 10), (43, -10)]),
            seed=None,
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


@pytest.mark.parametrize("strict_tools", [True, False])
def test_strict_tools_model_arg(strict_tools: bool) -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        strict_tools=strict_tools,
    )

    tools = api.tools_to_openai([ToolInfo(name="test_tool", description="Test tool")])
    assert tools[0]["function"]["strict"] is strict_tools


def test_strict_tools_default_true() -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
    )

    tools = api.tools_to_openai([ToolInfo(name="test_tool", description="Test tool")])
    assert tools[0]["function"]["strict"] is True


async def test_responses_phase_model_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test responses_phase is an openai-api model arg, not an SDK arg."""
    captured: dict[str, Any] = {}

    async def mock_generate_responses(**kwargs: Any) -> ModelOutput:
        captured.update(kwargs)
        return ModelOutput.from_content(model="gpt-5", content="ok")

    monkeypatch.setattr(
        "inspect_ai.model._providers.openai_compatible.generate_responses",
        mock_generate_responses,
    )
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        responses_api=True,
        responses_phase=True,
    )
    try:
        assert api.responses_phase is True
        assert "responses_phase" not in api.model_args

        await api.generate(
            input=[ChatMessageUser(content="hi")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )
        assert captured["synthesize_phase"] is True
    finally:
        await api.aclose()


@skip_if_no_openai
async def test_openai_responses_compatible() -> None:
    with environ_var("OPENAI_BASE_URL", "https://api.openai.com/v1"):
        model = get_model("openai-api/openai/gpt-5", responses_api=True)
        message = ChatMessageUser(content="This is a test string. What are you?")
        response = await model.generate(input=[message])
        assert len(response.completion) >= 1


@pytest.mark.parametrize(
    ("status_code", "message", "stop_reason"),
    [
        pytest.param(
            400,
            "Requested input length 125000 exceeds maximum input length 40000",
            "model_length",
            id="deepinfra_model_length",
        ),
        pytest.param(400, "Bad Request", None, id="bad_request"),
        pytest.param(403, "Forbidden", None, id="forbidden"),
        pytest.param(500, "Internal Server Error", None, id="internal_server_error"),
    ],
)
def test_handle_bad_request(
    status_code: int, message: str, stop_reason: StopReason | None
) -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
    )
    error = APIStatusError(
        message=message,
        response=httpx2.Response(
            request=httpx2.Request(method="POST", url="https://example.com"),
            status_code=status_code,
            json={"message": message},
        ),
        body={"message": message},
    )
    response = api.handle_bad_request(error)
    if stop_reason:
        assert isinstance(response, ModelOutput)
        assert message in response.completion
        assert response.stop_reason == stop_reason
    else:
        assert isinstance(response, APIStatusError)


@pytest.mark.parametrize(
    ("body", "expected_stop_reason"),
    [
        pytest.param(
            {
                "message": "blocked",
                "code": "invalid_prompt",
                "type": "invalid_request_error",
            },
            "content_filter",
            id="invalid_prompt",
        ),
        pytest.param(
            {
                "message": "content issue",
                "code": "content_policy_violation",
                "type": "invalid_request_error",
            },
            "content_filter",
            id="content_policy_violation",
        ),
        pytest.param(
            {
                "message": "filtered",
                "code": "content_filter",
                "type": "server_error",
            },
            "content_filter",
            id="content_filter_azure",
        ),
        pytest.param(
            {
                "message": "Your request was blocked by safety",
                "code": "some_other_code",
                "type": "invalid_request_error",
            },
            "content_filter",
            id="invalid_request_blocked_message",
        ),
        pytest.param(
            {
                "message": "This request has been flagged for potentially high-risk cyber activity.",
                "code": "cyber_policy",
                "type": "invalid_request",  # This is the error type for 5.4
            },
            "content_filter",
            id="cyber_policy",
        ),
        pytest.param(
            {
                "message": "Something else entirely",
                "code": "some_other_code",
                "type": "invalid_request_error",
            },
            None,
            id="invalid_request_not_blocked",
        ),
    ],
)
def test_handle_bad_request_content_filter(
    body: dict[str, str], expected_stop_reason: StopReason | None
) -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
    )
    error = APIStatusError(
        message=body["message"],
        response=httpx2.Response(
            request=httpx2.Request(method="POST", url="https://example.com"),
            status_code=400,
            json=body,
        ),
        body=body,
    )
    response = api.handle_bad_request(error)
    if expected_stop_reason:
        assert isinstance(response, ModelOutput)
        assert response.stop_reason == expected_stop_reason
    else:
        assert isinstance(response, APIStatusError)


async def test_initialize_recreates_closed_http_client() -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
    )
    await api.http_client.aclose()
    assert api.http_client.is_closed
    api.initialize()
    assert not api.http_client.is_closed


def test_client_timeout_sets_http_timeout() -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        client_timeout=1800.0,
    )
    timeout = api.http_client.timeout
    assert timeout.read == 1800.0
    assert timeout.write == 1800.0
    assert timeout.pool == 1800.0
    # The connect deadline is floored at the shared default rather than pinned
    # to it, so a budget already above the floor carries through unchanged.
    assert timeout.connect == 1800.0


def test_client_timeout_default_uses_sdk_default() -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
    )
    # SDK default is 600s
    assert api.http_client.timeout.read == 600.0


@pytest.mark.anyio
async def test_client_timeout_preserved_after_reinitialize() -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        client_timeout=1800.0,
    )
    await api.http_client.aclose()
    assert api.http_client.is_closed
    api.initialize()
    assert not api.http_client.is_closed
    assert api.http_client.timeout.read == 1800.0
    assert api.http_client.timeout.connect == 1800.0


def test_user_supplied_http_client_not_overridden() -> None:
    custom_client = httpx2.AsyncClient(timeout=httpx2.Timeout(42.0))
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        client_timeout=1800.0,
        http_client=custom_client,
    )
    # user-supplied client should be used as-is
    assert api.http_client is custom_client
    assert api.http_client.timeout.read == 42.0


def _together_api(stream: bool | Literal["auto"] | None = None) -> TogetherAIAPI:
    return TogetherAIAPI(
        model_name="together/meta-llama/Llama-3.1-8B-Instruct-Turbo",
        api_key="test",
        base_url="https://example.com",
        stream=stream,
    )


def test_together_stream_defaults_to_auto() -> None:
    # unset stream is "auto": stream only when the caller passes on_stream
    api = _together_api()
    assert api.stream is None
    assert api.resolve_stream(GenerateConfig()) is False


@pytest.mark.parametrize("stream", [True, False])
def test_together_stream_model_arg_forwarded(stream: bool) -> None:
    assert _together_api(stream=stream).stream is stream


def test_stream_model_arg_normalized() -> None:
    # -M args are YAML-parsed, so -M stream=auto arrives as the string
    # "auto" — it must map to the auto sentinel (keeping the
    # auto_streamable guards in force), not a truthy explicit setting
    assert _together_api(stream="auto").stream is None
    # string bool spellings are accepted for non-YAML callers
    assert _together_api(stream="true").stream is True  # type: ignore[arg-type]
    assert _together_api(stream="False").stream is False  # type: ignore[arg-type]
    # a typo'd value raises rather than silently forcing streaming on or off
    with pytest.raises(ValueError, match="stream"):
        _together_api(stream="always")  # type: ignore[arg-type]


@skip_if_no_together
async def test_together_stream_end_to_end() -> None:
    # Use a generous max_tokens: reasoning models (e.g. gpt-oss) spend their
    # budget on the reasoning channel and emit no answer content if it is too
    # low, producing an empty completion (regardless of streaming).
    events: list[Any] = []

    async def collect(event: Any) -> None:
        events.append(event)

    model = get_model(
        "together/openai/gpt-oss-20b",
        stream=True,
        config=GenerateConfig(max_tokens=1024, temperature=0.0),
    )
    response = await model.generate(
        input=[ChatMessageUser(content="This is a test string. What are you?")],
        on_stream=collect,
    )
    assert len(response.completion) >= 1
    streamed = "".join(e.text for e in events if isinstance(e, StreamTextEvent))
    assert streamed == response.completion


class _FakeChunkStream:
    """A raw chunk stream as returned by `create(stream=True)`."""

    def __init__(self, chunks: list[ChatCompletionChunk]) -> None:
        self._chunks = chunks

    async def __aenter__(self) -> "_FakeChunkStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> Any:
        async def gen() -> Any:
            for chunk in self._chunks:
                yield chunk

        return gen()


async def test_openai_compatible_streaming_returns_partial_on_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A length-truncated stream returns the partial completion, like non-streaming.

    The SDK's final parse raises LengthFinishReasonError (carrying the
    accumulated snapshot); the streaming path recovers it.
    """
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        stream=True,
    )

    chunks = [
        _chunk(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(role="assistant", content="truncated"),
                        finish_reason=None,
                    )
                ]
            )
        ),
        _chunk(dict(choices=[dict(index=0, delta=dict(), finish_reason="length")])),
    ]

    async def fake_create(**kwargs: Any) -> _FakeChunkStream:
        return _FakeChunkStream(chunks)

    monkeypatch.setattr(api.client.chat.completions, "create", fake_create)

    try:
        result = await api._generate_completion({}, GenerateConfig())
        assert result.choices[0].message.content == "truncated"
        assert chat_choices_from_openai(result, [])[0].stop_reason == "max_tokens"
    finally:
        await api.aclose()


async def test_openai_compatible_streaming_returns_snapshot_on_content_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A content-filtered stream returns the snapshot, like non-streaming.

    The SDK's final parse raises ContentFilterFinishReasonError (with no
    payload) after recording finish_reason and any partial content on the
    snapshot; the streaming path recovers via the snapshot.
    """
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        stream=True,
    )

    chunks = [
        _chunk(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(role="assistant", content="partial"),
                        finish_reason=None,
                    )
                ]
            )
        ),
        _chunk(
            dict(choices=[dict(index=0, delta=dict(), finish_reason="content_filter")])
        ),
    ]

    async def fake_create(**kwargs: Any) -> _FakeChunkStream:
        return _FakeChunkStream(chunks)

    monkeypatch.setattr(api.client.chat.completions, "create", fake_create)

    try:
        result = await api._generate_completion({}, GenerateConfig())
        assert result.choices[0].message.content == "partial"
        assert chat_choices_from_openai(result, [])[0].stop_reason == "content_filter"
    finally:
        await api.aclose()


def _mid_stream_error(body: dict[str, Any]) -> APIError:
    """The exception the SDK's stream iterator raises for an error event: a plain APIError."""
    return APIError(
        message=str(body.get("message")),
        request=httpx2.Request(method="POST", url="https://example.com"),
        body=body,
    )


class _ErroringChunkStream(_FakeChunkStream):
    """A chunk stream that raises mid-iteration, like the SDK on error events."""

    def __init__(self, chunks: list[ChatCompletionChunk], error: APIError) -> None:
        super().__init__(chunks)
        self._error = error

    def __aiter__(self) -> Any:
        async def gen() -> Any:
            for chunk in self._chunks:
                yield chunk
            raise self._error

        return gen()


async def test_openai_compatible_streaming_converts_mid_stream_safeguard_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A safeguard block raised mid-stream becomes content_filter output (like the 400 path)."""
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        stream=True,
    )

    stream = _ErroringChunkStream(
        [
            _chunk(
                dict(
                    choices=[
                        dict(
                            index=0,
                            delta=dict(role="assistant", content="par"),
                            finish_reason=None,
                        )
                    ]
                )
            )
        ],
        _mid_stream_error(
            dict(
                message="Your prompt was blocked by our content policy.",
                type="invalid_request_error",
                code="content_policy_violation",
            )
        ),
    )

    async def fake_create(**kwargs: Any) -> _ErroringChunkStream:
        return stream

    monkeypatch.setattr(api.client.chat.completions, "create", fake_create)

    try:
        result = await api.generate(
            input=[ChatMessageUser(content="hi")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )
        assert isinstance(result, tuple)
        output, model_call = result
        assert isinstance(output, ModelOutput)
        assert output.choices[0].stop_reason == "content_filter"
        assert "blocked" in output.completion
        assert model_call.error is True
    finally:
        await api.aclose()


async def test_openai_compatible_streaming_raises_unrecognized_mid_stream_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mid-stream error that isn't a recognized block still raises."""
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        stream=True,
    )

    error = _mid_stream_error(
        dict(message="The server had an error.", type="server_error")
    )

    async def fake_create(**kwargs: Any) -> _ErroringChunkStream:
        return _ErroringChunkStream([], error)

    monkeypatch.setattr(api.client.chat.completions, "create", fake_create)

    try:
        with pytest.raises(APIError) as excinfo:
            await api.generate(
                input=[ChatMessageUser(content="hi")],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
            )
        assert excinfo.value is error
    finally:
        await api.aclose()


def test_openai_handle_stream_error_ignores_status_errors() -> None:
    """Status errors are never converted mid-stream; they keep retry semantics."""
    status_error = APIStatusError(
        message="blocked",
        response=httpx2.Response(
            status_code=429,
            request=httpx2.Request(method="POST", url="https://example.com"),
        ),
        body=dict(message="blocked", code="content_policy_violation"),
    )
    assert openai_handle_stream_error("gpt-5", status_error) is None

    converted = openai_handle_stream_error(
        "gpt-5",
        _mid_stream_error(dict(message="blocked", code="content_policy_violation")),
    )
    assert isinstance(converted, ModelOutput)
    assert converted.choices[0].stop_reason == "content_filter"


def test_openai_handle_stream_error_converts_response_errors() -> None:
    """Responses-API error events (OpenAIResponseError) convert by block code.

    Unrecognized codes return None so `server_error`/`rate_limit_exceeded`
    keep their retry classification.
    """
    converted = openai_handle_stream_error(
        "gpt-5",
        OpenAIResponseError(code="content_policy_violation", message="blocked"),
    )
    assert isinstance(converted, ModelOutput)
    assert converted.choices[0].stop_reason == "content_filter"

    unrecognized = openai_handle_stream_error(
        "gpt-5", OpenAIResponseError(code="server_error", message="oops")
    )
    assert unrecognized is None


def test_sdk_stream_state_contract() -> None:
    """The SDK contracts the stream accumulation and recovery depend on.

    `openai_chat_completion_stream_final` accumulates with a bare
    `ChatCompletionStreamState` (no input_tools/response_format — the
    resource-level `.stream()` helper instead rejects any function tool
    without `strict: true` before sending the request). It relies on:
    `handle_chunk` never raising for finish reasons without parseable
    input, `get_final_completion` raising on length/content_filter, the
    LengthFinishReasonError carrying the accumulated snapshot, and the
    state's snapshot recording finish_reason and partial content for the
    payload-less ContentFilterFinishReasonError.
    """
    from openai.lib.streaming.chat import ChatCompletionStreamState

    def accumulate(finish_reason: str) -> Any:
        state: Any = ChatCompletionStreamState()
        content = dict(role="assistant", content="par")
        # non-strict tool deltas accumulate without validation errors
        tool_delta = dict(
            tool_calls=[
                dict(
                    index=0,
                    type="function",
                    id="call_1",
                    function=dict(name="bash", arguments="{}"),
                )
            ]
        )
        for delta, finish in [(content, None), (tool_delta, finish_reason)]:
            list(
                state.handle_chunk(
                    _chunk(
                        dict(choices=[dict(index=0, delta=delta, finish_reason=finish)])
                    )
                )
            )
        return state

    state = accumulate("content_filter")
    with pytest.raises(ContentFilterFinishReasonError):
        state.get_final_completion()
    snapshot = state.current_completion_snapshot
    assert snapshot.choices[0].finish_reason == "content_filter"
    assert snapshot.choices[0].message.content == "par"

    state = accumulate("length")
    with pytest.raises(LengthFinishReasonError) as excinfo:
        state.get_final_completion()
    assert excinfo.value.completion.choices[0].message.content == "par"


# -- Stream observer reporting (on_stream) -------------------------------------


class _StreamCollector:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def __call__(self, event: Any) -> None:
        self.events.append(event)


def _compatible_api(stream: bool | None = None) -> OpenAICompatibleAPI:
    return OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        stream=stream,
    )


def test_resolve_stream_honors_on_stream() -> None:
    """Unset stream is "auto": stream iff the caller passed on_stream."""
    config = GenerateConfig()
    collector = _StreamCollector()

    api = _compatible_api()
    assert api.stream is None
    assert api.resolve_stream(config) is False
    with model_stream_observer(ModelStreamObserver("test", collector)):
        assert api.resolve_stream(config) is True

    # explicit opt-out wins over an on_stream callback
    with model_stream_observer(ModelStreamObserver("test", collector)):
        assert _compatible_api(stream=False).resolve_stream(config) is False

    # explicit opt-in streams without a callback
    assert _compatible_api(stream=True).resolve_stream(config) is True


def _chunk(payload: dict[str, Any]) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        dict(
            id="chatcmpl-1",
            object="chat.completion.chunk",
            created=0,
            model="gpt-5",
        )
        | payload
    )


async def test_chat_completion_stream_reports_deltas() -> None:
    """The shared stream consumer reports chunk deltas to on_stream.

    Also verifies the final completion is accumulated from the raw chunks
    (content, non-strict tool call, finish_reason, and usage).
    """
    reasoning_delta = dict(role="assistant", reasoning_content="hmm")
    text_delta = dict(content="hel")
    tool_delta = dict(
        tool_calls=[
            dict(
                index=0,
                type="function",
                id="call_1",
                function=dict(name="bash", arguments="{"),
            )
        ]
    )
    # continuation fragment: id/name arrive only on a call's first fragment
    tool_continuation_delta = dict(
        tool_calls=[dict(index=0, function=dict(arguments='"cmd": "ls"}'))]
    )
    usage = dict(prompt_tokens=3, completion_tokens=7, total_tokens=10)
    chunks = [
        _chunk(
            dict(choices=[dict(index=0, delta=reasoning_delta, finish_reason=None)])
        ),
        _chunk(dict(choices=[dict(index=0, delta=text_delta, finish_reason=None)])),
        _chunk(dict(choices=[dict(index=0, delta=tool_delta, finish_reason=None)])),
        _chunk(
            dict(
                choices=[
                    dict(index=0, delta=tool_continuation_delta, finish_reason="stop")
                ]
            )
        ),
        # final usage chunk (stream_options.include_usage)
        _chunk(dict(choices=[], usage=usage)),
    ]

    fake_stream: Any = _FakeChunkStream(chunks)
    collector = _StreamCollector()
    observer = ModelStreamObserver("test", collector)
    with model_stream_observer(observer):
        result = await openai_chat_completion_stream_final(fake_stream)

    # the final completion was accumulated from the chunks
    choice = result.choices[0]
    assert choice.message.content == "hel"
    assert choice.finish_reason == "stop"
    tool_calls = choice.message.tool_calls
    assert tool_calls is not None and tool_calls[0].id == "call_1"
    assert tool_calls[0].type == "function"
    assert tool_calls[0].function.arguments == '{"cmd": "ls"}'
    assert result.usage is not None and result.usage.completion_tokens == 7

    assert [type(e) for e in collector.events] == [
        StreamReasoningEvent,
        StreamTextEvent,
        StreamToolCallEvent,
        StreamToolCallEvent,
    ]
    assert collector.events[0].reasoning == "hmm"
    assert collector.events[1].text == "hel"
    tool_event = collector.events[2]
    assert tool_event.id == "call_1"
    assert tool_event.function == "bash"
    assert tool_event.arguments == "{"
    # the continuation fragment is attributed to its call (id/name are
    # remembered from the first fragment)
    continuation_event = collector.events[3]
    assert continuation_event.id == "call_1"
    assert continuation_event.function == "bash"
    assert continuation_event.arguments == '"cmd": "ls"}'
    # the usage chunk reported cumulative output tokens
    assert observer._tokens_current == 7


async def test_chat_completion_stream_gated_without_on_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an on_stream consumer only usage/heartbeat progress runs.

    Explicit stream=true callers (and providers that stream by default)
    stream without asking for stream events, so delta construction
    (on_stream support code) must not run for them.
    """
    import inspect_ai.model._openai as openai_module

    async def fail(delta: object) -> None:
        raise AssertionError("delta reported without an on_stream consumer")

    monkeypatch.setattr(openai_module, "report_model_stream_delta", fail)

    usage = dict(prompt_tokens=3, completion_tokens=7, total_tokens=10)
    chunks = [
        _chunk(
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
        _chunk(
            dict(
                choices=[dict(index=0, delta=dict(content="lo"), finish_reason="stop")]
            )
        ),
        _chunk(dict(choices=[], usage=usage)),
    ]

    fake_stream: Any = _FakeChunkStream(chunks)
    observer = ModelStreamObserver("test", None)
    with model_stream_observer(observer):
        result = await openai_chat_completion_stream_final(fake_stream)

    # response assembly and the usage progress channel are unaffected
    assert result.choices[0].message.content == "hello"
    assert observer._tokens_current == 7


async def test_chat_completion_stream_empty_raises() -> None:
    """A zero-chunk stream raises a descriptive, retryable error, not a bare assert."""
    from inspect_ai.model._stream import NoStreamDataError

    fake_stream: Any = _FakeChunkStream([])
    with pytest.raises(NoStreamDataError, match="without delivering any chunks"):
        await openai_chat_completion_stream_final(fake_stream)


async def test_streaming_requests_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Streaming requests ask for usage on the final chunk (include_usage).

    Goes through generate() to also verify the logged ModelCall request
    matches the wire request (stream_options is added before the snapshot).
    """
    api = _compatible_api()  # stream unset ("auto")

    chunks = [
        _chunk(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(role="assistant", content="ok"),
                        finish_reason="stop",
                    )
                ]
            )
        ),
    ]

    captured: dict[str, Any] = {}

    async def fake_create(**kwargs: Any) -> _FakeChunkStream:
        captured.update(kwargs)
        return _FakeChunkStream(chunks)

    monkeypatch.setattr(api.client.chat.completions, "create", fake_create)

    async def collect(event: Any) -> None:
        pass

    try:
        with model_stream_observer(ModelStreamObserver("test", collect)):
            result = await api.generate(
                input=[ChatMessageUser(content="hi")],
                tools=[],
                tool_choice="none",
                config=GenerateConfig(),
            )
        assert isinstance(result, tuple)
        output, model_call = result
        assert isinstance(output, ModelOutput)
        assert output.completion == "ok"
        assert captured["stream"] is True
        assert captured["stream_options"] == {"include_usage": True}
        # the logged request matches what was sent on the wire
        assert model_call.request["stream"] is True
        assert model_call.request["stream_options"] == {"include_usage": True}
    finally:
        await api.aclose()


def test_resolve_stream_declines_prompt_logprobs() -> None:
    """Auto mode declines to stream when prompt_logprobs is requested.

    The streaming path drops prompt_logprobs, and a display-only on_stream
    request must not degrade results (an explicit opt-in still streams,
    with a warning).
    """
    config = GenerateConfig(prompt_logprobs=1)
    collector = _StreamCollector()
    with model_stream_observer(ModelStreamObserver("test", collector)):
        assert _compatible_api().resolve_stream(config) is False
        assert _compatible_api(stream=True).resolve_stream(config) is True


def test_together_resolve_stream_excludes_batching() -> None:
    """Batching and streaming are mutually exclusive.

    A batched request never streams (and so never carries stream_options
    in its logged ModelCall).
    """
    config = GenerateConfig(batch=True)
    collector = _StreamCollector()
    with model_stream_observer(ModelStreamObserver("test", collector)):
        assert _together_api().resolve_stream(config) is False
        assert _together_api(stream=True).resolve_stream(config) is False


def test_together_resolve_stream_declines_logprobs() -> None:
    """Auto mode declines to stream when logprobs is requested.

    Together's native tokens/token_logprobs shape is not carried into
    the final completion by the SDK stream accumulator, so a display-only
    on_stream request must not enable streaming (an explicit opt-in
    still streams).
    """
    config = GenerateConfig(logprobs=True)
    collector = _StreamCollector()
    with model_stream_observer(ModelStreamObserver("test", collector)):
        assert _together_api().resolve_stream(config) is False
        assert _together_api(stream=True).resolve_stream(config) is True
        # logprobs unset still auto-streams
        assert _together_api().resolve_stream(GenerateConfig()) is True


def test_perplexity_resolve_stream_declines_auto() -> None:
    """Perplexity never auto-streams from an on_stream callback alone.

    Its citations/usage extras arrive as top-level response fields that
    the SDK stream accumulator drops (an explicit opt-in still streams).
    """
    from inspect_ai.model._providers.perplexity import PerplexityAPI

    def perplexity_api(stream: bool | None = None) -> PerplexityAPI:
        return PerplexityAPI(
            model_name="perplexity/sonar",
            api_key="test",
            base_url="https://example.com",
            stream=stream,
        )

    config = GenerateConfig()
    collector = _StreamCollector()
    with model_stream_observer(ModelStreamObserver("test", collector)):
        assert perplexity_api().resolve_stream(config) is False
        assert perplexity_api(stream=True).resolve_stream(config) is True


def test_openrouter_resolve_stream_declines_reasoning() -> None:
    """OpenRouter auto mode declines to stream reasoning-bearing requests.

    Whether the SDK stream accumulator reassembles OpenRouter's streamed
    reasoning_details losslessly is unverified against the live API, so a
    display-only on_stream request declines to stream when the request asks
    for reasoning (an explicit opt-in still streams).
    """
    from inspect_ai.model._providers.openrouter import OpenRouterAPI

    def openrouter_api(
        stream: bool | None = None,
        model: str = "openrouter/anthropic/claude-sonnet-4",
        **model_args: Any,
    ) -> OpenRouterAPI:
        return OpenRouterAPI(
            model_name=model, api_key="test", stream=stream, **model_args
        )

    collector = _StreamCollector()
    with model_stream_observer(ModelStreamObserver("test", collector)):
        # no reasoning in play: auto-streams
        assert openrouter_api().resolve_stream(GenerateConfig()) is True
        # reasoning requested via config or model arg: declines (explicit
        # opt-in still streams)
        effort = GenerateConfig(reasoning_effort="medium")
        assert openrouter_api().resolve_stream(effort) is False
        assert openrouter_api(stream=True).resolve_stream(effort) is True
        tokens = GenerateConfig(reasoning_tokens=1024)
        assert openrouter_api().resolve_stream(tokens) is False
        assert (
            openrouter_api(reasoning_enabled=True).resolve_stream(GenerateConfig())
            is False
        )
        # the :thinking model variant enables reasoning without any config
        thinking = openrouter_api(
            model="openrouter/anthropic/claude-3.7-sonnet:thinking"
        )
        assert thinking.resolve_stream(GenerateConfig()) is False
        # reasoning explicitly disabled wins over effort/tokens
        assert openrouter_api(reasoning_enabled=False).resolve_stream(effort) is True
