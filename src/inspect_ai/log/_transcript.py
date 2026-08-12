import contextlib
import copy
import os
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from logging import getLogger
from typing import (
    TYPE_CHECKING,
    Literal,
    NamedTuple,
    Protocol,
    TypeVar,
    overload,
)

from pydantic import (
    JsonValue,
)
from shortuuid import uuid

from inspect_ai._util.constants import SKIP_TRANSCRIPT_DISPATCH
from inspect_ai._util.list import find_last_match
from inspect_ai._util.logger import warn_once
from inspect_ai.event._base import BaseEvent
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._interrupt import InterruptEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._pool import _CALL_MESSAGE_KEYS, _strict_eq
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._store import StoreEvent
from inspect_ai.event._timeline import Timeline
from inspect_ai.log._condense import (
    ATTACHMENT_PROTOCOL,
    WalkContext,
    attachment_refs_from_object,
    events_attachment_fn,
    walk_json_dict,
    walk_json_value,
    walk_model_call,
)
from inspect_ai.model._chat_message import ChatMessageBase
from inspect_ai.model._model_call import ModelCall
from inspect_ai.util._store import store, store_changes, store_jsonable

if TYPE_CHECKING:
    from inspect_ai.log._recorders.buffer.types import TranscriptEventSink

logger = getLogger(__name__)


ET = TypeVar("ET", bound=BaseEvent)


@dataclass(frozen=True)
class _TranscriptSubscription:
    id: int
    callback: Callable[[Event], None]


class _EventRefs(NamedTuple):
    """Result of scanning one event for attachment references."""

    refs: set[str]
    """Attachment hashes the event references."""

    message_ids: set[str]
    """`ChatMessage.id`s encountered during the scan (memo lifetime sidecar)."""


def transcript_bounded_enabled() -> bool:
    value = os.environ.get("INSPECT_TRANSCRIPT_BOUNDED")
    if value is None:
        return False
    return value.strip().lower() not in ("0", "false", "no", "off")


DEFAULT_RESIDENT_TAIL = 100
"""Default number of most-recent events a bounded transcript keeps in memory.

Shared source of truth for the resident window. Consumers that read a
recent slice of history (e.g. the ACP replay-on-attach in
``agent/_acp/session_router.py``, whose ``REPLAY_MAX_EVENTS`` is aligned to
this value) can rely on that slice being served from resident,
attachment-resolved memory rather than re-materialized from the buffer DB.
"""


CALL_WALK_CACHE_SLOTS = 8
"""Retained request lineages for the transcript call-condense cache.

Each generate stream produces two lineages per turn (the raw request at
call-registration/completion, and the transcript-condensed form the
timestamp update re-notifies), so 8 slots cover ~4 interleaved streams
with distinct request prefixes (fork()/collect()/parallel tools funnel
into one sample transcript). Streams sharing a pre-fork history prefix
fork into separate slots (a partial prefix match appends a sibling
lineage rather than replacing the matched slot), so they keep prefix-
hitting independently. The residual cost of fork fan-out is slot-count
pressure: enough concurrent lineages evict each other via LRU, which
degrades to a full walk — never worse.
"""


_MESSAGE_REFS_BUCKET_LIMIT = 4
"""Max cached content variants per message id.

Buckets exist for same-id variants (raw agent-state vs condensed
restored-event messages after a resume) — legitimately 2. Third-party
code that rewrites content via model_copy while keeping the id would
otherwise grow a bucket without bound, pinning every old payload. The
memo is an accelerator: dropping the oldest variant is always safe (it
re-scans on next sight).
"""


@dataclass
class _CallWalkSlot:
    """One retained request lineage for `Transcript._condense_model_call`.

    ``pre_walk`` and ``walked`` are cache-owned deep copies (strings shared —
    deepcopy treats str as atomic): the copy-on-write walkers alias unchanged
    subtrees of the caller's live request, and callers can mutate
    ``call.request`` in place (same hazard `CallPoolIndex.set_prev`
    documents). ``attachments`` holds the (hash, content) pairs walking each
    message created, so prefix reuse can re-assert content that bounded-mode
    refcounting has since pruned from ``Transcript._attachments``.
    """

    key: str
    pre_walk: list[JsonValue] = field(default_factory=list)
    walked: list[JsonValue] = field(default_factory=list)
    attachments: list[list[tuple[str, str]]] = field(default_factory=list)


