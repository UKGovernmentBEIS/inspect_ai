"""Tests for Bedrock ConverseStream support (on_stream streaming).

The accumulator consumes ConverseStream event dicts and reconstructs the
non-streaming ConverseResponse shape, reporting deltas to the model layer's
stream observer along the way.
"""

from __future__ import annotations

import json
import struct
import zlib
from typing import Any, Iterable, Iterator

import pytest
from test_helpers.utils import skip_if_no_bedrock

from inspect_ai.model import ChatMessageUser, RetryDecision, get_model
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._providers.bedrock import (
    BedrockAPI,
    bedrock_error_code,
    converse_response_from_stream,
    model_output_from_response,
)
from inspect_ai.model._stream import (
    ModelStreamObserver,
    StreamReasoningEvent,
    StreamTextEvent,
    StreamToolCallEvent,
    model_stream_observer,
)
from inspect_ai.util._json import JSONSchema

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")


class _StreamCollector:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def __call__(self, event: Any) -> None:
        self.events.append(event)


def _make_api(streaming: bool | None = None) -> BedrockAPI:
    """Build a BedrockAPI without instantiating a session.

    Follows the pattern from ``test_bedrock_adaptive_thinking.py``.
    """
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = "anthropic.claude-sonnet-4-6-20260101-v1:0"
    api.streaming = streaming
    return api


def test_bedrock_resolve_streaming_honors_on_stream() -> None:
    """Unset streaming is "auto": stream iff the caller passed on_stream."""
    from inspect_ai.model import ResponseSchema

    config = GenerateConfig()
    collector = _StreamCollector()

    api = _make_api()
    assert api.resolve_streaming(config) is False
    with model_stream_observer(ModelStreamObserver("test", collector)):
        assert api.resolve_streaming(config) is True

        # auto mode declines requests carrying a response_schema
        schema_config = GenerateConfig(
            response_schema=ResponseSchema(
                name="schema", json_schema=JSONSchema(type="object")
            )
        )
        assert api.resolve_streaming(schema_config) is False
        assert _make_api(streaming=True).resolve_streaming(schema_config) is True

        # explicit opt-out wins over an on_stream callback
        assert _make_api(streaming=False).resolve_streaming(config) is False

    # explicit opt-in streams without a callback
    assert _make_api(streaming=True).resolve_streaming(config) is True


async def _events(items: list[dict[str, Any]]) -> Any:
    for item in items:
        yield item


async def test_bedrock_converse_response_from_stream() -> None:
    """The stream accumulator reconstructs the response and reports deltas."""
    events: list[dict[str, Any]] = [
        {"messageStart": {"role": "assistant"}},
        {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"reasoningContent": {"text": "hmm"}},
            }
        },
        # signature deltas are dropped (not modeled by the response either)
        {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"reasoningContent": {"signature": "sig=="}},
            }
        },
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {
            "contentBlockDelta": {
                "contentBlockIndex": 1,
                "delta": {"text": "hel"},
            }
        },
        {"contentBlockStop": {"contentBlockIndex": 1}},
        {
            "contentBlockStart": {
                "contentBlockIndex": 2,
                "start": {"toolUse": {"toolUseId": "call_1", "name": "bash"}},
            }
        },
        {
            "contentBlockDelta": {
                "contentBlockIndex": 2,
                "delta": {"toolUse": {"input": '{"cmd": '}},
            }
        },
        {
            "contentBlockDelta": {
                "contentBlockIndex": 2,
                "delta": {"toolUse": {"input": '"ls"}'}},
            }
        },
        {"contentBlockStop": {"contentBlockIndex": 2}},
        {"messageStop": {"stopReason": "tool_use"}},
        {
            "metadata": {
                "usage": {"inputTokens": 3, "outputTokens": 7, "totalTokens": 10},
                "metrics": {"latencyMs": 42},
            }
        },
    ]

    collector = _StreamCollector()
    with model_stream_observer(ModelStreamObserver("test", collector)):
        response = await converse_response_from_stream(_events(events))

    # final response accumulated from the events
    assert response.stopReason == "tool_use"
    assert response.usage.totalTokens == 10
    assert response.metrics.latencyMs == 42
    content = response.output.message.content
    assert content[0].reasoningContent is not None
    assert content[0].reasoningContent.reasoningText.text == "hmm"
    assert content[1].text == "hel"
    assert content[2].toolUse is not None
    assert content[2].toolUse.toolUseId == "call_1"
    assert content[2].toolUse.name == "bash"
    assert content[2].toolUse.input == {"cmd": "ls"}

    # deltas were reported to on_stream (with tool fragments attributed)
    assert [type(e) for e in collector.events] == [
        StreamReasoningEvent,
        StreamTextEvent,
        StreamToolCallEvent,
        StreamToolCallEvent,
    ]
    assert collector.events[0].reasoning == "hmm"
    assert collector.events[1].text == "hel"
    assert collector.events[2].id == "call_1"
    assert collector.events[2].function == "bash"
    assert collector.events[2].arguments == '{"cmd": '

    # the accumulated response flows through existing response parsing
    output = model_output_from_response("test-model", response, [])
    assert output.choices[0].stop_reason == "tool_calls"
    assert output.choices[0].message.tool_calls is not None
    assert output.choices[0].message.tool_calls[0].arguments == {"cmd": "ls"}
    assert output.usage is not None and output.usage.total_tokens == 10


