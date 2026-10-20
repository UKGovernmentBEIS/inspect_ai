"""`ModelEvent.input` records the messages as they were when the model was called."""

import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

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
from inspect_ai.model._model import _snapshot_messages, use_model_event_sink
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


class _Sink:
    def __init__(self) -> None:
        self.events: list[ModelEvent] = []

    def on_pending(self, event: ModelEvent) -> None:
        self.events.append(event)

    def on_complete(self, event: ModelEvent) -> None:
        pass


async def test_model_event_input_snapshot_with_event_sink() -> None:
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    messages = _conversation()
    sink = _Sink()

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


async def test_model_event_input_reuses_id_less_snapshots() -> None:
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    user = ChatMessageUser.model_validate(
        {"role": "user", "content": "hi"}, context=get_deserializing_context()
    )
    assert user.id is None
    messages: list[ChatMessage] = [user]

    await model.generate(messages)
    await model.generate(messages)
    user.content = "edited"
    await model.generate(messages)

    first, second, third = _model_events()
    assert first.input[0] is second.input[0]
    assert second.input[0].content == "hi"
    assert third.input[0].content == "edited"


@pytest.mark.parametrize(
    "replacement,reused", [(float("nan"), True), (None, False), (math.inf, False)]
)
async def test_model_event_input_compares_nan_as_logged(
    replacement: float | None, reused: bool
) -> None:
    # logs write every NaN the same way but keep NaN, Infinity and null apart
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    nan = float("nan")
    assistant = ChatMessageAssistant(
        content="",
        tool_calls=[ToolCall(id="c1", function="f", arguments={"x": nan})],
    )
    messages: list[ChatMessage] = [assistant]

    await model.generate(messages)
    assert assistant.tool_calls
    assistant.tool_calls[0].arguments["x"] = replacement
    assert assistant.tool_calls[0].arguments["x"] is not nan
    await model.generate(messages)

    first, second = _model_events()
    assert (first.input[0] is second.input[0]) is reused
    for event, expected in ((first, nan), (second, replacement)):
        logged = event.input[0]
        assert isinstance(logged, ChatMessageAssistant) and logged.tool_calls
        assert json.dumps(logged.tool_calls[0].arguments["x"]) == json.dumps(expected)


@dataclass(slots=True)
class _SlottedState:
    step: int


async def test_model_event_input_copies_unserializable_metadata() -> None:
    # numpy arrays don't serialize, so the message is copied every time
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    message = ChatMessageUser(content="hi", metadata={"values": np.array([1, 2])})

    await model.generate([message])
    assert message.metadata is not None
    message.metadata["values"][0] = 99
    await model.generate([message])

    first, second = _model_events()
    assert first.input[0] is not second.input[0]
    assert first.input[0].metadata is not None
    assert second.input[0].metadata is not None
    assert first.input[0].metadata["values"].tolist() == [1, 2]
    assert second.input[0].metadata["values"].tolist() == [99, 2]


def test_model_event_input_snapshots_object_tool_arguments() -> None:
    # called directly: generate() itself fails here, since providers (and
    # mockllm's token count) JSON-encode the arguments
    state = _SlottedState(step=1)
    message = ChatMessageAssistant(
        content="",
        tool_calls=[ToolCall(id="c1", function="f", arguments={"state": state})],
    )

    [first] = _snapshot_messages([message])
    [second] = _snapshot_messages([message])
    state.step = 2
    [third] = _snapshot_messages([message])

    assert first is second
    steps = []
    for logged in (first, third):
        assert isinstance(logged, ChatMessageAssistant) and logged.tool_calls
        steps.append(logged.tool_calls[0].arguments["state"].step)
    assert steps == [1, 2]


async def test_model_event_input_reuses_deeply_nested_metadata() -> None:
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    nested: dict[str, Any] = {}
    inner = nested
    for _ in range(250):
        inner["k"] = {}
        inner = inner["k"]
    message = ChatMessageUser(content="hi", metadata={"nested": nested})

    await model.generate([message])
    await model.generate([message])

    first, second = _model_events()
    assert first.input[0] is second.input[0]