def _recording_attachment_fn(
    inner: Callable[[str], str], created: list[tuple[str, str]]
) -> Callable[[str], str]:
    """Wrap a content fn, recording (hash, content) for attachments it creates."""

    def fn(text: str) -> str:
        result = inner(text)
        if result is not text and result.startswith(ATTACHMENT_PROTOCOL):
            created.append((result[len(ATTACHMENT_PROTOCOL) :], text))
        return result

    return fn


class TranscriptHistoryUnavailableError(RuntimeError):
    """A transcript's event history can no longer be served.

    Raised by the bounded-memory history accessors when evicted events can't
    be materialized: either the transcript has no history provider, or the
    provider's backing store has been torn down or deleted (eg. the realtime
    sample buffer racing eval teardown). Storage-agnostic — consumers catch
    this rather than the backing store's own exception types. A
    ``RuntimeError`` subclass so callers handling "history not available"
    generically keep working.
    """


class TranscriptHistoryProvider(Protocol):
    @property
    def event_count(self) -> int: ...

    def iter_events(self) -> Iterator[Event]: ...

    def events(self) -> Sequence[Event]: ...

    def recent_events(self, n: int | None = None) -> Sequence[Event]: ...

    def events_from(self, start: int, limit: int | None = None) -> Sequence[Event]: ...

    def events_since_last(self, event_type: type[Event]) -> list[Event]: ...

    def contains_event(self, event_id: str) -> bool: ...

    def attachments(self) -> Mapping[str, str]: ...

    def attachment(self, hash: str) -> str | None: ...

    def export_transcript_events(
        self, transcript_store: "TranscriptEventSink"
    ) -> int: ...


class _TranscriptEventsView(Sequence[Event]):
    def __init__(self, transcript: "Transcript") -> None:
        self._transcript = transcript

    def __len__(self) -> int:
        return self._transcript.history.event_count

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
        if any(event.uuid == item_key for event in self._transcript._events):
            return True
        provider = self._transcript._history_provider
        if provider is None:
            return False
        if not self._transcript._events_truncated:
            return False
        return provider.contains_event(item_key)

    @overload
    def __getitem__(self, index: int) -> Event: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Event]: ...

    def __getitem__(self, index: int | slice) -> Event | Sequence[Event]:
        if isinstance(index, slice):
            return self._slice(index)
        if index == -1:
            if self._transcript._history_provider is not None:
                recent_events = self._transcript.history.recent_events(1)
                if not recent_events:
                    raise IndexError("Transcript events index out of range")
                return recent_events[-1]
            last_event = self._transcript.history.last_event
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
                window = self._transcript._trailing_window(-start)
                if window is not None:
                    return window
                return provider.recent_events(-start)
        return self._materialize()[index]

    def _materialize(self) -> list[Event]:
        provider = self._transcript._history_provider
        if provider is None:
            return list(self._transcript._events)
        return list(provider.events())


