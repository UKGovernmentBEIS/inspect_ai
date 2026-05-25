from collections.abc import Iterator, Sequence

from inspect_ai._util.list import find_last_match
from inspect_ai.event._event import Event
from inspect_ai.util._checkpoint._event_store import CheckpointEventStore


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

    def attachments(self) -> dict[str, str]:
        return dict(self._attachments)

    def attachment(self, hash: str) -> str | None:
        return self._attachments.get(hash)

    def import_checkpoint_events(self, event_store: CheckpointEventStore) -> int:
        for event in self._events:
            event_store.merge_event(event, self._attachments.get)
        event_store.merge_attachments(self._attachments)
        return len(self._events)
