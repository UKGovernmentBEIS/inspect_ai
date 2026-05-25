import contextlib
import os
from collections import deque
from contextvars import ContextVar
from logging import getLogger
from typing import (
    TYPE_CHECKING,
    Callable,
    Deque,
    Iterator,
    Literal,
    Mapping,
    Protocol,
    Sequence,
    TypeVar,
    overload,
)

from pydantic import (
    JsonValue,
)
from shortuuid import uuid

from inspect_ai._util.list import find_last_match
from inspect_ai._util.logger import warn_once
from inspect_ai.event._base import BaseEvent
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._interrupt import InterruptEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._store import StoreEvent
from inspect_ai.event._timeline import Timeline
from inspect_ai.log._condense import (
    WalkContext,
    attachment_refs_from_value,
    events_attachment_fn,
    walk_model_call,
)
from inspect_ai.util._store import store, store_changes, store_jsonable

if TYPE_CHECKING:
    from inspect_ai.util._checkpoint._event_store import CheckpointEventStore

logger = getLogger(__name__)


ET = TypeVar("ET", bound=BaseEvent)


def transcript_bounded_enabled() -> bool:
    value = os.environ.get("INSPECT_TRANSCRIPT_BOUNDED")
    if value is None:
        return False
    return value.strip().lower() not in ("0", "false", "no", "off")


class TranscriptHistoryProvider(Protocol):
    @property
    def event_count(self) -> int: ...

    def iter_events(self) -> Iterator[Event]: ...

    def events(self) -> Sequence[Event]: ...

    def recent_events(self, n: int | None = None) -> Sequence[Event]: ...

    def events_from(self, start: int) -> Sequence[Event]: ...

    def events_since_last(self, event_type: type[Event]) -> list[Event]: ...

    def attachments(self) -> Mapping[str, str]: ...

    def attachment(self, hash: str) -> str | None: ...

    def import_checkpoint_events(self, event_store: "CheckpointEventStore") -> int: ...


class _TranscriptEventsView(Sequence[Event]):
    def __init__(self, transcript: "Transcript") -> None:
        self._transcript = transcript

    def __len__(self) -> int:
        return self._transcript.event_count

    def __iter__(self) -> Iterator[Event]:
        provider = self._transcript._history_provider
        if provider is None:
            return iter(self._transcript._events)
        return provider.iter_events()

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, BaseEvent):
            return False
        item_key = item.uuid
        if item_key is None:
            return any(event is item for event in self._transcript._events)
        return any(event.uuid == item_key for event in self._transcript._events)

    @overload
    def __getitem__(self, index: int) -> Event: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Event]: ...

    def __getitem__(self, index: int | slice) -> Event | Sequence[Event]:
        if isinstance(index, slice):
            return self._slice(index)
        if index == -1:
            provider = self._transcript._history_provider
            if provider is not None:
                recent_events = provider.recent_events(1)
                if not recent_events:
                    raise IndexError("Transcript events index out of range")
                return recent_events[-1]
            last_event = self._transcript.last_event
            if last_event is None:
                raise IndexError("Transcript events index out of range")
            return last_event
        if index >= 0:
            provider = self._transcript._history_provider
            if provider is not None:
                for event_index, event in enumerate(provider.iter_events()):
                    if event_index == index:
                        return event
                raise IndexError("Transcript events index out of range")
        events = self._materialize()
        return events[index]

    def _slice(self, index: slice) -> Sequence[Event]:
        if index == slice(None, None, None):
            provider = self._transcript._history_provider
            if provider is None:
                return self._transcript._events[:]
            return provider.events()
        if index.step is None and index.stop is None and index.start is not None:
            start = index.start
            provider = self._transcript._history_provider
            if provider is not None:
                if start >= 0:
                    return provider.events_from(start)
                return provider.recent_events(-start)
        return self._materialize()[index]

    def _materialize(self) -> list[Event]:
        provider = self._transcript._history_provider
        if provider is None:
            return list(self._transcript._events)
        return list(provider.events())


