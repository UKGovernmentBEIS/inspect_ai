from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from openai import (
    APIStatusError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
)
from openai.types.chat import ChatCompletion, ChatCompletionChunk
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
    chat_choices_from_openai,
    openai_chat_completion_stream_final,
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
    assert timeout.connect == 5.0


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
    assert api.http_client.timeout.connect == 5.0


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


def _together_api(stream: bool | None = None) -> TogetherAIAPI:
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


@skip_if_no_together
async def test_together_stream_end_to_end() -> None:
    # Use a generous max_tokens: reasoning models (e.g. gpt-oss) spend their
    # budget on the reasoning channel and emit no answer content if it is too
    # low, producing an empty completion (regardless of streaming).
    model = get_model(
        "together/openai/gpt-oss-20b",
        stream=True,
        config=GenerateConfig(max_tokens=1024, temperature=0.0),
    )
    response = await model.generate(
        input=[ChatMessageUser(content="This is a test string. What are you?")]
    )
    assert len(response.completion) >= 1


async def test_openai_compatible_streaming_returns_partial_on_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        stream=True,
    )

    partial = ChatCompletion.model_validate(
        {
            "id": "partial",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-5",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "length",
                    "message": {"role": "assistant", "content": "truncated"},
                }
            ],
        }
    )

    class _LengthTruncatedStream:
        async def __aenter__(self) -> "_LengthTruncatedStream":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        def __aiter__(self) -> "_LengthTruncatedStream":
            return self

        async def __anext__(self) -> object:
            raise StopAsyncIteration

        async def get_final_completion(self) -> ChatCompletion:
            raise LengthFinishReasonError(completion=partial)

    monkeypatch.setattr(
        api.client.chat.completions,
        "stream",
        lambda **kwargs: _LengthTruncatedStream(),
    )

    try:
        result = await api._generate_completion({}, GenerateConfig())
        assert result is partial
        assert chat_choices_from_openai(result, [])[0].stop_reason == "max_tokens"
    finally:
        await api.aclose()


