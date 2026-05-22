"""Tests for the additive `Transcript._add_subscriber` API.

Independent of ACP: ``_add_subscriber`` is general-purpose multi-cast
plumbing used by the Phase 6 router and (potentially) future hooks /
tooling consumers.
"""

from inspect_ai.event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.log._transcript import Transcript


def _info(data: str) -> InfoEvent:
    return InfoEvent(data=data)


def _info_data(events: list[Event]) -> list[str]:
    """Project a list of (Info)Events to their string `data` for assertion."""
    out: list[str] = []
    for e in events:
        assert isinstance(e, InfoEvent)
        assert isinstance(e.data, str)
        out.append(e.data)
    return out


def test_add_subscriber_receives_events_in_order() -> None:
    """Subscriber receives events in the order they were appended."""
    tr = Transcript()
    received: list[Event] = []
    tr._add_subscriber(received.append)

    tr._event(_info("one"))
    tr._event(_info("two"))
    tr._event(_info("three"))

    assert _info_data(received) == ["one", "two", "three"]


def test_add_subscriber_multi_cast_to_two_subscribers() -> None:
    """Two subscribers added in turn both receive every event."""
    tr = Transcript()
    a: list[Event] = []
    b: list[Event] = []
    tr._add_subscriber(a.append)
    tr._add_subscriber(b.append)

    tr._event(_info("x"))
    tr._event(_info("y"))

    assert _info_data(a) == ["x", "y"]
    assert _info_data(b) == ["x", "y"]


def test_add_subscriber_coexists_with_legacy_subscribe() -> None:
    """The legacy single-slot ``_subscribe`` and ``_add_subscriber`` both fire."""
    tr = Transcript()
    legacy: list[Event] = []
    additive: list[Event] = []
    tr._subscribe(legacy.append)
    tr._add_subscriber(additive.append)

    tr._event(_info("hello"))

    assert _info_data(legacy) == ["hello"]
    assert _info_data(additive) == ["hello"]


def test_unsubscribe_handle_stops_delivery() -> None:
    """The returned unsubscribe callable removes the subscriber."""
    tr = Transcript()
    received: list[Event] = []
    unsubscribe = tr._add_subscriber(received.append)

    tr._event(_info("before"))
    unsubscribe()
    tr._event(_info("after"))

    assert _info_data(received) == ["before"]

    # Double-unsubscribe must be a no-op.
    unsubscribe()


def test_subscriber_exception_does_not_block_other_subscribers() -> None:
    """A raising subscriber is logged but does not block siblings or the loop."""
    tr = Transcript()
    received: list[Event] = []

    def raises(_e: Event) -> None:
        raise RuntimeError("boom")

    tr._add_subscriber(raises)
    tr._add_subscriber(received.append)

    # _event itself must not raise even though `raises` does.
    tr._event(_info("survivor"))

    assert _info_data(received) == ["survivor"]