class Transcript:
    """Transcript of events."""

    _event_logger: Callable[[Event], None] | None
    _event_loggers: list[Callable[[Event], None]]
    _additional_subscribers: list[Callable[[Event], None]]
    _notifying_subscribers: set[int]
    _context: WalkContext

    @overload
    def __init__(
        self,
        *,
        log_model_api: bool | None = None,
        bounded: bool = False,
        resident_tail: int = 100,
        history_provider: TranscriptHistoryProvider | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        events: list[Event],
        log_model_api: bool | None = None,
        bounded: bool = False,
        resident_tail: int = 100,
        history_provider: TranscriptHistoryProvider | None = None,
    ) -> None: ...

    def __init__(
        self,
        events: list[Event] | None = None,
        log_model_api: bool | None = None,
        bounded: bool = False,
        resident_tail: int = 100,
        history_provider: TranscriptHistoryProvider | None = None,
    ) -> None:
        self._event_logger = None
        self._event_loggers = []
        self._additional_subscribers = self._event_loggers
        self._log_model_api = log_model_api
        self._context = WalkContext(message_cache={}, only_core=False)
        self._events: list[Event] = self._copy_uuidless_events(events or [])
        self._history_provider = history_provider
        self._events_view = _TranscriptEventsView(self)
        self._attachments: dict[str, str] = {}
        self._attachment_refcount: dict[str, int] = {}
        self._event_attachment_refs: dict[str, set[str]] = {}
        self._timelines: list[Timeline] = []
        self._model_call_counts: dict[str, int] = {}
        self._kept_event_ids: set[str] = set()
        self._bounded = bounded
        self._resident_tail = resident_tail
        self._event_count = len(self._events)
        self._events_truncated = False
        self._pinned_event_ids: set[str] = {
            self._event_key(event)
            for event in self._events
            if isinstance(event, SampleInitEvent)
        }
        self._pending_event_ids: set[str] = {
            self._event_key(event) for event in self._events if event.pending
        }
        self._pending_events: dict[str, Event] = {
            self._event_key(event): event for event in self._events if event.pending
        }
        self._resident_event_ids: set[str] = {
            self._event_key(event) for event in self._events
        }
        self._evictable_event_ids: Deque[str] = deque(
            event_key
            for event in self._events
            if (event_key := self._event_key(event))
            not in self._pinned_event_ids | self._pending_event_ids
        )
        # Re-entry guard for subscriber callbacks. If a subscriber logs while
        # handling an event, the resulting LoggerEvent should still reach all
        # other subscribers, but not recursively notify the same subscriber.
        self._notifying_subscribers = set()
        self._evict_events()

    def info(self, data: JsonValue, *, source: str | None = None) -> None:
        """Add an `InfoEvent` to the transcript.

        Args:
           data: Data associated with the event.
           source: Optional event source.
        """
        self._event(InfoEvent(source=source, data=data))

    @contextlib.contextmanager
    def step(self, name: str, type: str | None = None) -> Iterator[None]:
        """Context manager for recording StepEvent.

        The `step()` context manager is deprecated and will be removed in a future version.
        Please use the `span()` context manager instead.

        Args:
            name (str): Step name.
            type (str | None): Optional step type.
        """
        warn_once(
            logger,
            "The `transcript().step()` context manager is deprecated and will "
            + "be removed in a future version. Please replace the call to step() "
            + "with a call to span().",
        )
        yield

    @property
    def events(self) -> Sequence[Event]:
        """Compatibility view of the logical event history.

        For unbounded or provider-free transcripts this returns resident events.
        For bounded transcripts with a history provider this returns a lazy view
        over the full logical history. Iteration, random indexing, and some slices
        may read and materialize events from the provider; hot paths should use
        `resident_events`, `event_count`, `last_event`, or `recent_events()`.
        """
        if self._history_provider is None:
            return self._events
        return self._events_view

    @property
    def resident_events(self) -> Sequence[Event]:
        """Events currently resident in memory for live/hot-path consumers."""
        return self._events

    @property
    def pending_events(self) -> Sequence[Event]:
        """Currently-pending events in insertion order."""
        return list(self._pending_events.values())

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def resident_events_truncated(self) -> bool:
        return self._events_truncated

    @property
    def full_history_available(self) -> bool:
        return not self._events_truncated or self._history_provider is not None

    @property
    def last_event(self) -> Event | None:
        return self._events[-1] if self._events else None

    def recent_events(self, n: int | None = None) -> Sequence[Event]:
        if n is not None and n <= 0:
            return []
        if self._history_provider is None:
            return self._events if n is None else self._events[-n:]
        if not self._events_truncated and n is not None and n <= len(self._events):
            return self._events[-n:]
        return self._history_provider.recent_events(n)

    def events_since_last(self, event_type: type[Event]) -> list[Event]:
        if self._events_truncated:
            if self._history_provider is not None:
                return self._history_provider.events_since_last(event_type)
            raise RuntimeError(
                "Full transcript history is not available from this Transcript"
            )
        events = list(self._events)
        index = find_last_match(events, lambda event: isinstance(event, event_type))
        if index is not None:
            return events[index:]
        return events

    @property
    def attachments(self) -> dict[str, str]:
        return self._attachments

    @property
    def timelines(self) -> Sequence[Timeline]:
        return self._timelines

    def add_timeline(self, timeline: Timeline) -> None:
        """Add a named timeline to the transcript.

        Args:
            timeline: Timeline to add.

        Raises:
            ValueError: If a timeline with the same name already exists.
        """
        for existing in self._timelines:
            if existing.name == timeline.name:
                raise ValueError(
                    f"A timeline with the name '{timeline.name}' already exists."
                )
        self._timelines.append(timeline)

    def _event(self, event: Event) -> None:
        event_key = self._ensure_event_key(event)
        if event_key in self._resident_event_ids:
            raise ValueError(f"Duplicate event uuid: {event_key}")
        self._process_event(event)
        self._events.append(event)
        self._resident_event_ids.add(event_key)
        self._set_attachment_refs(event)
        self._event_count += 1
        self._update_pin_state(event)
        self._update_pending(event)
        self._update_evictable_state(event)
        self._evict_events()

    def _extend_restored_events(
        self, events: Sequence[Event], attachments: Mapping[str, str]
    ) -> None:
        events = self._copy_uuidless_events(events)
        event_keys: list[str] = []
        new_event_keys: set[str] = set()
        for event in events:
            event_key = self._ensure_event_key(event)
            if event_key in self._resident_event_ids or event_key in new_event_keys:
                raise ValueError(f"Duplicate event uuid: {event_key}")
            event_keys.append(event_key)
            new_event_keys.add(event_key)

        self._attachments.update(attachments)
        for event, event_key in zip(events, event_keys):
            self._events.append(event)
            self._resident_event_ids.add(event_key)
            self._set_attachment_refs(event)
            self._event_count += 1
            self._update_pin_state(event)
            self._update_pending(event)
            self._update_evictable_state(event)
        self._evict_events()

    def _event_updated(self, event: Event) -> None:
        if self._is_resident(event):
            self._process_event(event)
            self._set_attachment_refs(event)
            self._update_pin_state(event)
            self._update_pending(event)
            self._update_evictable_state(event)
            self._evict_events()
        else:
            self._process_event(event, retain_attachments=False)
            self._update_pending(event)
            self._prune_unreferenced_attachments()

    def _update_pending(self, event: Event) -> None:
        """Reflect ``event``'s current pending state in the sidecar."""
        event_key = self._event_key(event)
        if event.pending:
            self._pending_events[event_key] = event
        else:
            self._pending_events.pop(event_key, None)

    def _process_event(self, event: Event, *, retain_attachments: bool = True) -> None:
        if isinstance(event, ModelEvent) and event.call is not None:
            is_error = bool(event.call.error)
            if not is_error:
                if self._log_model_api is True:
                    pass
                elif self._log_model_api is False:
                    event.call = None
                else:
                    event_key = self._event_key(event)
                    if event_key not in self._kept_event_ids:
                        from inspect_ai._util.constants import (
                            DEFAULT_LOG_MODEL_API_CALLS,
                        )

                        count = self._model_call_counts.get(event.model, 0)
                        if count < DEFAULT_LOG_MODEL_API_CALLS:
                            self._model_call_counts[event.model] = count + 1
                            self._kept_event_ids.add(event_key)
                        else:
                            event.call = None

            if retain_attachments and event.call is not None:
                event_fn = events_attachment_fn(self.attachments)
                event.call = walk_model_call(event.call, event_fn, self._context)

        for event_logger in list(self._event_loggers):
            subscriber_id = id(event_logger)
            if subscriber_id in self._notifying_subscribers:
                continue
            self._notifying_subscribers.add(subscriber_id)
            try:
                try:
                    event_logger(event)
                except Exception:
                    logger.warning("Transcript subscriber failed", exc_info=True)
            finally:
                self._notifying_subscribers.remove(subscriber_id)

    def _set_attachment_refs(self, event: Event) -> None:
        if not self._bounded:
            return

        event_key = self._event_key(event)
        previous_refs = self._event_attachment_refs.get(event_key, set())
        current_refs = self._attachment_refs(event)
        for ref in previous_refs - current_refs:
            self._decrement_attachment_ref(ref)
        for ref in current_refs - previous_refs:
            self._attachment_refcount[ref] = self._attachment_refcount.get(ref, 0) + 1
        if current_refs:
            self._event_attachment_refs[event_key] = current_refs
        else:
            self._event_attachment_refs.pop(event_key, None)

    def _attachment_refs(self, event: Event) -> set[str]:
        return attachment_refs_from_value(event.model_dump(mode="python"))

    def _decrement_attachment_ref(self, ref: str) -> None:
        count = self._attachment_refcount.get(ref, 0) - 1
        if count > 0:
            self._attachment_refcount[ref] = count
        else:
            self._attachment_refcount.pop(ref, None)
            self._attachments.pop(ref, None)

    def _prune_unreferenced_attachments(self) -> None:
        if not self._bounded:
            return

        for ref in list(self._attachments):
            if ref not in self._attachment_refcount:
                self._attachments.pop(ref, None)

    def _evict_events(self) -> None:
        if not self._bounded:
            return

        resident_tail = max(self._resident_tail, 0)
        evicted_event_ids: set[str] = set()
        while len(self._evictable_event_ids) > resident_tail:
            event_key = self._evictable_event_ids.popleft()
            if not self._is_evictable_event_key(event_key):
                continue
            evicted_event_ids.add(event_key)

        if evicted_event_ids:
            self._events = [
                event
                for event in self._events
                if self._event_key(event) not in evicted_event_ids
            ]
            self._resident_event_ids.difference_update(evicted_event_ids)
            self._events_truncated = True
            self._prune_pin_state()

    def _prune_pin_state(self) -> None:
        resident_event_keys = self._resident_event_ids
        self._pinned_event_ids.intersection_update(resident_event_keys)
        self._pending_event_ids.intersection_update(resident_event_keys)
        self._evictable_event_ids = deque(
            event_key
            for event_key in self._evictable_event_ids
            if self._is_evictable_event_key(event_key)
        )
        if self._bounded:
            self._kept_event_ids.intersection_update(resident_event_keys)
            self._prune_attachment_refs(resident_event_keys)

    def _prune_attachment_refs(self, resident_event_keys: set[str]) -> None:
        for event_key in list(self._event_attachment_refs):
            if event_key in resident_event_keys:
                continue
            for ref in self._event_attachment_refs.pop(event_key):
                self._decrement_attachment_ref(ref)

    def _is_resident(self, event: Event) -> bool:
        return event.uuid is not None and event.uuid in self._resident_event_ids

    def _update_pin_state(self, event: Event) -> None:
        event_key = self._event_key(event)
        if isinstance(event, SampleInitEvent):
            self._pinned_event_ids.add(event_key)
        if event.pending:
            self._pending_event_ids.add(event_key)
        else:
            self._pending_event_ids.discard(event_key)

    def _update_evictable_state(self, event: Event) -> None:
        event_key = self._event_key(event)
        if not self._is_evictable_event_key(event_key):
            return
        if event_key in self._evictable_event_ids:
            return

        for index, resident_event in enumerate(self._events):
            if resident_event is event:
                self._evictable_event_ids.insert(index, event_key)
                return
        self._evictable_event_ids.append(event_key)

    def _is_evictable_event_key(self, event_key: str) -> bool:
        return (
            event_key in self._resident_event_ids
            and event_key not in self._pinned_event_ids
            and event_key not in self._pending_event_ids
        )

    def _event_key(self, event: Event) -> str:
        if event.uuid is None:
            raise ValueError("Transcript event is missing uuid")
        return event.uuid

    def _ensure_event_key(self, event: Event) -> str:
        if event.uuid is None:
            event.uuid = uuid()
        return event.uuid

    @staticmethod
    def _copy_uuidless_events(events: Sequence[Event]) -> list[Event]:
        copied_events: list[Event] = []
        for event in events:
            if event.uuid is None:
                event = event.model_copy()
                event.uuid = uuid()
            copied_events.append(event)
        return copied_events

    def subscribe(self, event_logger: Callable[[Event], None]) -> Callable[[], None]:
        """Subscribe to transcript event notifications.

        The callback is invoked when an event is added and when a resident event
        is updated. Subscriber exceptions are logged and do not prevent other
        subscribers or normal transcript processing. Returns an unsubscribe
        callback that removes the subscription.
        """
        self._event_loggers.append(event_logger)

        def unsubscribe() -> None:
            if event_logger in self._event_loggers:
                self._event_loggers.remove(event_logger)

        return unsubscribe

    def _subscribe(self, event_logger: Callable[[Event], None]) -> None:
        """Legacy subscription API for eval logging."""
        if self._event_logger is not None and self._event_logger in self._event_loggers:
            self._event_loggers.remove(self._event_logger)
        self._event_logger = event_logger
        self._event_loggers.append(event_logger)

    def _add_subscriber(self, callback: Callable[[Event], None]) -> Callable[[], None]:
        return self.subscribe(callback)