class TranscriptHistory:
    """Bounded-memory access to a transcript's logical event history.

    When a transcript is running in bounded mode, older events may be evicted
    from memory and served lazily from a history provider (e.g. an on-disk
    checkpoint store). This class provides explicit, memory-aware access to the
    event history so that hot paths can avoid materializing the full history.

    Access an instance via the `Transcript.history` property. For most use cases
    the `Transcript.events` compatibility view is sufficient; prefer this class
    when you need to reason about what is resident in memory or want to read only
    a recent slice of events without materializing the entire history.
    """

    def __init__(self, transcript: "Transcript") -> None:
        self._transcript = transcript

    @property
    def event_count(self) -> int:
        """Total number of events in the logical history (resident or evicted)."""
        return self._transcript._event_count

    @property
    def resident_events(self) -> Sequence[Event]:
        """Events currently retained in memory.

        In bounded mode this may be only the most recent tail of the logical
        history rather than the full history.
        """
        return self._transcript._events

    @property
    def resident_events_truncated(self) -> bool:
        """Whether resident events are a truncated view of the full history.

        `True` when older events have been evicted from memory, meaning
        `resident_events` does not contain the complete event history.
        """
        return self._transcript._events_truncated

    @property
    def full_history_available(self) -> bool:
        """Whether the complete event history can be retrieved.

        `True` when events have not been truncated, or when a history provider
        is available to materialize evicted events.
        """
        transcript = self._transcript
        return (
            not transcript._events_truncated or transcript._history_provider is not None
        )

    @property
    def provider(self) -> TranscriptHistoryProvider | None:
        """History provider backing evicted events, if any.

        `None` when the transcript keeps all events resident in memory.
        """
        return self._transcript._history_provider

    @property
    def last_event(self) -> Event | None:
        """Most recent event, or `None` if the transcript has no events."""
        events = self._transcript._events
        return events[-1] if events else None

    def recent_events(self, n: int | None = None) -> Sequence[Event]:
        """Return the most recent events in the transcript.

        Reads from resident memory when possible, falling back to the history
        provider only when the requested events have been evicted. This avoids
        materializing the full history when only a recent slice is needed.

        Args:
            n: Number of recent events to return. If `None`, returns the full
                logical history (which may materialize evicted events from the
                provider).

        Returns:
            The most recent `n` events (or all events when `n` is `None`), in
            insertion order.

        Raises:
            TranscriptHistoryUnavailableError: If `n` is `None`, events
                have been truncated, and no history provider is available to
                materialize the full history.
        """
        transcript = self._transcript
        if n is not None and n <= 0:
            return []
        if transcript._history_provider is None:
            if n is None and transcript._events_truncated:
                raise TranscriptHistoryUnavailableError(
                    "Full transcript history is not available from this Transcript"
                )
            return transcript._events if n is None else transcript._events[-n:]
        if n is not None:
            window = transcript._trailing_window(n)
            if window is not None:
                return window
        return transcript._history_provider.recent_events(n)

    def events_from(self, start: int, limit: int | None = None) -> Sequence[Event]:
        """Return events from logical index ``start`` onward.

        Serves from resident memory when ``start`` falls inside the resident
        window, falling back to the history provider to materialize evicted
        events. Prefer this over slicing ``resident_events`` when the caller's
        position is a *logical* history index (eg. a resume cursor) that may
        point below the resident window.

        Args:
            start: Logical index (0-based) of the first event to return.
                Negative values are treated as 0.
            limit: Maximum number of events to return. ``None`` returns
                everything through the end of the history.

        Returns:
            Events from ``start`` (inclusive), in insertion order. Empty when
            ``start`` is at or past the end of the history.

        Raises:
            TranscriptHistoryUnavailableError: If events have been
                truncated, the requested range extends beyond the trailing
                resident window, and no history provider is available to
                materialize the evicted events.
        """
        transcript = self._transcript
        start = max(0, start)
        count = transcript._event_count
        if start >= count:
            return []
        if not transcript._events_truncated:
            # nothing evicted: resident events ARE the logical history. Slice
            # page-bounded in one step — copying the whole tail and then
            # trimming it would be O(remaining history) per page on large
            # transcripts.
            end = count if limit is None else start + limit
            return transcript._events[start:end]
        # Once events have been evicted, resident events are NOT a contiguous
        # suffix of the logical history (pinned/pending events survive at
        # their insertion positions), so a logical offset can't be mapped
        # into ``_events`` by suffix arithmetic — only the trailing window is
        # a memory read (see `Transcript._trailing_window` for the
        # invariant). Anything earlier must come from the provider.
        window = transcript._trailing_window(count - start, limit)
        if window is not None:
            return window
        if transcript._history_provider is None:
            raise TranscriptHistoryUnavailableError(
                "Full transcript history is not available from this Transcript"
            )
        return transcript._history_provider.events_from(start, limit)

    def events_since_last(self, event_type: type[Event]) -> list[Event]:
        """Return events from the last occurrence of a given event type onward.

        Finds the most recent event of `event_type` and returns it along with
        every event that followed it. If no event of that type exists, returns
        the full event history.

        Args:
            event_type: Event type to search for (e.g. `ModelEvent`).

        Returns:
            Events from the last matching event (inclusive) to the end of the
            transcript, or all events if no match is found.

        Raises:
            TranscriptHistoryUnavailableError: If events have been
                truncated and no history provider is available to materialize
                the full history.
        """
        transcript = self._transcript
        if transcript._events_truncated:
            if transcript._history_provider is not None:
                return transcript._history_provider.events_since_last(event_type)
            raise TranscriptHistoryUnavailableError(
                "Full transcript history is not available from this Transcript"
            )
        events = list(transcript._events)
        index = find_last_match(events, lambda event: isinstance(event, event_type))
        if index is not None:
            return events[index:]
        return events


