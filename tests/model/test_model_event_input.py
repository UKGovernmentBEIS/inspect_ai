"""`ModelEvent.input` records the messages as they were when the model was called."""

import json
import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from inspect_ai._util.constants import get_deserializing_context
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    get_model,
)
from inspect_ai.model._model import use_model_event_sink
from inspect_ai.tool import ToolCall, ToolCallError


def _conversation() -> list[ChatMessage]:
    return [
        ChatMessageUser(content="What is in the file?"),
        ChatMessageAssistant(
            content="",
            tool_calls=[ToolCall(id="c1", function="read", arguments={"path": "f"})],
        ),
        ChatMessageTool(
            content="original",
            tool_call_id="c1",
            function="read",
            metadata={"notes": ["kept"]},
            error=ToolCallError(type="unknown", message="original error"),
        ),
    ]


def _rewrite_tool_result(message: ChatMessage) -> None:
    assert isinstance(message, ChatMessageTool)
    message.content = "rewritten"
    assert message.metadata is not None
    message.metadata["notes"].append("added")
    message.error = None


def _assert_original(message: ChatMessage) -> None:
    assert isinstance(message, ChatMessageTool)
    assert message.content == "original"
    assert message.metadata == {"notes": ["kept"]}
    assert message.error == ToolCallError(type="unknown", message="original error")


def _model_events() -> list[ModelEvent]:
    return [e for e in transcript().events if isinstance(e, ModelEvent)]


async def test_model_event_input_unchanged_by_later_edits() -> None:
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    messages = _conversation()

    await model.generate(messages)
    _rewrite_tool_result(messages[2])
    await model.generate(messages)

    first, second = _model_events()
    _assert_original(first.input[2])
    assert second.input[2].content == "rewritten"

    # unchanged messages share one copy across events, so the log's message
    # pool still dedups them by identity
    assert first.input[0] is second.input[0]
    assert first.input[1] is second.input[1]
    assert first.input[0] is not messages[0]


async def test_model_event_input_snapshot_with_event_sink() -> None:
    class Sink:
        def __init__(self) -> None:
            self.events: list[ModelEvent] = []

        def on_pending(self, event: ModelEvent) -> None:
            self.events.append(event)

        def on_complete(self, event: ModelEvent) -> None:
            pass

    init_transcript(Transcript())
    model = get_model("mockllm/model")
    messages = _conversation()
    sink = Sink()

    with use_model_event_sink(sink):
        await model.generate(messages)
    _rewrite_tool_result(messages[2])

    assert len(sink.events) == 1
    _assert_original(sink.events[0].input[2])
    assert _model_events() == []


@pytest.mark.parametrize(
    "before,after", [(0.0, -0.0), ({"x": 1, "y": 2}, {"y": 2, "x": 1})]
)
async def test_model_event_input_keeps_equal_but_distinct_edits(
    before: Any, after: Any
) -> None:
    # == treats these as equal, but they serialize (and are sent) differently
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    messages = _conversation()
    assistant = messages[1]
    assert isinstance(assistant, ChatMessageAssistant) and assistant.tool_calls
    assistant.tool_calls[0].arguments["value"] = before

    await model.generate(messages)
    assistant.tool_calls[0].arguments["value"] = after
    await model.generate(messages)

    logged = []
    for event in _model_events():
        message = event.input[1]
        assert isinstance(message, ChatMessageAssistant) and message.tool_calls
        logged.append(json.dumps(message.tool_calls[0].arguments["value"]))
    assert logged == [json.dumps(before), json.dumps(after)]


async def test_model_event_input_reuses_nan_and_id_less_snapshots() -> None:
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    user = ChatMessageUser.model_validate(
        {"role": "user", "content": "hi"}, context=get_deserializing_context()
    )
    assert user.id is None
    assistant = ChatMessageAssistant(
        content="",
        tool_calls=[ToolCall(id="c1", function="f", arguments={"x": float("nan")})],
    )
    messages: list[ChatMessage] = [user, assistant]

    await model.generate(messages)
    await model.generate(messages)
    user.content = "edited"
    await model.generate(messages)

    first, second, third = _model_events()
    assert first.input[0] is second.input[0]
    assert first.input[1] is second.input[1]
    assert second.input[0].content == "hi"
    assert third.input[0].content == "edited"
    assert third.input[1] is first.input[1]
    first_call = first.input[1]
    assert isinstance(first_call, ChatMessageAssistant) and first_call.tool_calls
    assert math.isnan(first_call.tool_calls[0].arguments["x"])


@dataclass(slots=True)
class _SlottedState:
    step: int


class _ExtraState(BaseModel):
    model_config = ConfigDict(extra="allow")


def _cyclic_list() -> list[Any]:
    value: list[Any] = []
    value.append(value)
    return value


@pytest.mark.parametrize(
    "value",
    [
        _SlottedState(step=1),
        _ExtraState.model_validate({"step": 1}),
        OrderedDict(step=1),
        _cyclic_list(),
    ],
)
async def test_model_event_input_refuses_object_metadata(value: Any) -> None:
    init_transcript(Transcript())
    message = ChatMessageUser(content="hi", metadata={"state": value})

    with pytest.raises(TypeError, match=r"metadata\['state'\]"):
        await get_model("mockllm/model").generate([message])


@pytest.mark.parametrize("value", [_SlottedState(step=1), [OrderedDict(step=1)]])
async def test_model_event_input_refuses_object_tool_arguments(value: Any) -> None:
    init_transcript(Transcript())
    message = ChatMessageAssistant(
        content="",
        tool_calls=[ToolCall(id="c1", function="f", arguments={"state": value})],
    )

    with pytest.raises(
        TypeError, match=r"tool_calls\[0\]\.arguments\['state'\].* has type"
    ):
        await get_model("mockllm/model").generate([message])
