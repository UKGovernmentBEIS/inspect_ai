from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import TYPE_CHECKING

from inspect_ai.event._event import Event
from inspect_ai.event._pool import (
    materialize_pooled_events,
    resolve_model_event_calls,
    resolve_model_event_inputs,
)
from inspect_ai.event._validate import validate_events

if TYPE_CHECKING:
    from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
    from inspect_ai.log._recorders.buffer.history import SampleHistory
    from inspect_ai.log._transcript import TranscriptHistoryProvider
    from inspect_ai.util._checkpoint._transcript_store import CheckpointTranscriptStore


class BufferTranscriptHistoryProvider:
    def __init__(
        self,
        buffer_db: SampleBufferDatabase,
        sample_id: str | int,
        epoch: int,
    ) -> None:
        self._buffer_db = buffer_db
        self._sample_id = sample_id
        self._epoch = epoch

    @property
    def event_count(self) -> int:
        return self._buffer_db.sample_event_count(self._sample_id, self._epoch)

    def events(self) -> Sequence[Event]:
        return self._events()

    def iter_events(self) -> Iterator[Event]:
        return self._iter_events()

    def recent_events(self, n: int | None = None) -> Sequence[Event]:
        if n is None:
            return self._events()
        if n <= 0:
            return []
        with self._buffer_db.open_sample_history_tail(
            self._sample_id, self._epoch, n
        ) as history:
            return _materialize_events(history)

    def events_from(self, start: int) -> Sequence[Event]:
        if start <= 0:
            return self._events()
        with self._buffer_db.open_sample_history_from(
            self._sample_id, self._epoch, start
        ) as history:
            return _materialize_events(history)

    def events_since_last(self, event_type: type[Event]) -> list[Event]:
        suffix: list[Event] = []
        with self._buffer_db.open_sample_history(
            self._sample_id, self._epoch
        ) as history:
            for event in _iter_materialized_events(history):
                if isinstance(event, event_type):
                    suffix = [event]
                else:
                    suffix.append(event)
        return suffix

    def attachments(self) -> Mapping[str, str]:
        with self._buffer_db.open_sample_history(
            self._sample_id, self._epoch
        ) as history:
            return dict(history.attachments)

    def attachment(self, hash: str) -> str | None:
        return self._buffer_db.sample_attachment(self._sample_id, self._epoch, hash)

    def import_checkpoint_events(
        self, transcript_store: "CheckpointTranscriptStore"
    ) -> int:
        return self._buffer_db.import_checkpoint_events(
            self._sample_id, self._epoch, transcript_store
        )

    def _events(self) -> list[Event]:
        with self._buffer_db.open_sample_history(
            self._sample_id, self._epoch
        ) as history:
            return _materialize_events(history)

    def _iter_events(self) -> Iterator[Event]:
        with self._buffer_db.open_sample_history(
            self._sample_id, self._epoch
        ) as history:
            yield from _iter_materialized_events(history)


def _materialize_events(history: SampleHistory) -> list[Event]:
    return materialize_pooled_events(
        history.iter_events(),
        history.events_data["messages"],
        history.events_data["calls"],
    )


def _iter_materialized_events(history: SampleHistory) -> Iterator[Event]:
    message_pool = history.events_data["messages"]
    call_pool = history.events_data["calls"]
    for raw_event in history.iter_events():
        event = validate_events([raw_event])[0]
        event = resolve_model_event_inputs([event], message_pool)[0]
        yield resolve_model_event_calls([event], call_pool)[0]


if TYPE_CHECKING:
    _buffer_transcript_history_provider: type[TranscriptHistoryProvider] = (
        BufferTranscriptHistoryProvider
    )
