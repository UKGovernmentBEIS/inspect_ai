from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any, Literal

from inspect_ai._util.list import find_last_match
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.log._recorders.buffer.types import TranscriptEventSink
from inspect_ai.model import ChatMessage, GenerateConfig, ModelOutput
from inspect_ai.model._model_call import ModelCall


def make_model_event(
    messages: list[ChatMessage],
    *,
    uuid: str | None = None,
    content: str | None = None,
    model: str = "test",
    tool_choice: Literal["auto", "any", "none"] = "auto",
    call: ModelCall | None = None,
    timestamp: datetime | None = None,
    working_start: float | None = None,
) -> ModelEvent:
    kwargs: dict[str, Any] = {}
    if uuid is not None:
        kwargs["uuid"] = uuid
    if timestamp is not None:
        kwargs["timestamp"] = timestamp
    if working_start is not None:
        kwargs["working_start"] = working_start
    return ModelEvent(
        model=model,
        input=messages,
        tools=[],
        tool_choice=tool_choice,
        config=GenerateConfig(),
        output=ModelOutput.from_content(model, content)
        if content is not None
        else ModelOutput(),
        call=call,
        **kwargs,
    )


def assert_spans_balanced(events: Sequence[Event]) -> None:
    """Assert every span has exactly one begin and end.

    Spans are parent-id based, not strict stack brackets: concurrent sibling
    spans can interleave, and background child spans can outlive the dispatching
    parent span.
    """
    begin_by_id: dict[str, int] = {}
    end_by_id: dict[str, int] = {}
    for idx, event in enumerate(events):
        if isinstance(event, SpanBeginEvent):
            assert event.id not in begin_by_id, f"duplicate span_begin {event.id}"
            begin_by_id[event.id] = idx
        elif isinstance(event, SpanEndEvent):
            assert event.id in begin_by_id, f"span_end {event.id} with no begin"
            assert event.id not in end_by_id, f"duplicate span_end {event.id}"
            end_by_id[event.id] = idx

    unclosed = [span_id for span_id in begin_by_id if span_id not in end_by_id]
    assert not unclosed, f"{len(unclosed)} unclosed span(s): {unclosed}"


class FakeTranscriptHistoryProvider:
    def __init__(
        self, events: Sequence[Event], attachments: dict[str, str] | None = None
    ) -> None:
        self._events = list(events)
        self._attachments = dict(attachments or {})

    @property
    def event_count(self) -> int:
        return len(self._events)

    def events(self) -> Sequence[Event]:
        return list(self._events)

    def iter_events(self) -> Iterator[Event]:
        return iter(self._events)

    def recent_events(self, n: int | None = None) -> Sequence[Event]:
        if n is None:
            return list(self._events)
        if n <= 0:
            return []
        return list(self._events[-n:])

    def events_from(self, start: int) -> Sequence[Event]:
        return list(self._events[start:])

    def events_since_last(self, event_type: type[Event]) -> list[Event]:
        events = list(self._events)
        index = find_last_match(events, lambda event: isinstance(event, event_type))
        if index is not None:
            return events[index:]
        return events

    def contains_event(self, event_id: str) -> bool:
        return any(event.uuid == event_id for event in self._events)

    def attachments(self) -> dict[str, str]:
        return dict(self._attachments)

    def attachment(self, hash: str) -> str | None:
        return self._attachments.get(hash)

    def export_transcript_events(self, transcript_store: TranscriptEventSink) -> int:
        for event in self._events:
            assert event.uuid is not None
            transcript_store.merge_condensed_event(
                event.uuid,
                event.model_dump(mode="json", exclude_none=True),
                self._attachments.get,
            )
        transcript_store.merge_attachment_refs(
            set(self._attachments), self._attachments.get
        )
        return len(self._events)
