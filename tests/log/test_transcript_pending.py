"""Unit tests for ``Transcript.pending_events``.

The sidecar is read by the live TUI toolbar (and, eventually, by the
DB-backed transcript) to query in-flight state in O(in-flight) without
scanning the full event list.
"""

from inspect_ai.event._info import InfoEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import Transcript


def _tool_event(
    *,
    id: str,
    uuid: str | None,
    pending: bool,
) -> ToolEvent:
    return ToolEvent(
        id=id,
        function="noop",
        arguments={},
        pending=pending,
        uuid=uuid,
    )


def test_pending_events_empty_initially() -> None:
    t = Transcript()
    assert list(t.pending_events) == []


def test_event_with_pending_true_lands_in_sidecar() -> None:
    t = Transcript()
    ev = _tool_event(id="tc-1", uuid="uuid-1", pending=True)
    t._event(ev)
    assert [e.uuid for e in t.pending_events] == ["uuid-1"]


def test_event_updated_to_terminal_removes_from_sidecar() -> None:
    t = Transcript()
    ev = _tool_event(id="tc-1", uuid="uuid-1", pending=True)
    t._event(ev)
    assert list(t.pending_events) == [ev]

    # Mirror call_tools.py's path: flip pending in-place, then notify.
    ev.pending = None
    t._event_updated(ev)
    assert list(t.pending_events) == []


def test_pending_events_preserve_insertion_order() -> None:
    """Insertion order = declared order — important for "earliest pending"."""
    t = Transcript()
    for uuid in ("uuid-a", "uuid-b", "uuid-c"):
        t._event(_tool_event(id=uuid, uuid=uuid, pending=True))
    assert [e.uuid for e in t.pending_events] == ["uuid-a", "uuid-b", "uuid-c"]


def test_out_of_order_completion_does_not_disturb_remaining_pending() -> None:
    """Completing a later sibling first leaves earlier siblings pending."""
    t = Transcript()
    a = _tool_event(id="a", uuid="uuid-a", pending=True)
    b = _tool_event(id="b", uuid="uuid-b", pending=True)
    t._event(a)
    t._event(b)

    # B finishes first.
    b.pending = None
    t._event_updated(b)
    assert [e.uuid for e in t.pending_events] == ["uuid-a"]

    # A finishes.
    a.pending = None
    t._event_updated(a)
    assert list(t.pending_events) == []


def test_non_pending_event_does_not_enter_sidecar() -> None:
    t = Transcript()
    ev = _tool_event(id="tc-1", uuid="uuid-1", pending=False)
    t._event(ev)
    assert list(t.pending_events) == []


def test_event_without_uuid_is_assigned_key() -> None:
    """UUID-less events are normalized before pending bookkeeping."""
    t = Transcript()
    ev = _tool_event(id="tc-1", uuid="uuid-1", pending=True)
    ev.uuid = None
    t._event(ev)
    assert ev.uuid is not None
    assert list(t.pending_events) == [ev]


def test_hydration_from_constructor_events_populates_sidecar() -> None:
    """A transcript reconstructed from a saved events list keeps pending state.

    Matters for resume / re-attach: when a checkpoint or DB-backed log
    rehydrates a transcript with in-flight events, consumers should see
    them as pending without re-running ``_event``.
    """
    pending = _tool_event(id="tc-pending", uuid="uuid-pending", pending=True)
    done = _tool_event(id="tc-done", uuid="uuid-done", pending=False)
    info = InfoEvent(source=None, data={"k": "v"})
    t = Transcript(events=[done, pending, info])
    assert [e.uuid for e in t.pending_events] == ["uuid-pending"]


def test_constructor_does_not_mutate_uuidless_seed_events() -> None:
    ev = _tool_event(id="tc-1", uuid="uuid-1", pending=True)
    ev.uuid = None

    t = Transcript(events=[ev])

    assert ev.uuid is None
    assert list(t.pending_events)[0] is not ev
    assert list(t.pending_events)[0].uuid is not None


def test_pending_and_non_pending_interleaved() -> None:
    """Non-pending events between pending ones don't disturb the sidecar."""
    t = Transcript()
    a = _tool_event(id="a", uuid="uuid-a", pending=True)
    info = InfoEvent(source=None, data={"k": "v"})  # not pending; not tracked
    b = _tool_event(id="b", uuid="uuid-b", pending=True)
    t._event(a)
    t._event(info)
    t._event(b)
    assert [e.uuid for e in t.pending_events] == ["uuid-a", "uuid-b"]
