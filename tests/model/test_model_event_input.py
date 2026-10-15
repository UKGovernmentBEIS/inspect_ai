"""`ModelEvent.input` records the messages as they were when the model was called."""

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
