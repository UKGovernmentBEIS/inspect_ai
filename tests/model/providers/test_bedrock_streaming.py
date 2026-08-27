"""Tests for Bedrock ConverseStream support (on_stream streaming).

The accumulator consumes ConverseStream event dicts and reconstructs the
non-streaming ConverseResponse shape, reporting deltas to the model layer's
stream observer along the way.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from botocore.exceptions import ClientError  # noqa: E402

from inspect_ai.model._generate_config import GenerateConfig  # noqa: E402
from inspect_ai.model._providers.bedrock import (  # noqa: E402
    BedrockAPI,
    converse_response_from_stream,
    model_output_from_response,
)
from inspect_ai.model._stream import (  # noqa: E402
    ModelStreamObserver,
    StreamReasoningEvent,
    StreamTextEvent,
    StreamToolCallEvent,
    model_stream_observer,
)
from inspect_ai.util._json import JSONSchema  # noqa: E402


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


async def test_bedrock_stream_error_event_raises_client_error() -> None:
    """Exception members of the event union raise classified ClientErrors."""
    events: list[dict[str, Any]] = [
        {"messageStart": {"role": "assistant"}},
        {"throttlingException": {"message": "Too many requests"}},
    ]

    with pytest.raises(ClientError) as excinfo:
        await converse_response_from_stream(_events(events))
    assert excinfo.value.response["Error"]["Code"] == "ThrottlingException"

    # the raised code is one the provider classifies as a rate limit
    api = _make_api()
    decision = api.should_retry(excinfo.value)
    assert bool(decision) is True

    # the stream-only ModelStreamErrorException (documented by AWS as
    # "Retry your request") classifies as retryable too
    events = [
        {"messageStart": {"role": "assistant"}},
        {"modelStreamErrorException": {"message": "stream interrupted"}},
    ]
    with pytest.raises(ClientError) as excinfo:
        await converse_response_from_stream(_events(events))
    assert excinfo.value.response["Error"]["Code"] == "ModelStreamErrorException"
    assert bool(api.should_retry(excinfo.value)) is True


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


from test_helpers.utils import skip_if_no_bedrock  # noqa: E402

from inspect_ai.model import ChatMessageUser, get_model  # noqa: E402


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
