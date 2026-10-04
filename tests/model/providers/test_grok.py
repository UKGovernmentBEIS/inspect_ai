import asyncio
import importlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import anyio
import grpc
import pytest
import tenacity
from pydantic import BaseModel
from test_helpers.utils import skip_if_no_grok, skip_if_trio

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    BatchConfig,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    ResponseSchema,
    get_model,
)
from inspect_ai.model._model import AttemptTimeoutError
from inspect_ai.model._providers._grok_batch import GrokBatcher
from inspect_ai.model._providers.util.batch import Batch, BatchRequest
from inspect_ai.model._retry import model_retry_config
from inspect_ai.scorer import includes
from inspect_ai.util import json_schema


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


@pytest.mark.parametrize(
    "details",
    [
        # current xAI wording (structured error code)
        "Failed to start sampling: [input_too_large] Current message "
        "(1149677 tokens) exceeds budget (975424 tokens)",
        # legacy xAI wording
        "The prompt length exceeds the maximum context length",
    ],
)
def test_grok_context_overflow_maps_to_model_length(details: str) -> None:
    """INVALID_ARGUMENT context-overflow errors map to stop_reason=model_length."""
    from inspect_ai.model._providers._grok_batch import _BatchRpcError
    from inspect_ai.model._providers.grok import GrokAPI

    api = GrokAPI(model_name="grok-4.3", api_key="test-key")
    ex = _BatchRpcError(status_code=grpc.StatusCode.INVALID_ARGUMENT, message=details)
    output = api._handle_grpc_bad_request(ex)
    assert isinstance(output, ModelOutput)
    assert output.stop_reason == "model_length"
    assert output.completion == details


def test_grok_unrelated_bad_request_is_returned_as_error() -> None:
    """INVALID_ARGUMENT errors that are not context overflows surface as errors."""
    from inspect_ai.model._providers._grok_batch import _BatchRpcError
    from inspect_ai.model._providers.grok import GrokAPI

    api = GrokAPI(model_name="grok-4.3", api_key="test-key")
    ex = _BatchRpcError(
        status_code=grpc.StatusCode.INVALID_ARGUMENT,
        message="Reasoning budget exceeds budget (1000 tokens)",
    )
    result = api._handle_grpc_bad_request(ex)
    assert isinstance(result, Exception)
    assert result is ex


@pytest.mark.parametrize(
    "details",
    [
        "Request blocked by safety_check",
        "I can't help with that request.",
        "Request rejected: I CAN'T HELP WITH THAT REQUEST",
    ],
)
def test_grok_refusal_maps_to_content_filter(details: str) -> None:
    from inspect_ai.model._providers._grok_batch import _BatchRpcError
    from inspect_ai.model._providers.grok import GrokAPI

    api = GrokAPI(model_name="grok-4.3", api_key="test-key")
    ex = _BatchRpcError(status_code=grpc.StatusCode.PERMISSION_DENIED, message=details)

    output = api._handle_grpc_permission_denied(ex)

    assert output is not None
    assert output.stop_reason == "content_filter"
    assert output.completion == details
    stop_details = output.choices[0].stop_details
    assert stop_details is not None
    assert stop_details.type == "refusal"
    assert stop_details.explanation == details


def test_grok_unrelated_permission_denied_is_not_a_refusal() -> None:
    from inspect_ai.model._providers._grok_batch import _BatchRpcError
    from inspect_ai.model._providers.grok import GrokAPI

    api = GrokAPI(model_name="grok-4.3", api_key="test-key")
    ex = _BatchRpcError(
        status_code=grpc.StatusCode.PERMISSION_DENIED,
        message="Permission denied for this model",
    )

    assert api._handle_grpc_permission_denied(ex) is None


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


# -- Built-in-typed calls to client function tools ------------------------------


def _code_execution_tool_info(native: bool) -> Any:
    """The `code_execution()` tool as sent to Grok, native or client-side."""
    from inspect_ai.tool._tool_info import ToolInfo
    from inspect_ai.tool._tool_params import ToolParam, ToolParams

    return ToolInfo(
        name="code_execution",
        description="Execute Python code.",
        parameters=ToolParams(
            properties={"code": ToolParam(type="string")}, required=["code"]
        ),
        options={"providers": {"grok": {}} if native else {"python": {}}},
    )


