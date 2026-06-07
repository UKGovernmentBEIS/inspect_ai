"""ACP replay-on-attach snapshot reads the full since-attach history.

The replay snapshot slices the transcript's logical event history from the
router's attach index forward, served through the bounded-history provider
when older events have been evicted from resident memory. It must NOT be a
resident-only window:

* the sub-agent depth filter walks the AGENT_SPAN begin/end markers from
  attach forward, so eliding evicted SpanBegin events would surface
  in-progress sub-agent events as top-level conversation; and
* the per-stream ``REPLAY_MAX_EVENTS`` cap means "last N semantic events",
  which only holds when the filter runs over the full since-attach history.

Reading through the provider is content-safe because the provider resolves
``attachment://`` references back to their underlying values, matching the
un-condensed resident events.
"""

from typing import Sequence

from inspect_ai.agent._acp.session_router import (
    REPLAY_MAX_EVENTS,
    _filter_subagent_events,
)
from inspect_ai.agent._acp.transport_live import LiveAcpTransport
from inspect_ai.event import SpanBeginEvent
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.log._transcript import Transcript
from inspect_ai.util._span import AGENT_SPAN_TYPE


class _ListBackedProvider:
    """In-memory history provider backed by a growing event list.

    Mirrors what the buffer-DB provider hands the snapshot on a bounded
    transcript: the full logical history (attachment-resolved), including
    events the transcript has evicted from resident memory. Subscribe
    ``record`` to a transcript so the provider observes every event before
    eviction.
    """

    def __init__(self) -> None:
        self._events: list[Event] = []

    def record(self, event: Event) -> None:
        self._events.append(event)

    @property
    def event_count(self) -> int:
        return len(self._events)

    def iter_events(self):
        return iter(self._events)

    def events(self) -> Sequence[Event]:
        return list(self._events)

    def recent_events(self, n: int | None = None) -> Sequence[Event]:
        if n is None:
            return list(self._events)
        if n <= 0:
            return []
        return self._events[-n:]

    def events_from(self, start: int) -> Sequence[Event]:
        if start <= 0:
            return list(self._events)
        return self._events[start:]

    def events_since_last(self, event_type: type[Event]) -> list[Event]:
        suffix: list[Event] = []
        for event in self._events:
            if isinstance(event, event_type):
                suffix = [event]
            else:
                suffix.append(event)
        return suffix

    def contains_event(self, event_id: str) -> bool:
        return any(e.uuid == event_id for e in self._events)

    def attachments(self):
        return {}

    def attachment(self, hash: str) -> str | None:
        return None

    def export_transcript_events(self, transcript_store) -> int:
        return 0


def _capture(transcript: Transcript, attach_index: int) -> LiveAcpTransport:
    acp = LiveAcpTransport()
    acp._transcript_capture.captured = transcript
    acp._transcript_capture.attach_index = attach_index
    return acp


def _bounded_transcript(resident_tail: int) -> tuple[Transcript, _ListBackedProvider]:
    provider = _ListBackedProvider()
    tr = Transcript(
        bounded=True, resident_tail=resident_tail, history_provider=provider
    )
    tr._subscribe(provider.record)
    return tr, provider


def test_snapshot_applies_attach_index() -> None:
    tr = Transcript()
    for i in range(5):
        tr._event(InfoEvent(data=i))

    snap = _capture(tr, attach_index=2).transcript_events_snapshot()

    assert [e.data for e in snap] == [2, 3, 4]


def test_snapshot_reads_full_history_from_provider_after_eviction() -> None:
    # Bounded transcript with only the last 2 events resident; older events
    # are evicted from memory but remain available from the provider.
    tr, _ = _bounded_transcript(resident_tail=2)
    for i in range(5):
        tr._event(InfoEvent(data=i))
    assert tr.history.resident_events_truncated is True

    snap = _capture(tr, attach_index=0).transcript_events_snapshot()

    # Full since-attach history, not just the resident tail.
    assert [e.data for e in snap] == [0, 1, 2, 3, 4]


def test_snapshot_preserves_subagent_span_context_after_eviction() -> None:
    """Evicted AGENT_SPAN markers still reach the sub-agent depth filter.

    Regression: when the snapshot was a resident-only window, eviction of
    the outer/sub-agent SpanBegin events made the depth filter classify
    in-progress sub-agent events as top-level conversation (and misfire the
    first-is-outer rule onto a nested span). Reading from attach_index via
    the provider gives replay the same event stream the live router saw.
    """
    # resident_tail small enough that the two SpanBegins (logical indices
    # 0 and 2) get evicted, leaving only sub-agent events resident.
    tr, _ = _bounded_transcript(resident_tail=2)
    tr._event(SpanBeginEvent(id="outer", type=AGENT_SPAN_TYPE, name="outer"))
    tr._event(InfoEvent(data="top-level"))
    tr._event(SpanBeginEvent(id="sub", type=AGENT_SPAN_TYPE, name="sub"))
    tr._event(InfoEvent(data="inside-sub-1"))
    tr._event(InfoEvent(data="inside-sub-2"))

    # The two SpanBegins are no longer resident...
    resident = list(tr.history.resident_events)
    assert not any(isinstance(e, SpanBeginEvent) for e in resident)

    # ...but the snapshot recovers them from attach_index forward, so the
    # depth filter keeps only the genuinely top-level event.
    snap = list(_capture(tr, attach_index=0).transcript_events_snapshot())
    filtered = [
        e.data for e in _filter_subagent_events(snap) if isinstance(e, InfoEvent)
    ]
    assert filtered == ["top-level"]


def test_snapshot_resident_only_would_misclassify_subagent_events() -> None:
    """Pin the bug the fix prevents: filtering a resident-only window wrong.

    If replay fed the depth filter only the resident tail (which has lost
    the SpanBegin markers), the sub-agent events leak through as top-level.
    This asserts that failure mode against the resident window directly, so
    a regression back to resident-only snapshotting is caught here too.
    """
    tr, _ = _bounded_transcript(resident_tail=2)
    tr._event(SpanBeginEvent(id="outer", type=AGENT_SPAN_TYPE, name="outer"))
    tr._event(InfoEvent(data="top-level"))
    tr._event(SpanBeginEvent(id="sub", type=AGENT_SPAN_TYPE, name="sub"))
    tr._event(InfoEvent(data="inside-sub-1"))
    tr._event(InfoEvent(data="inside-sub-2"))

    resident = list(tr.history.resident_events)
    leaked = [
        e.data for e in _filter_subagent_events(resident) if isinstance(e, InfoEvent)
    ]
    # Sub-agent events wrongly surface when the SpanBegins are missing.
    assert leaked == ["inside-sub-1", "inside-sub-2"]


def test_replay_max_events_is_a_wire_payload_cap() -> None:
    # Decoupled from the resident window: purely bounds the replay payload.
    assert REPLAY_MAX_EVENTS == 100