async def test_bedrock_stream_gated_without_on_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an on_stream consumer only usage/heartbeat progress runs.

    Explicit streaming=true callers stream without asking for stream events,
    so delta construction (on_stream support code) must not run for them.
    """
    import inspect_ai.model._providers.bedrock as bedrock_module

    async def fail(delta: Any) -> None:
        raise AssertionError("delta reported without an on_stream consumer")

    monkeypatch.setattr(bedrock_module, "report_model_stream_delta", fail)

    events: list[dict[str, Any]] = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "hel"}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "lo"}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "end_turn"}},
        {
            "metadata": {
                "usage": {"inputTokens": 3, "outputTokens": 7, "totalTokens": 10},
                "metrics": {"latencyMs": 42},
            }
        },
    ]

    observer = ModelStreamObserver("test", None)
    with model_stream_observer(observer):
        response = await converse_response_from_stream(_events(events))

    # response assembly and the usage progress channel are unaffected
    assert response.output.message.content[0].text == "hello"
    assert observer._tokens_current == 7


def _event_stream_frame(headers: dict[str, str], payload: dict[str, Any]) -> bytes:
    """Encode one AWS event-stream message (all headers as strings)."""
    encoded_headers = b""
    for name, value in headers.items():
        name_bytes, value_bytes = name.encode(), value.encode()
        encoded_headers += (
            struct.pack("!B", len(name_bytes))
            + name_bytes
            + b"\x07"  # string header value type
            + struct.pack("!H", len(value_bytes))
            + value_bytes
        )
    body = json.dumps(payload).encode()
    prelude = struct.pack(
        "!II", 16 + len(encoded_headers) + len(body), len(encoded_headers)
    )
    message = prelude + struct.pack("!I", zlib.crc32(prelude)) + encoded_headers + body
    return message + struct.pack("!I", zlib.crc32(message))


def _sdk_stream(frames: list[bytes]) -> Any:
    """A botocore EventStream over encoded ConverseStream frames.

    Runs the real service model and event-stream parser, so exception frames
    surface exactly as they do from aiobotocore (whose `_parse_event` is the
    same code): raised as `EventStreamError` before any event is yielded.
    """
    import botocore.session
    from botocore.eventstream import EventStream
    from botocore.model import StructureShape
    from botocore.parsers import EventStreamJSONParser

    class _RawStream:
        def stream(self) -> Iterator[bytes]:
            yield from frames

    model = botocore.session.get_session().get_service_model("bedrock-runtime")
    output_shape = model.operation_model("ConverseStream").output_shape
    assert output_shape is not None
    stream_shape = output_shape.members["stream"]
    assert isinstance(stream_shape, StructureShape)
    events: Iterable[Any] = EventStream(
        _RawStream(), stream_shape, EventStreamJSONParser(), "ConverseStream"
    )

    async def _aiter() -> Any:
        for event in events:
            yield event

    return _aiter()


def _exception_frame(exception_type: str, message: str) -> bytes:
    return _event_stream_frame(
        {
            ":message-type": "exception",
            ":exception-type": exception_type,
            ":content-type": "application/json",
        },
        {"message": message},
    )


_MESSAGE_START = _event_stream_frame(
    {
        ":message-type": "event",
        ":event-type": "messageStart",
        ":content-type": "application/json",
    },
    {"role": "assistant"},
)


@pytest.mark.parametrize(
    ("exception_type", "kind"),
    [
        ("throttlingException", "rate_limit"),
        ("serviceUnavailableException", "transient"),
        # stream-only; AWS documents it as "Retry your request."
        ("modelStreamErrorException", "transient"),
    ],
)
async def test_bedrock_stream_exception_frame_retries(
    exception_type: str, kind: str
) -> None:
    """A throttling/transient exception frame mid-stream is retried.

    The frame's `:exception-type` header is the event union's member name
    (lowercase-first), which botocore uses verbatim as the error code — not
    the PascalCase shape name the non-streaming operation raises.
    """
    from botocore.exceptions import EventStreamError

    frames = [_MESSAGE_START, _exception_frame(exception_type, "Too many requests")]
    with pytest.raises(EventStreamError) as excinfo:
        await converse_response_from_stream(_sdk_stream(frames))
    assert excinfo.value.response["Error"]["Code"] == exception_type
    assert excinfo.value.response["Error"]["Message"] == "Too many requests"

    decision = _make_api().should_retry(excinfo.value)
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True
    assert decision.kind == kind


async def test_bedrock_stream_validation_frame_maps_to_shape_name() -> None:
    """The stream-path validation error is recognised like the non-streaming one."""
    from botocore.exceptions import EventStreamError

    frames = [_exception_frame("validationException", "Input is too long")]
    with pytest.raises(EventStreamError) as excinfo:
        await converse_response_from_stream(_sdk_stream(frames))
    assert bedrock_error_code(excinfo.value) == "ValidationException"
    assert bool(_make_api().should_retry(excinfo.value)) is False


def test_bedrock_error_code_normalises_case() -> None:
    from botocore.exceptions import ClientError

    def client_error(code: str) -> ClientError:
        return ClientError({"Error": {"Code": code, "Message": ""}}, "Converse")

    # non-streaming codes pass through unchanged
    assert (
        bedrock_error_code(client_error("ThrottlingException")) == "ThrottlingException"
    )
    assert bedrock_error_code(client_error("")) == ""
    # stream member names map to the shape name the retry sets use
    assert (
        bedrock_error_code(client_error("throttlingException")) == "ThrottlingException"
    )
    api = _make_api()
    assert bool(api.should_retry(client_error("throttlingException"))) is True
    assert bool(api.should_retry(client_error("internalServerException"))) is False
    assert api.is_auth_failure(client_error("ExpiredTokenException")) is True


async def test_bedrock_stream_without_stop_reason_raises() -> None:
    events: list[dict[str, Any]] = [{"messageStart": {"role": "assistant"}}]
    with pytest.raises(RuntimeError, match="without delivering a stop reason"):
        await converse_response_from_stream(_events(events))


async def test_bedrock_stream_without_usage_raises() -> None:
    """A stream missing its trailing metadata event fails loudly.

    Fabricating zero usage would silently under-count tokens.
    """
    events: list[dict[str, Any]] = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "hi"}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    with pytest.raises(RuntimeError, match="without delivering usage"):
        await converse_response_from_stream(_events(events))


@pytest.mark.anyio
@skip_if_no_bedrock
async def test_bedrock_stream_end_to_end() -> None:
    """Passing on_stream alone enables ConverseStream and reconstructs output."""
    events: list[Any] = []

    async def collect(event: Any) -> None:
        events.append(event)

    model = get_model(
        "bedrock/us.anthropic.claude-sonnet-4-6",
        config=GenerateConfig(max_tokens=256, temperature=0.0),
    )
    response = await model.generate(
        input=[ChatMessageUser(content="This is a test string. What are you?")],
        on_stream=collect,
    )
    assert len(response.completion) >= 1
    streamed = "".join(e.text for e in events if isinstance(e, StreamTextEvent))
    assert streamed == response.completion
