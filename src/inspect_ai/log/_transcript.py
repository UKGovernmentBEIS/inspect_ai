import contextlib
from contextvars import ContextVar
from logging import getLogger
from typing import (
    Callable,
    Iterator,
    Sequence,
    overload,
)

from pydantic import (
    JsonValue,
)
from shortuuid import uuid

from inspect_ai._util.logger import warn_once
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._store import StoreEvent
from inspect_ai.event._timeline import Timeline
from inspect_ai.log._condense import (
    ATTACHMENT_PROTOCOL,
    WalkContext,
    events_attachment_fn,
    walk_model_call,
)
from inspect_ai.util._store import store, store_changes, store_jsonable

logger = getLogger(__name__)


class Transcript:
    """Transcript of events."""

    _event_loggers: list[Callable[[Event], None]]
    _context: WalkContext

    @overload
    def __init__(
        self,
        *,
        log_model_api: bool | None = None,
        bounded: bool | None = None,
        resident_tail: int = 100,
    ) -> None: ...

    @overload
    def __init__(
        self,
        events: list[Event],
        log_model_api: bool | None = None,
        bounded: bool | None = None,
        resident_tail: int = 100,
    ) -> None: ...

    def __init__(
        self,
        events: list[Event] | None = None,
        log_model_api: bool | None = None,
        bounded: bool | None = None,
        resident_tail: int = 100,
    ) -> None:
        self._event_loggers = []
        self._log_model_api = log_model_api
        self._context = WalkContext(message_cache={}, only_core=False)
        self._events: list[Event] = events if events is not None else []
        self._attachments: dict[str, str] = {}
        self._attachment_refcount: dict[str, int] = {}
        self._event_attachment_refs: dict[str, set[str]] = {}
        self._timelines: list[Timeline] = []
        self._model_call_counts: dict[str, int] = {}
        self._kept_event_ids: set[str] = set()
        self._bounded = bool(bounded) if bounded is not None else False
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
        self._resident_event_ids: set[str] = {
            self._event_key(event) for event in self._events
        }
        self._seen_event_ids: set[str] = set(self._resident_event_ids)
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
        """Events currently resident in memory.

        For unbounded transcripts this is the full event history. For bounded
        transcripts this may be only a resident suffix plus pinned events; use
        ``events_truncated`` to detect that older events have been evicted.
        """
        return self._events

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def events_truncated(self) -> bool:
        return self._events_truncated

    @property
    def last_event(self) -> Event | None:
        return self._events[-1] if self._events else None

    def recent_events(self, n: int | None = None) -> Sequence[Event]:
        if n is None:
            return self._events
        if n <= 0:
            return []
        return self._events[-n:]

    def events_since_last(self, event_type: type[Event]) -> list[Event]:
        if self._events_truncated:
            raise RuntimeError(
                "Full transcript history is not available from this Transcript"
            )
        events = list(self._events)
        for i in range(len(events) - 1, -1, -1):
            if isinstance(events[i], event_type):
                return events[i:]
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
        event_key = self._event_key(event)
        if event_key in self._seen_event_ids:
            raise ValueError(f"Duplicate event uuid: {event_key}")
        self._seen_event_ids.add(event_key)
        self._process_event(event)
        self._events.append(event)
        self._resident_event_ids.add(event_key)
        self._set_attachment_refs(event)
        self._event_count += 1
        self._update_pin_state(event)
        self._evict_events()

    def _event_updated(self, event: Event) -> None:
        if self._is_resident(event):
            self._process_event(event)
            self._set_attachment_refs(event)
            self._update_pin_state(event)
            self._evict_events()
        else:
            self._process_event(event, retain_attachments=False)
            self._prune_unreferenced_attachments()

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

        try:
            for event_logger in list(self._event_loggers):
                try:
                    event_logger(event)
                except Exception:
                    logger.warning("Transcript subscriber failed", exc_info=True)
        finally:
            # condense model event calls immediately to prevent O(N) memory usage
            if (
                retain_attachments
                and isinstance(event, ModelEvent)
                and event.call is not None
            ):
                event_fn = events_attachment_fn(self.attachments)
                event.call = walk_model_call(event.call, event_fn, self._context)

    def _set_attachment_refs(self, event: Event) -> None:
        if not self._bounded:
            return

        event_key = self._event_key(event)
        previous_refs = self._event_attachment_refs.get(event_key)
        current_refs = self._attachment_refs(event)
        if previous_refs is None:
            for ref in current_refs:
                self._attachment_refcount[ref] = (
                    self._attachment_refcount.get(ref, 0) + 1
                )
        else:
            for ref in previous_refs - current_refs:
                self._decrement_attachment_ref(ref)
            for ref in current_refs - previous_refs:
                self._attachment_refcount[ref] = (
                    self._attachment_refcount.get(ref, 0) + 1
                )
        if current_refs:
            self._event_attachment_refs[event_key] = current_refs
        else:
            self._event_attachment_refs.pop(event_key, None)

    def _attachment_refs(self, event: Event) -> set[str]:
        refs: set[str] = set()

        def collect(value: object) -> None:
            if isinstance(value, str):
                if value.startswith(ATTACHMENT_PROTOCOL):
                    refs.add(value.removeprefix(ATTACHMENT_PROTOCOL))
            elif isinstance(value, dict):
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(event.model_dump(mode="python"))
        return refs

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
        retained_events: list[Event | None] = []
        evictable_indices: list[int] = []
        evicted = False

        for event in self._events:
            event_key = self._event_key(event)
            retained_events.append(event)
            if (
                event_key in self._pinned_event_ids
                or event_key in self._pending_event_ids
            ):
                continue

            evictable_indices.append(len(retained_events) - 1)
            if len(evictable_indices) > resident_tail:
                evicted = True
                evict_index = evictable_indices.pop(0)
                evict_event = retained_events[evict_index]
                retained_events[evict_index] = None
                if evict_event is not None:
                    evict_key = self._event_key(evict_event)
                    for ref in self._event_attachment_refs.pop(evict_key, set()):
                        self._decrement_attachment_ref(ref)

        if evicted:
            self._events = [event for event in retained_events if event is not None]
            self._events_truncated = True
        self._prune_pin_state()

    def _prune_pin_state(self) -> None:
        resident_event_keys = {self._event_key(event) for event in self._events}
        self._resident_event_ids = resident_event_keys
        self._pinned_event_ids.intersection_update(resident_event_keys)
        self._pending_event_ids.intersection_update(resident_event_keys)

    def _is_resident(self, event: Event) -> bool:
        return self._event_key(event) in self._resident_event_ids

    def _update_pin_state(self, event: Event) -> None:
        event_key = self._event_key(event)
        if isinstance(event, SampleInitEvent):
            self._pinned_event_ids.add(event_key)
        if event.pending:
            self._pending_event_ids.add(event_key)
        else:
            self._pending_event_ids.discard(event_key)

    def _event_key(self, event: Event) -> str:
        if event.uuid is None:
            event.uuid = uuid()
        return event.uuid

    def subscribe(self, event_logger: Callable[[Event], None]) -> Callable[[], None]:
        self._event_loggers.append(event_logger)

        def unsubscribe() -> None:
            if event_logger in self._event_loggers:
                self._event_loggers.remove(event_logger)

        return unsubscribe


def transcript() -> Transcript:
    """Get the current `Transcript`."""
    active_transcript = _transcript.get()
    if active_transcript is None:
        active_transcript = Transcript()
        _transcript.set(active_transcript)
    return active_transcript


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
