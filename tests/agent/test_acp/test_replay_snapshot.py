"""ACP replay snapshot reads the resident, un-condensed event window.

Part B / C of the attachment-resolution fix: the replay-on-attach snapshot
reads only the resident (in-memory) event window via the history accessor,
never the provider-backed ``events`` view. Resident events keep their message
content un-condensed, so replay forwards real content instead of
``attachment://`` references — and it stays off the buffer DB even on a
bounded, already-evicted transcript. ``REPLAY_MAX_EVENTS`` is aligned to the
resident window so capping never reaches past what is held in memory.
"""

from typing import Sequence

from inspect_ai.agent._acp.session_router import REPLAY_MAX_EVENTS
from inspect_ai.agent._acp.transport_live import LiveAcpTransport
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.log._transcript import DEFAULT_RESIDENT_TAIL, Transcript


class _RaisingReadProvider:
    """History provider that fails if any event-read method is touched.

    The snapshot must serve everything from the resident window, so reaching
    the provider at all is a bug.
    """

    @property
    def event_count(self) -> int:
        raise AssertionError("snapshot must not read provider.event_count")

    def iter_events(self):
        raise AssertionError("snapshot must not read provider.iter_events")

    def events(self) -> Sequence[Event]:
        raise AssertionError("snapshot must not read provider.events")

    def recent_events(self, n: int | None = None) -> Sequence[Event]:
        raise AssertionError("snapshot must not read provider.recent_events")

    def events_from(self, start: int) -> Sequence[Event]:
        raise AssertionError("snapshot must not read provider.events_from")

    def events_since_last(self, event_type: type[Event]) -> list[Event]:
        raise AssertionError("snapshot must not read provider.events_since_last")

    def contains_event(self, event_id: str) -> bool:
        raise AssertionError("snapshot must not read provider.contains_event")

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


def test_snapshot_uses_resident_window_not_provider() -> None:
    # Bounded transcript with only the last 2 events resident; older events
    # are evicted and would be served (condensed) by the provider.
    tr = Transcript(
        bounded=True, resident_tail=2, history_provider=_RaisingReadProvider()
    )
    for i in range(5):
        tr._event(InfoEvent(data=i))
    assert tr.history.resident_events_truncated is True

    snap = _capture(tr, attach_index=0).transcript_events_snapshot()

    # Resident window (last 2) — read without touching the raising provider.
    assert [e.data for e in snap] == [3, 4]


def test_snapshot_applies_attach_index_floor() -> None:
    tr = Transcript()
    for i in range(5):
        tr._event(InfoEvent(data=i))

    snap = _capture(tr, attach_index=2).transcript_events_snapshot()

    assert [e.data for e in snap] == [2, 3, 4]


def test_snapshot_attach_index_predating_eviction_returns_resident() -> None:
    # attach_index points at an event that has since been evicted; the floor
    # clamps into the resident window rather than going negative.
    tr = Transcript(
        bounded=True, resident_tail=2, history_provider=_RaisingReadProvider()
    )
    for i in range(5):
        tr._event(InfoEvent(data=i))

    # first resident event is logical index 3; attach_index 1 predates it.
    snap = _capture(tr, attach_index=1).transcript_events_snapshot()

    assert [e.data for e in snap] == [3, 4]


def test_replay_window_aligned_with_resident_tail() -> None:
    # Replay must never need to read past the resident window (which would
    # surface unresolved attachment refs from the provider).
    assert REPLAY_MAX_EVENTS <= DEFAULT_RESIDENT_TAIL