def _code_execution_typed_response() -> Any:
    """A completion whose one tool call xAI typed as its built-in code_execution."""
    from xai_sdk.chat import Response, chat_pb2

    proto = chat_pb2.GetChatCompletionResponse(
        outputs=[
            chat_pb2.CompletionOutput(
                index=0,
                finish_reason="REASON_TOOL_CALLS",
                message=chat_pb2.CompletionMessage(
                    role=chat_pb2.MessageRole.ROLE_ASSISTANT,
                    tool_calls=[
                        chat_pb2.ToolCall(
                            id="call-1",
                            type=chat_pb2.ToolCallType.TOOL_CALL_TYPE_CODE_EXECUTION_TOOL,
                            function=chat_pb2.FunctionCall(
                                name="code_execution",
                                arguments='{"code":"print(435678 + 23457)"}',
                            ),
                        )
                    ],
                ),
            )
        ]
    )
    return Response(proto, 0)


def test_grok_builtin_typed_call_to_client_function_is_executed() -> None:
    """A code_execution-typed call to a client `code_execution` function is a tool call."""
    from inspect_ai._util.content import ContentToolUse
    from inspect_ai.model._providers.grok import GrokAPI

    api = GrokAPI(model_name="grok-4-fast", api_key="test-key")
    output = api._model_output_from_response(
        _code_execution_typed_response(), [_code_execution_tool_info(native=False)]
    )

    message = output.message
    assert message.tool_calls is not None
    assert [(tc.id, tc.function) for tc in message.tool_calls] == [
        ("call-1", "code_execution")
    ]
    assert message.tool_calls[0].arguments == {"code": "print(435678 + 23457)"}
    assert not any(isinstance(c, ContentToolUse) for c in message.content)
    assert output.stop_reason == "tool_calls"


def test_grok_native_code_execution_call_stays_server_side() -> None:
    """With native code execution enabled the same call is a server tool use."""
    from inspect_ai._util.content import ContentToolUse
    from inspect_ai.model._providers.grok import GrokAPI

    api = GrokAPI(model_name="grok-4-fast", api_key="test-key")
    output = api._model_output_from_response(
        _code_execution_typed_response(), [_code_execution_tool_info(native=True)]
    )

    message = output.message
    assert message.tool_calls is None
    tool_uses = [c for c in message.content if isinstance(c, ContentToolUse)]
    assert len(tool_uses) == 1
    assert tool_uses[0].tool_type == "code_execution"
    assert tool_uses[0].name == "code_execution"


def test_grok_native_web_search_call_named_like_client_function_stays_server_side() -> (
    None
):
    """A native web_search call keeps its type even if a client function shares its name."""
    from xai_sdk.chat import Response, chat_pb2

    from inspect_ai._util.content import ContentToolUse
    from inspect_ai.model._providers.grok import GrokAPI
    from inspect_ai.tool._tool_info import ToolInfo

    native_web_search = ToolInfo(
        name="web_search", description="Native web search", options={"grok": {}}
    )
    client_browse_page = ToolInfo(name="browse_page", description="Local function")
    proto = chat_pb2.GetChatCompletionResponse(
        outputs=[
            chat_pb2.CompletionOutput(
                index=0,
                finish_reason="REASON_STOP",
                message=chat_pb2.CompletionMessage(
                    role=chat_pb2.MessageRole.ROLE_ASSISTANT,
                    content="Done",
                    tool_calls=[
                        chat_pb2.ToolCall(
                            id="call-1",
                            type=chat_pb2.ToolCallType.TOOL_CALL_TYPE_WEB_SEARCH_TOOL,
                            function=chat_pb2.FunctionCall(
                                name="browse_page", arguments='{"url":"https://x.ai"}'
                            ),
                        )
                    ],
                ),
            )
        ]
    )

    api = GrokAPI(model_name="grok-4-fast", api_key="test-key")
    output = api._model_output_from_response(
        Response(proto, 0), [native_web_search, client_browse_page]
    )

    message = output.message
    assert message.tool_calls is None
    tool_uses = [c for c in message.content if isinstance(c, ContentToolUse)]
    assert [(t.tool_type, t.name) for t in tool_uses] == [("web_search", "browse_page")]