class Transcript:
    """Transcript of events."""

    _event_logger: _TranscriptSubscription | None
    _event_loggers: list[_TranscriptSubscription]
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
        self._next_event_logger_id = 0
        self._log_model_api = log_model_api
        self._context = WalkContext(message_cache={}, only_core=False)
        self._call_walk_slots: list[_CallWalkSlot] = []
        self._events: list[Event] = self._normalize_seeded_events(events or [])
        self._history_provider = history_provider
        self._events_view = _TranscriptEventsView(self)
        self._history = TranscriptHistory(self)
        self._attachments: dict[str, str] = {}
        self._attachment_refcount: dict[str, int] = {}
        self._event_attachment_refs: dict[str, set[str]] = {}
        # Per-message attachment-ref memo (bounded mode). Buckets are lists
        # because one msg.id can hold content variants (raw agent-state vs
        # condensed restored-event message after a resume). Lifetime rides the
        # same event-diff/eviction machinery as _event_attachment_refs via
        # _event_message_ids/_message_id_refcount, so departed messages age
        # out with their referencing events instead of pinning evicted memory.
        self._message_refs_cache: dict[
            str, list[tuple[ChatMessageBase, frozenset[str]]]
        ] = {}
        self._event_message_ids: dict[str, set[str]] = {}
        self._message_id_refcount: dict[str, int] = {}
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
        self._evictable_event_ids: deque[str] = deque(
            event_key
            for event in self._events
            if self._bounded
            and (event_key := self._event_key(event))
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
        `history.resident_events`, `history.event_count`, `history.last_event`, or
        `history.recent_events()`.
        """
        if self._history_provider is None or not self._events_truncated:
            return self._events
        return self._events_view

    @property
    def history(self) -> TranscriptHistory:
        """Explicit bounded-memory event history access."""
        return self._history

    @property
    def pending_events(self) -> Sequence[Event]:
        """Currently-pending events in insertion order."""
        return list(self._pending_events.values())

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
        track_pending = event.uuid is not None
        event_key = self._ensure_event_key(event)
        # Duplicate detection covers RESIDENT events only — tracking every
        # historical uuid would defeat bounded memory, so re-appending a uuid
        # whose original was evicted is accepted (incrementing _event_count)
        # even though the buffer database collapses both rows to one logical
        # event. That puts logical offsets out of sync with buffer rows, which the
        # control channel's cursor paging assumes aligned; no production path
        # re-appends an evicted uuid (event *updates* go through
        # _event_updated, which doesn't increment the count), so this is a
        # documented limitation rather than a guarded one.
        if event_key in self._resident_event_ids:
            raise ValueError(f"Duplicate event uuid: {event_key}")
        self._process_event(event)
        self._events.append(event)
        self._resident_event_ids.add(event_key)
        self._set_attachment_refs(event)
        self._event_count += 1
        self._update_pin_state(event)
        if track_pending:
            self._update_pending(event)
        self._update_evictable_state(event)
        self._evict_events()

    def _extend_restored_events(
        self,
        events: Sequence[Event],
        attachments: Mapping[str, str],
        *,
        notify_subscribers: bool = False,
    ) -> None:
        events = self._normalize_seeded_events(events)
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
            if notify_subscribers:
                self._notify_subscribers(event)
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
        if event.uuid is None:
            return
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

        self._notify_subscribers(event)

        # Condense model event calls after notifying subscribers so raw
        # transcript consumers can observe the original inline payload.
        if (
            isinstance(event, ModelEvent)
            and retain_attachments
            and event.call is not None
        ):
            event.call = self._condense_model_call(event.call)

    def _condense_model_call(self, call: ModelCall) -> ModelCall:
        """Condense a model call's payload into attachment references.

        Prefix-cached equivalent of ``walk_model_call``: consecutive kept
        calls share their conversation prefix, so only the divergent tail
        (plus non-message request fields and the response, which change per
        notification) is walked and hashed. Reused prefix messages have
        their attachment content re-asserted — bounded-mode refcounting may
        have pruned it while the prefix text lives on in the conversation.
        """
        msg_key = next((k for k in _CALL_MESSAGE_KEYS if k in call.request), None)
        msgs = call.request.get(msg_key) if msg_key is not None else None
        if msg_key is None or not isinstance(msgs, list) or not msgs:
            walked_call = walk_model_call(
                call, events_attachment_fn(self.attachments), self._context
            )
            assert walked_call is not None, (
                "walk_model_call(call) is None for non-None call"
            )
            return walked_call

        best_slot: _CallWalkSlot | None = None
        best_len = 0
        for slot in self._call_walk_slots:
            if slot.key != msg_key:
                continue
            n = 0
            for msg, prev in zip(msgs, slot.pre_walk):
                if not _strict_eq(msg, prev):
                    break
                n += 1
            if n > best_len:
                best_len = n
                best_slot = slot

        walked_msgs: list[JsonValue] = []
        slot_pre_walk: list[JsonValue] = []
        slot_walked: list[JsonValue] = []
        slot_attachments: list[list[tuple[str, str]]] = []
        if best_slot is not None:
            for index in range(best_len):
                for attachment_hash, content in best_slot.attachments[index]:
                    self.attachments[attachment_hash] = content
                walked_msgs.append(copy.deepcopy(best_slot.walked[index]))
            slot_pre_walk.extend(best_slot.pre_walk[:best_len])
            slot_walked.extend(best_slot.walked[:best_len])
            slot_attachments.extend(best_slot.attachments[:best_len])

        event_fn = events_attachment_fn(self.attachments)
        for msg in msgs[best_len:]:
            created: list[tuple[str, str]] = []
            walked = walk_json_value(
                msg, _recording_attachment_fn(event_fn, created), self._context
            )
            walked_msgs.append(walked)
            slot_pre_walk.append(copy.deepcopy(msg))
            slot_walked.append(copy.deepcopy(walked))
            slot_attachments.append(created)

        rest = {k: v for k, v in call.request.items() if k != msg_key}
        new_request: dict[str, JsonValue] = dict(
            walk_json_dict(rest, event_fn, self._context)
        )
        new_request[msg_key] = walked_msgs

        new_slot = _CallWalkSlot(
            key=msg_key,
            pre_walk=slot_pre_walk,
            walked=slot_walked,
            attachments=slot_attachments,
        )
        # Replace only on full consumption (the request extends that lineage).
        # A partial match is a sibling lineage forked from a shared prefix
        # (fork()/collect() streams share pre-fork history); replacing would
        # merge the two lineages, and they would alternately destroy each
        # other's cached tails, re-walking the divergent tail every call.
        if best_slot is not None and best_len == len(best_slot.pre_walk):
            self._call_walk_slots.remove(best_slot)
        self._call_walk_slots.append(new_slot)
        if len(self._call_walk_slots) > CALL_WALK_CACHE_SLOTS:
            self._call_walk_slots.pop(0)

        return call.model_copy(
            update={
                "request": new_request,
                "response": walk_json_dict(call.response, event_fn, self._context)
                if call.response
                else None,
            }
        )

    def _notify_subscribers(self, event: Event) -> None:
        for event_logger in list(self._event_loggers):
            subscriber_id = event_logger.id
            if subscriber_id in self._notifying_subscribers:
                continue
            self._notifying_subscribers.add(subscriber_id)
            try:
                try:
                    event_logger.callback(event)
                except Exception:
                    # Tag this record so the eval LogHandler does NOT re-inject
                    # it as a LoggerEvent — that would re-enter this loop and
                    # fan out combinatorially across other failing subscribers.
                    logger.warning(
                        "Transcript subscriber failed",
                        exc_info=True,
                        extra={SKIP_TRANSCRIPT_DISPATCH: True},
                    )
            finally:
                self._notifying_subscribers.remove(subscriber_id)

    def _set_attachment_refs(self, event: Event) -> None:
        if not self._bounded:
            return

        event_key = self._event_key(event)
        previous_refs = self._event_attachment_refs.get(event_key, set())
        event_refs = self._attachment_refs(event)
        current_refs = event_refs.refs
        for ref in previous_refs - current_refs:
            self._decrement_attachment_ref(ref)
        for ref in current_refs - previous_refs:
            self._attachment_refcount[ref] = self._attachment_refcount.get(ref, 0) + 1
        if current_refs:
            self._event_attachment_refs[event_key] = current_refs
        else:
            self._event_attachment_refs.pop(event_key, None)

        previous_ids = self._event_message_ids.get(event_key, set())
        current_ids = event_refs.message_ids
        for msg_id in previous_ids - current_ids:
            self._decrement_message_id_ref(msg_id)
        for msg_id in current_ids - previous_ids:
            self._message_id_refcount[msg_id] = (
                self._message_id_refcount.get(msg_id, 0) + 1
            )
        if current_ids:
            self._event_message_ids[event_key] = current_ids
        else:
            self._event_message_ids.pop(event_key, None)

    def _attachment_refs(self, event: Event) -> _EventRefs:
        message_ids: set[str] = set()

        def message_refs(msg: ChatMessageBase) -> frozenset[str] | None:
            # In-place mutation of a message's content without an id refresh
            # returns stale refs (identity/equality hit on the pre-mutation
            # entry) — the same accepted convention as WalkContext.message_cache
            # and MessagePoolIndex; first-party mutators mint new ids.
            msg_id = msg.id
            if msg_id is None:
                return None
            message_ids.add(msg_id)
            bucket = self._message_refs_cache.get(msg_id)
            if bucket is not None:
                for cached_msg, cached_refs in bucket:
                    if cached_msg is msg:
                        return cached_refs
                # identity miss: an ==-equal clone reuses the entry WITHOUT
                # being inserted (per-event model_copy clones would otherwise
                # grow the bucket unboundedly). == is cheap here: clones share
                # field objects, so comparisons short-circuit on identity.
                for cached_msg, cached_refs in bucket:
                    if cached_msg == msg:
                        return cached_refs
            refs = frozenset(attachment_refs_from_object(msg))
            if bucket is not None:
                if len(bucket) >= _MESSAGE_REFS_BUCKET_LIMIT:
                    del bucket[0]
                bucket.append((msg, refs))
            else:
                self._message_refs_cache[msg_id] = [(msg, refs)]
            return refs

        refs = attachment_refs_from_object(event, message_refs=message_refs)
        return _EventRefs(refs=refs, message_ids=message_ids)

    def _decrement_attachment_ref(self, ref: str) -> None:
        count = self._attachment_refcount.get(ref, 0) - 1
        if count > 0:
            self._attachment_refcount[ref] = count
        else:
            self._attachment_refcount.pop(ref, None)
            self._attachments.pop(ref, None)

    def _decrement_message_id_ref(self, msg_id: str) -> None:
        count = self._message_id_refcount.get(msg_id, 0) - 1
        if count > 0:
            self._message_id_refcount[msg_id] = count
        else:
            self._message_id_refcount.pop(msg_id, None)
            self._message_refs_cache.pop(msg_id, None)

    def _prune_unreferenced_attachments(self) -> None:
        if not self._bounded:
            return

        for ref in list(self._attachments):
            if ref not in self._attachment_refcount:
                self._attachments.pop(ref, None)

    def _trailing_window(self, n: int, limit: int | None = None) -> list[Event] | None:
        """The newest ``n`` logical events, served from resident memory.

        The eviction invariant this relies on — maintained by
        :meth:`_evict_events`, and the single place it should be reasoned
        about: eviction removes only the *oldest evictable* events, while
        pinned and pending events survive at their insertion positions. Older
        positions in ``_events`` may therefore be gapped relative to the
        logical history, but the trailing ``min(_resident_tail,
        len(_events))`` elements are always exactly the newest logical
        events, in order.

        Returns the window (optionally capped at ``limit`` events from its
        start) when ``n`` lies within that guarantee, else ``None`` — the
        caller must then materialize from the history provider (or fail).
        """
        if n > min(self._resident_tail, len(self._events)):
            return None
        first = len(self._events) - n
        end = len(self._events) if limit is None else first + limit
        return self._events[first:end]

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
            self._prune_model_call_counts()
            self._prune_attachment_refs(resident_event_keys)

    def _prune_model_call_counts(self) -> None:
        self._model_call_counts = {}
        for event in self._events:
            if not isinstance(event, ModelEvent):
                continue
            event_key = self._event_key(event)
            if event_key not in self._kept_event_ids:
                continue
            self._model_call_counts[event.model] = (
                self._model_call_counts.get(event.model, 0) + 1
            )

    def _prune_attachment_refs(self, resident_event_keys: set[str]) -> None:
        for event_key in list(self._event_attachment_refs):
            if event_key in resident_event_keys:
                continue
            for ref in self._event_attachment_refs.pop(event_key):
                self._decrement_attachment_ref(ref)
        for event_key in list(self._event_message_ids):
            if event_key in resident_event_keys:
                continue
            for msg_id in self._event_message_ids.pop(event_key):
                self._decrement_message_id_ref(msg_id)

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
        if not self._bounded:
            return
        event_key = self._event_key(event)
        if not self._is_evictable_event_key(event_key):
            return
        if event_key in self._evictable_event_ids:
            return

        evictable_index = 0
        for resident_event in self._events:
            if resident_event is event:
                self._evictable_event_ids.insert(evictable_index, event_key)
                return
            resident_event_key = self._event_key(resident_event)
            if self._is_evictable_event_key(resident_event_key):
                evictable_index += 1
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
    def _normalize_seeded_events(events: Sequence[Event]) -> list[Event]:
        """Assign UUIDs to seeded events without mutating caller-owned objects."""
        copied_events: list[Event] = []
        for event in events:
            if event.uuid is None:
                event = event.model_copy()
                event.uuid = uuid()
            copied_events.append(event)
        return copied_events

    def _subscribe(self, event_logger: Callable[[Event], None]) -> Callable[[], None]:
        subscription = self._create_subscription(event_logger)
        self._event_loggers.append(subscription)
        unsubscribed = False

        def unsubscribe() -> None:
            nonlocal unsubscribed
            if not unsubscribed:
                unsubscribed = True
                self._event_loggers.remove(subscription)

        return unsubscribe

    def _create_subscription(
        self, callback: Callable[[Event], None]
    ) -> _TranscriptSubscription:
        self._next_event_logger_id += 1
        return _TranscriptSubscription(id=self._next_event_logger_id, callback=callback)


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

    Args:
        source: What caused the interrupt — an ACP client cancel,
            a sample limit, or system shutdown.
        interrupted: What was running at the moment of the interrupt.
        interrupted_tool_call_id: ``ToolEvent.id`` of the in-flight
            tool call, if any.
        interrupted_model_event_id: ``ModelEvent.uuid`` of the
            in-flight model call, if any.
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