def transcript() -> Transcript:
    """Get the current `Transcript`."""
    active_transcript = _transcript.get()
    if active_transcript is None:
        active_transcript = Transcript()
        _transcript.set(active_transcript)
    return active_transcript


def record_interrupt_event(
    *,
    source: Literal["user_cancel", "limit", "system"],
    interrupted: Literal["generate", "tool_call", "between_turns"],
    interrupted_tool_call_id: str | None = None,
    interrupted_model_event_id: str | None = None,
) -> None:
    """Append an `InterruptEvent` to the current transcript.

    Internal helper used by Inspect's cancellation machinery — the ACP
    `cancel_current_turn` path, sample-level limit handlers, and system
    shutdown. Not a public API for agent authors.
    """
    transcript()._event(
        InterruptEvent(
            source=source,
            interrupted=interrupted,
            interrupted_tool_call_id=interrupted_tool_call_id,
            interrupted_model_event_id=interrupted_model_event_id,
        )
    )


@contextlib.contextmanager
def track_store_changes() -> Iterator[None]:
    before = store_jsonable(store())
    yield
    after = store_jsonable(store())

    changes = store_changes(before, after)
    if changes:
        transcript()._event(StoreEvent(changes=changes))


def init_transcript(transcript: Transcript) -> None:
    _transcript.set(transcript)


_transcript: ContextVar[Transcript | None] = ContextVar(
    "subtask_transcript", default=None
)