class _SleepingGrpcHandler(grpc.GenericRpcHandler):
    """Answers every unary method by sleeping until the client cancels the call."""

    async def _sleep(self, request: bytes, context: grpc.aio.ServicerContext) -> bytes:
        await asyncio.sleep(60)
        return b""

    def service(
        self, handler_call_details: grpc.HandlerCallDetails
    ) -> grpc.RpcMethodHandler | None:
        return grpc.unary_unary_rpc_method_handler(self._sleep)


@asynccontextmanager
async def _sleeping_grpc_server() -> AsyncIterator[str]:
    """A local gRPC server whose unary calls never complete on their own."""
    server = grpc.aio.server()
    server.add_generic_rpc_handlers((_SleepingGrpcHandler(),))
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        yield f"127.0.0.1:{port}"
    finally:
        await server.stop(None)


class _Answer(BaseModel):
    text: str


def _track_grok_clients(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Record every real xai_sdk AsyncClient the provider creates, and its close."""
    import inspect_ai.model._providers.grok as grok_module

    # xai_sdk ships no type stubs; going through import_module keeps mypy out of it
    real_client: Any = importlib.import_module("xai_sdk").AsyncClient
    clients: list[Any] = []

    def recording_client(**kwargs: Any) -> Any:
        client = real_client(**kwargs)
        real_close = client.close

        async def close() -> None:
            client.closed = True
            await real_close()

        client.closed = False
        client.close = close
        clients.append(client)
        return client

    monkeypatch.setattr(grok_module, "AsyncClient", recording_client)
    return clients


def _assert_client_closed(clients: list[Any]) -> None:
    """The cancelled operation's client was closed and its channel shut down."""
    assert len(clients) == 1
    (client,) = clients
    assert client.closed
    assert client._api_channel.get_state() == grpc.ChannelConnectivity.SHUTDOWN


def _sleeping_grok_api(target: str) -> Any:
    from inspect_ai.model._providers.grok import GrokAPI

    return GrokAPI(
        model_name="grok-4.5",
        api_key="test-key",
        base_url=target,
        streaming=False,
        use_insecure_channel=True,
    )


_PARSE_CONFIG = GenerateConfig(
    response_schema=ResponseSchema(name="answer", json_schema=json_schema(_Answer))
)


@skip_if_trio
@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda api: _generate_once(api, GenerateConfig()), id="sample"),
        pytest.param(lambda api: _generate_once(api, _PARSE_CONFIG), id="parse"),
        pytest.param(lambda api: api.count_text_tokens("hello"), id="tokens"),
    ],
)
async def test_grok_unary_call_cancelled_by_fail_after_raises_timeout(
    operation: Callable[[Any], Awaitable[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unary gRPC call cut off by an anyio deadline reports the timeout.

    grpc.aio answers a cancelled unary call with a fresh, message-less
    CancelledError that anyio does not recognise as its own, so without the
    provider's guard the bare cancellation escapes instead of TimeoutError.
    The provider's client is still closed on the way out.
    """
    clients = _track_grok_clients(monkeypatch)
    async with _sleeping_grpc_server() as target:
        api = _sleeping_grok_api(target)
        with pytest.raises(TimeoutError):
            with anyio.fail_after(1):
                await operation(api)
        _assert_client_closed(clients)


@skip_if_trio
async def test_grok_unary_call_attempt_timeout_is_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled unary Grok call hit by `attempt_timeout` ends as AttemptTimeoutError.

    That is the retryable outcome; without the guard the attempt ends in a bare
    cancellation that the retry loop never sees.
    """
    clients = _track_grok_clients(monkeypatch)
    async with _sleeping_grpc_server() as target:
        model = get_model(
            "grok/grok-4.5",
            api_key="test-key",
            base_url=target,
            streaming=False,
            use_insecure_channel=True,
            memoize=False,
        )
        with pytest.raises(tenacity.RetryError) as excinfo:
            await model.generate(
                "hello", config=GenerateConfig(attempt_timeout=1, max_retries=0)
            )
        assert isinstance(excinfo.value.last_attempt.exception(), AttemptTimeoutError)
        _assert_client_closed(clients)
