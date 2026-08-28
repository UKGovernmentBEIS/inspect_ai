from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest
from test_helpers.utils import skip_if_no_grok, skip_if_trio

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    BatchConfig,
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._providers._grok_batch import GrokBatcher
from inspect_ai.model._providers.util.batch import Batch, BatchRequest
from inspect_ai.model._retry import model_retry_config
from inspect_ai.scorer import includes


@skip_if_no_grok
async def test_grok_api() -> None:
    """Smoke test a basic Grok completion request."""
    model = get_model(
        "grok/grok-3-mini",
        config=GenerateConfig(
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


def test_grok_service_tier_model_arg() -> None:
    """The service_tier model arg is passed through to request params."""
    from inspect_ai.model._providers.grok import GrokAPI

    api = GrokAPI(model_name="grok-4.6", api_key="test-key", service_tier="priority")
    assert api._grok_params(GenerateConfig())["service_tier"] == "priority"

    # omitted by default (the service default tier applies)
    default_api = GrokAPI(model_name="grok-4.6", api_key="test-key")
    assert "service_tier" not in default_api._grok_params(GenerateConfig())


def test_grok_service_tier_omitted_for_batch() -> None:
    """Batch requests use xAI's batch tier, so service_tier is not sent."""
    from typing import Any, cast

    from inspect_ai.model._providers.grok import GrokAPI

    api = GrokAPI(model_name="grok-4.6", api_key="test-key", service_tier="priority")
    api._batcher = cast(Any, object())
    assert "service_tier" not in api._grok_params(GenerateConfig())


def test_grok_service_tier_requires_sdk_support(monkeypatch) -> None:
    """SDKs predating chat.create(service_tier=...) (< 1.17) fail fast."""
    from xai_sdk.chat import usage_pb2  # type: ignore[import-untyped]

    from inspect_ai._util.error import PrerequisiteError
    from inspect_ai.model._providers.grok import GrokAPI

    monkeypatch.delattr(usage_pb2, "ServiceTier")
    with pytest.raises(PrerequisiteError, match="service_tier"):
        GrokAPI(model_name="grok-4.6", api_key="test-key", service_tier="priority")


class _AlarmTimeout(Exception):
    """Raised when the smoke test alarm times out."""

    pass


def _alarm_handler(_signum: int, _frame: object) -> None:
    """Signal handler that converts SIGALRM into _AlarmTimeout."""
    raise _AlarmTimeout


@skip_if_no_grok
def test_grok_batch_submission_smoke() -> None:
    """Batch submission should not be rejected immediately by Grok provider."""
    import signal

    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(4)
    try:
        eval(
            Task(
                dataset=[Sample(input="What is 2+2?", target="4")],
                scorer=includes(),
            ),
            # grok-3-mini currently rejects this batch endpoint for some keys.
            model="grok/grok-4-1-fast-non-reasoning",
            batch=BatchConfig(size=1, send_delay=0, tick=0.1),
            fail_on_error=True,
        )
    except _AlarmTimeout:
        pass  # submission succeeded, batch just didn't complete
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def _make_grok_batcher_and_batch(
    *,
    num_pending: int,
    num_success: int,
    num_error: int,
    num_cancelled: int,
    num_requests: int,
) -> tuple[GrokBatcher, Batch[object]]:
    """Create a mocked batcher and single-request batch for status tests."""
    client = MagicMock()
    client.batch.get = AsyncMock(
        return_value=SimpleNamespace(
            state=SimpleNamespace(
                num_pending=num_pending,
                num_success=num_success,
                num_error=num_error,
                num_cancelled=num_cancelled,
                num_requests=num_requests,
            ),
            create_time=SimpleNamespace(seconds=1234),
        )
    )

    batcher = GrokBatcher(
        client=client,
        config=BatchConfig(),
        retry_config=model_retry_config(
            "test", 3, None, lambda e: True, lambda ex: None, lambda m, s: None
        ),
    )

    send_stream = MagicMock()
    req: BatchRequest[object] = BatchRequest(
        request={},
        result_stream=send_stream,
        custom_id="req-1",
    )

    return batcher, Batch(id="batch-123", requests={"req-1": req})


@pytest.mark.parametrize(
    "num_pending,num_success,num_error,num_cancelled,num_requests,expect_completed,expect_failed,expect_completion",
    [
        pytest.param(2, 0, 0, 0, 2, 0, 0, False, id="pending"),
        pytest.param(0, 2, 0, 0, 2, 2, 0, True, id="all-success"),
        pytest.param(0, 1, 2, 3, 6, 1, 5, True, id="terminal-mixed"),
        pytest.param(0, 1, 0, 0, 2, 1, 0, False, id="counts-not-terminal"),
        pytest.param(0, 0, 0, 0, 0, 0, 0, False, id="empty-not-terminal"),
    ],
)
async def test_grok_check_batch_terminal_states(
    num_pending: int,
    num_success: int,
    num_error: int,
    num_cancelled: int,
    num_requests: int,
    expect_completed: int,
    expect_failed: int,
    expect_completion: bool,
) -> None:
    """Map xAI batch counters to inspect batch completion semantics."""
    batcher, batch = _make_grok_batcher_and_batch(
        num_pending=num_pending,
        num_success=num_success,
        num_error=num_error,
        num_cancelled=num_cancelled,
        num_requests=num_requests,
    )

    result = await batcher._check_batch(batch)
    assert result.completed_count == expect_completed
    assert result.failed_count == expect_failed
    assert (result.completion_info is not None) == expect_completion


async def test_grok_failed_batch_items_preserve_grpc_error_semantics() -> None:
    """Preserve grpc status codes when batch items fail."""
    client = MagicMock()
    client.batch.list_batch_results = AsyncMock(
        return_value=SimpleNamespace(
            results=[
                SimpleNamespace(
                    batch_request_id="req-1",
                    is_success=False,
                    error_message="permission denied",
                    proto=SimpleNamespace(
                        error=SimpleNamespace(
                            code=grpc.StatusCode.PERMISSION_DENIED.value[0]
                        )
                    ),
                )
            ],
            pagination_token=None,
        )
    )

    batcher = GrokBatcher(
        client=client,
        config=BatchConfig(),
        retry_config=model_retry_config(
            "test", 3, None, lambda e: True, lambda ex: None, lambda m, s: None
        ),
    )

    send_stream = MagicMock()
    req: BatchRequest[object] = BatchRequest(
        request={},
        result_stream=send_stream,
        custom_id="req-1",
    )
    batch = Batch(id="batch-123", requests={"req-1": req})

    results = await batcher._handle_batch_result(batch, True)
    error = results["req-1"]
    assert isinstance(error, grpc.RpcError)
    assert error.code() == grpc.StatusCode.PERMISSION_DENIED


async def test_grok_create_batch_parses_json_schema_response_format() -> None:
    """Rehydrate dict response_format into protobuf before chat.create."""
    schema = '{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}'
    client = MagicMock()
    client.chat.create = MagicMock(return_value=MagicMock())
    client.batch.create = AsyncMock(return_value=SimpleNamespace(batch_id="batch-123"))
    client.batch.add = AsyncMock()

    batcher = GrokBatcher(
        client=client,
        config=BatchConfig(),
        retry_config=model_retry_config(
            "test", 3, None, lambda e: True, lambda ex: None, lambda m, s: None
        ),
    )

    request: BatchRequest[object] = BatchRequest(
        request={
            "model": "grok-3-mini",
            "messages": [],
            "tools": [],
            "response_format": {
                "formatType": "FORMAT_TYPE_JSON_SCHEMA",
                "schema": schema,
            },
        },
        result_stream=MagicMock(),
        custom_id="req-1",
    )

    await batcher._create_batch([request])
    create_kwargs = client.chat.create.call_args.kwargs
    response_format = create_kwargs["response_format"]
    assert not isinstance(response_format, dict)
    assert response_format.schema == schema


@pytest.mark.anyio
async def test_grok_create_batch_chunks_add_calls() -> None:
    """Add each request in its own add call to avoid oversized gRPC payloads."""
    client = MagicMock()
    client.chat.create = MagicMock(return_value=MagicMock())
    client.batch.create = AsyncMock(return_value=SimpleNamespace(batch_id="batch-123"))
    client.batch.add = AsyncMock()

    batcher = GrokBatcher(
        client=client,
        config=BatchConfig(),
        retry_config=model_retry_config(
            "test", 3, None, lambda e: True, lambda ex: None, lambda m, s: None
        ),
    )

    batch_requests: list[BatchRequest[object]] = [
        BatchRequest(
            request={"model": "grok-3-mini", "messages": [], "tools": []},
            result_stream=MagicMock(),
            custom_id="req-1",
        ),
        BatchRequest(
            request={"model": "grok-3-mini", "messages": [], "tools": []},
            result_stream=MagicMock(),
            custom_id="req-2",
        ),
        BatchRequest(
            request={"model": "grok-3-mini", "messages": [], "tools": []},
            result_stream=MagicMock(),
            custom_id="req-3",
        ),
    ]

    await batcher._create_batch(batch_requests)

    assert client.batch.add.await_count == len(batch_requests)
    for call in client.batch.add.await_args_list:
        assert call.kwargs["batch_id"] == "batch-123"
        assert len(call.kwargs["batch_requests"]) == 1


# -- Stream observer reporting (on_stream) -------------------------------------


def test_grok_streaming_defaults_to_auto() -> None:
    """Unset streaming is auto (streams when the caller passes on_stream)."""
    from inspect_ai.model._providers.grok import GrokAPI

    assert GrokAPI(model_name="grok-4.6", api_key="test-key").streaming is None
    # -M streaming=auto arrives as the string "auto" (YAML-parsed) and must
    # map to the auto sentinel, not a truthy explicit setting
    assert (
        GrokAPI(model_name="grok-4.6", api_key="test-key", streaming="auto").streaming
        is None
    )
    assert (
        GrokAPI(model_name="grok-4.6", api_key="test-key", streaming=True).streaming
        is True
    )
    assert (
        GrokAPI(model_name="grok-4.6", api_key="test-key", streaming=False).streaming
        is False
    )
    # a typo'd value raises rather than silently forcing streaming on or off
    with pytest.raises(ValueError, match="streaming"):
        GrokAPI(
            model_name="grok-4.6",
            api_key="test-key",
            streaming="always",  # type: ignore[arg-type]
        )


def test_grok_resolve_streaming_declines_logprobs() -> None:
    """Auto mode declines to stream when logprobs are requested.

    xai_sdk's stream accumulator never carries logprobs into the final
    response, so a display-only on_stream request must not enable streaming
    (explicit streaming=true keeps its pre-existing lossy behavior).
    """
    from typing import Any

    from inspect_ai.model._providers.grok import GrokAPI
    from inspect_ai.model._stream import ModelStreamObserver, model_stream_observer

    async def collect(event: Any) -> None:
        pass

    def api(**model_args: Any) -> GrokAPI:
        return GrokAPI(model_name="grok-4.6", api_key="test-key", **model_args)

    logprobs = GenerateConfig(logprobs=True)
    with model_stream_observer(ModelStreamObserver("grok/test", collect)):
        assert api()._resolve_streaming(GenerateConfig()) is True
        assert api()._resolve_streaming(logprobs) is False
        # explicit opt-in/opt-out still wins
        assert api(streaming=True)._resolve_streaming(logprobs) is True
        assert api(streaming=False)._resolve_streaming(GenerateConfig()) is False
    # without an on_stream callback, auto never streams
    assert api()._resolve_streaming(GenerateConfig()) is False


async def test_grok_stream_chunk_reporting() -> None:
    """Streamed chunks are reported to the model layer's stream observer."""
    from xai_sdk.chat import Chunk, chat_pb2

    from inspect_ai.model import (
        StreamEvent,
        StreamReasoningEvent,
        StreamTextEvent,
        StreamToolCallEvent,
    )
    from inspect_ai.model._providers.grok import _report_grok_stream_chunk
    from inspect_ai.model._stream import ModelStreamObserver, model_stream_observer

    events: list[StreamEvent] = []

    async def collect(event: StreamEvent) -> None:
        events.append(event)

    proto = chat_pb2.GetChatCompletionChunk(
        outputs=[
            chat_pb2.CompletionOutputChunk(
                index=0,
                delta=chat_pb2.Delta(
                    role=chat_pb2.MessageRole.ROLE_ASSISTANT,
                    content="hel",
                    reasoning_content="hmm",
                    tool_calls=[
                        chat_pb2.ToolCall(
                            id="call_1",
                            function=chat_pb2.FunctionCall(
                                name="bash", arguments='{"cmd": "ls"}'
                            ),
                        )
                    ],
                ),
            )
        ],
    )
    proto.usage.completion_tokens = 7

    observer = ModelStreamObserver("grok/test", collect)
    with model_stream_observer(observer):
        await _report_grok_stream_chunk(Chunk(proto, 0))

    assert [type(e) for e in events] == [
        StreamReasoningEvent,
        StreamTextEvent,
        StreamToolCallEvent,
    ]
    assert isinstance(events[0], StreamReasoningEvent)
    assert events[0].reasoning == "hmm"
    assert isinstance(events[1], StreamTextEvent)
    assert events[1].text == "hel"
    tool_event = events[2]
    assert isinstance(tool_event, StreamToolCallEvent)
    assert tool_event.id == "call_1"
    assert tool_event.function == "bash"
    assert tool_event.arguments == '{"cmd": "ls"}'
    # the chunk's cumulative usage was reported
    assert observer._tokens_current == 7


async def test_grok_stream_chunk_gated_without_on_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an on_stream consumer only usage/heartbeat progress runs.

    Explicit streaming=true callers stream without asking for stream events,
    so delta construction (on_stream support code) must not run for them.
    """
    from xai_sdk.chat import Chunk, chat_pb2

    import inspect_ai.model._providers.grok as grok_module
    from inspect_ai.model._providers.grok import _report_grok_stream_chunk
    from inspect_ai.model._stream import ModelStreamObserver, model_stream_observer

    async def fail(delta: object) -> None:
        raise AssertionError("delta reported without an on_stream consumer")

    monkeypatch.setattr(grok_module, "report_model_stream_delta", fail)

    proto = chat_pb2.GetChatCompletionChunk(
        outputs=[
            chat_pb2.CompletionOutputChunk(
                index=0,
                delta=chat_pb2.Delta(
                    role=chat_pb2.MessageRole.ROLE_ASSISTANT,
                    content="hel",
                    reasoning_content="hmm",
                ),
            )
        ],
    )
    proto.usage.completion_tokens = 7

    observer = ModelStreamObserver("grok/test", None)
    with model_stream_observer(observer):
        await _report_grok_stream_chunk(Chunk(proto, 0))

    # the usage progress channel still ran
    assert observer._tokens_current == 7


# -- Prompt cache server affinity (x-grok-conv-id) -----------------------------


def _fake_grok_response() -> Any:
    """A minimal successful completion the provider can map to ModelOutput."""
    from xai_sdk.chat import Response, chat_pb2

    proto = chat_pb2.GetChatCompletionResponse(
        outputs=[
            chat_pb2.CompletionOutput(
                index=0,
                finish_reason="REASON_STOP",
                message=chat_pb2.CompletionMessage(
                    role=chat_pb2.MessageRole.ROLE_ASSISTANT, content="hello"
                ),
            )
        ]
    )
    proto.usage.prompt_tokens = 100
    proto.usage.cached_prompt_text_tokens = 80
    proto.usage.completion_tokens = 5
    proto.usage.total_tokens = 105
    return Response(proto, 0)


class _StubAsyncClient:
    """Stands in for xai_sdk.AsyncClient, recording its constructor kwargs."""

    instances: list["_StubAsyncClient"] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.chat = MagicMock()
        self.chat.create.return_value = SimpleNamespace(
            sample=AsyncMock(return_value=_fake_grok_response())
        )
        _StubAsyncClient.instances.append(self)

    async def __aenter__(self) -> "_StubAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


def _stub_grok_client(monkeypatch: pytest.MonkeyPatch) -> list[_StubAsyncClient]:
    import inspect_ai.model._providers.grok as grok_module

    _StubAsyncClient.instances = []
    monkeypatch.setattr(grok_module, "AsyncClient", _StubAsyncClient)
    return _StubAsyncClient.instances


def _stub_active_sample(
    monkeypatch: pytest.MonkeyPatch, sample_uuid: str | None
) -> None:
    import inspect_ai.model._providers.grok as grok_module

    active = SimpleNamespace(sample_uuid=sample_uuid) if sample_uuid else None
    monkeypatch.setattr(grok_module, "sample_active", lambda: active)


async def _generate_once(api: Any, config: GenerateConfig | None = None) -> Any:
    return await api.generate(
        input=[ChatMessageUser(content="hello")],
        tools=[],
        tool_choice="none",
        config=config or GenerateConfig(),
    )


@skip_if_trio
async def test_grok_conv_id_sent_for_active_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sample's uuid pins its turns to one xAI server so the cache hits."""
    from inspect_ai.model._providers.grok import GROK_CONV_ID_HEADER, GrokAPI

    clients = _stub_grok_client(monkeypatch)
    _stub_active_sample(monkeypatch, "sample-uuid-1")

    api = GrokAPI(model_name="grok-4.6", api_key="test-key")
    _output, model_call = await _generate_once(api)

    assert clients[0].kwargs["metadata"] == ((GROK_CONV_ID_HEADER, "sample-uuid-1"),)
    # and it is visible in the logged request for debugging cache behavior
    assert model_call.request["metadata"] == {GROK_CONV_ID_HEADER: "sample-uuid-1"}


@skip_if_trio
async def test_grok_conv_id_omitted_without_active_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside a sample there is no conversation to key on, so no header."""
    from inspect_ai.model._providers.grok import GrokAPI

    clients = _stub_grok_client(monkeypatch)
    _stub_active_sample(monkeypatch, None)

    api = GrokAPI(model_name="grok-4.6", api_key="test-key")
    _output, model_call = await _generate_once(api)

    assert clients[0].kwargs["metadata"] is None
    assert "metadata" not in model_call.request


@skip_if_trio
async def test_grok_conv_id_appends_to_caller_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied metadata model arg is extended, not clobbered.

    -M metadata=... arrives as JSON, so pairs are lists rather than tuples.
    """
    from inspect_ai.model._providers.grok import GROK_CONV_ID_HEADER, GrokAPI

    clients = _stub_grok_client(monkeypatch)
    _stub_active_sample(monkeypatch, "sample-uuid-1")

    api = GrokAPI(
        model_name="grok-4.6", api_key="test-key", metadata=[["x-team", "alpha"]]
    )
    await _generate_once(api)

    assert clients[0].kwargs["metadata"] == (
        ("x-team", "alpha"),
        (GROK_CONV_ID_HEADER, "sample-uuid-1"),
    )


@skip_if_trio
async def test_grok_metadata_model_arg_accepts_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mapping metadata model arg yields pairs, not unpacked bare keys."""
    from inspect_ai.model._providers.grok import GROK_CONV_ID_HEADER, GrokAPI

    clients = _stub_grok_client(monkeypatch)
    _stub_active_sample(monkeypatch, "sample-uuid-1")

    api = GrokAPI(
        model_name="grok-4.6", api_key="test-key", metadata={"x-team": "alpha"}
    )
    await _generate_once(api)

    assert clients[0].kwargs["metadata"] == (
        ("x-team", "alpha"),
        (GROK_CONV_ID_HEADER, "sample-uuid-1"),
    )


@skip_if_trio
async def test_grok_conv_id_omitted_for_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch shares one long-lived client, so no per-sample header.

    The batcher expands the request dict into chat.create(**request), so an
    unexpected metadata key there would raise.
    """
    from inspect_ai.model._providers.grok import GrokAPI

    _stub_grok_client(monkeypatch)
    _stub_active_sample(monkeypatch, "sample-uuid-1")

    api = GrokAPI(model_name="grok-4.6", api_key="test-key")
    batcher = MagicMock()
    batcher.generate_for_request = AsyncMock(return_value=_fake_grok_response())
    api._batcher = batcher

    _output, model_call = await _generate_once(api)

    assert "metadata" not in batcher.generate_for_request.await_args.args[0]
    assert "metadata" not in model_call.request


@skip_if_no_grok
def test_grok_prompt_cache_across_turns_live() -> None:
    """The conv id header is accepted and a second turn reads from the cache.

    Guards two things against the real API: that attaching the header to the
    gRPC call doesn't break requests, and that cache reads are reported. It
    does not isolate the header's routing effect — xAI often keeps short
    sequential conversations on one server anyway, so turn 2 tends to hit
    either way. The header's measurable benefit shows up under concurrency.
    """
    from inspect_ai.event import ModelEvent
    from inspect_ai.model._providers.grok import GROK_CONV_ID_HEADER
    from inspect_ai.solver import Generate, TaskState, generate, solver, system_message

    @solver
    def second_turn():
        async def solve(state: TaskState, _generate: Generate) -> TaskState:
            state.messages.append(ChatMessageUser(content="Now reply with 'bye'."))
            return await _generate(state)

        return solve

    padding = "The quick brown fox jumps over the lazy dog. " * 800
    model = "grok/grok-4-1-fast-non-reasoning"
    log = eval(
        Task(
            dataset=[Sample(input="Reply with 'hi'.")],
            solver=[system_message(padding), generate(), second_turn()],
        ),
        model=model,
        max_tokens=16,
    )[0]

    assert log.status == "success"
    assert log.samples is not None
    model_events = [e for e in log.samples[0].events if isinstance(e, ModelEvent)]
    assert len(model_events) == 2

    # both turns went out under the one sample's conv id
    conv_ids = set()
    for event in model_events:
        assert event.call is not None
        metadata = cast(dict[str, str], event.call.request["metadata"])
        conv_ids.add(metadata[GROK_CONV_ID_HEADER])
    assert len(conv_ids) == 1
    assert conv_ids.pop() == log.samples[0].uuid

    # the first turn's prompt is a prefix of the second turn's
    second = model_events[1].output.usage
    assert second is not None
    assert second.input_tokens_cache_read is not None
    assert second.input_tokens_cache_read > 0