async def test_openai_compatible_streaming_returns_snapshot_on_content_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A content-filtered stream returns the snapshot, like non-streaming.

    With strict tools/response_format in play the SDK raises
    ContentFilterFinishReasonError mid-stream (with no payload) after
    recording finish_reason and any partial content on the snapshot.
    """
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        stream=True,
    )

    snapshot = ChatCompletion.model_validate(
        {
            "id": "snapshot",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-5",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "content_filter",
                    "message": {"role": "assistant", "content": "partial"},
                }
            ],
        }
    )

    class _ContentFilteredStream:
        current_completion_snapshot = snapshot

        async def __aenter__(self) -> "_ContentFilteredStream":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        def __aiter__(self) -> "_ContentFilteredStream":
            return self

        async def __anext__(self) -> object:
            raise ContentFilterFinishReasonError()

    monkeypatch.setattr(
        api.client.chat.completions,
        "stream",
        lambda **kwargs: _ContentFilteredStream(),
    )

    try:
        result = await api._generate_completion({}, GenerateConfig())
        assert result is snapshot
        assert chat_choices_from_openai(result, [])[0].stop_reason == "content_filter"
    finally:
        await api.aclose()


def test_sdk_stream_state_content_filter_contract() -> None:
    """The SDK contract the content-filter recovery depends on.

    `openai_chat_completion_stream_final` returns
    `stream.current_completion_snapshot` when the SDK raises
    ContentFilterFinishReasonError, relying on the SDK recording
    finish_reason (and partial content) on the snapshot before raising —
    which it does only with parseable input (strict tools) in play.
    """
    from openai.lib.streaming.chat import ChatCompletionStreamState

    strict_tool: Any = {
        "type": "function",
        "function": {
            "name": "bash",
            "parameters": {"type": "object", "properties": {}},
            "strict": True,
        },
    }
    state = ChatCompletionStreamState(input_tools=[strict_tool], response_format=None)

    def chunk(payload: dict[str, Any]) -> ChatCompletionChunk:
        return ChatCompletionChunk.model_validate(
            dict(id="c1", object="chat.completion.chunk", created=0, model="gpt-5")
            | payload
        )

    content = dict(role="assistant", content="par")
    list(
        state.handle_chunk(
            chunk(dict(choices=[dict(index=0, delta=content, finish_reason=None)]))
        )
    )
    with pytest.raises(ContentFilterFinishReasonError):
        list(
            state.handle_chunk(
                chunk(
                    dict(
                        choices=[
                            dict(index=0, delta=dict(), finish_reason="content_filter")
                        ]
                    )
                )
            )
        )
    snapshot = state.current_completion_snapshot
    assert snapshot.choices[0].finish_reason == "content_filter"
    assert snapshot.choices[0].message.content == "par"


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
    """The shared stream consumer reports chunk deltas to on_stream."""
    reasoning_delta = dict(role="assistant", reasoning_content="hmm")
    text_delta = dict(content="hel")
    tool_delta = dict(
        tool_calls=[
            dict(index=0, id="call_1", function=dict(name="bash", arguments="{"))
        ]
    )
    usage = dict(prompt_tokens=3, completion_tokens=7, total_tokens=10)
    chunks = [
        _chunk(
            dict(choices=[dict(index=0, delta=reasoning_delta, finish_reason=None)])
        ),
        _chunk(dict(choices=[dict(index=0, delta=text_delta, finish_reason=None)])),
        _chunk(dict(choices=[dict(index=0, delta=tool_delta, finish_reason=None)])),
        # final usage chunk (stream_options.include_usage)
        _chunk(dict(choices=[], usage=usage)),
    ]

    final = ChatCompletion.model_validate(
        dict(
            id="chatcmpl-1",
            object="chat.completion",
            created=0,
            model="gpt-5",
            choices=[
                dict(
                    index=0,
                    finish_reason="stop",
                    message=dict(role="assistant", content="hello"),
                )
            ],
        )
    )

    class _FakeStream:
        def __aiter__(self) -> Any:
            async def gen() -> Any:
                for chunk in chunks:
                    yield SimpleNamespace(type="chunk", chunk=chunk)

            return gen()

        async def get_final_completion(self) -> ChatCompletion:
            return final

    fake_stream: Any = _FakeStream()
    collector = _StreamCollector()
    observer = ModelStreamObserver("test", collector)
    with model_stream_observer(observer):
        result = await openai_chat_completion_stream_final(fake_stream)

    assert result is final
    assert [type(e) for e in collector.events] == [
        StreamReasoningEvent,
        StreamTextEvent,
        StreamToolCallEvent,
    ]
    assert collector.events[0].reasoning == "hmm"
    assert collector.events[1].text == "hel"
    tool_event = collector.events[2]
    assert tool_event.id == "call_1"
    assert tool_event.function == "bash"
    assert tool_event.arguments == "{"
    # the usage chunk reported cumulative output tokens
    assert observer._tokens_current == 7


async def test_streaming_requests_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Streaming requests ask for usage on the final chunk (include_usage).

    Goes through generate() to also verify the logged ModelCall request
    matches the wire request (stream_options is added before the snapshot).
    """
    api = _compatible_api()  # stream unset ("auto")

    final = ChatCompletion.model_validate(
        dict(
            id="chatcmpl-1",
            object="chat.completion",
            created=0,
            model="gpt-5",
            choices=[
                dict(
                    index=0,
                    finish_reason="stop",
                    message=dict(role="assistant", content="ok"),
                )
            ],
        )
    )

    captured: dict[str, Any] = {}

    class _FakeStream:
        async def __aenter__(self) -> "_FakeStream":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        def __aiter__(self) -> "_FakeStream":
            return self

        async def __anext__(self) -> object:
            raise StopAsyncIteration

        async def get_final_completion(self) -> ChatCompletion:
            return final

    def fake_stream(**kwargs: Any) -> _FakeStream:
        captured.update(kwargs)
        return _FakeStream()

    monkeypatch.setattr(api.client.chat.completions, "stream", fake_stream)

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
        assert captured["stream_options"] == {"include_usage": True}
        # the logged request matches what was sent on the wire
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
