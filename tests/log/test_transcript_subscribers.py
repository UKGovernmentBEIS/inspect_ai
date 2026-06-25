"""Tests for the private `Transcript._subscribe` multi-cast API."""

import logging
from unittest.mock import patch

from inspect_ai._util.constants import SKIP_TRANSCRIPT_DISPATCH
from inspect_ai.event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._logger import LoggerEvent, LoggingMessage
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
    tr._subscribe(received.append)

    tr._event(_info("one"))
    tr._event(_info("two"))
    tr._event(_info("three"))

    assert _info_data(received) == ["one", "two", "three"]


def test_add_subscriber_multi_cast_to_two_subscribers() -> None:
    """Two subscribers added in turn both receive every event."""
    tr = Transcript()
    a: list[Event] = []
    b: list[Event] = []
    tr._subscribe(a.append)
    tr._subscribe(b.append)

    tr._event(_info("x"))
    tr._event(_info("y"))

    assert _info_data(a) == ["x", "y"]
    assert _info_data(b) == ["x", "y"]


def test_unsubscribe_handle_stops_delivery() -> None:
    """The returned unsubscribe callable removes the subscriber."""
    tr = Transcript()
    received: list[Event] = []
    unsubscribe = tr._subscribe(received.append)

    tr._event(_info("before"))
    unsubscribe()
    tr._event(_info("after"))

    assert _info_data(received) == ["before"]

    # Double-unsubscribe must be a no-op.
    unsubscribe()


def test_same_callback_subscribed_twice_fires_twice() -> None:
    tr = Transcript()
    received: list[Event] = []

    tr._subscribe(received.append)
    tr._subscribe(received.append)

    tr._event(_info("twice"))

    assert _info_data(received) == ["twice", "twice"]


def test_duplicate_subscription_unsubscribe_handles_are_independent() -> None:
    tr = Transcript()
    received: list[Event] = []

    first_unsubscribe = tr._subscribe(received.append)
    tr._subscribe(received.append)

    tr._event(_info("before"))
    first_unsubscribe()
    first_unsubscribe()
    tr._event(_info("after"))

    assert _info_data(received) == ["before", "before", "after"]


def test_subscriber_exception_does_not_block_other_subscribers() -> None:
    """A raising subscriber is logged but does not block siblings or the loop."""
    tr = Transcript()
    received: list[Event] = []

    def raises(_e: Event) -> None:
        raise RuntimeError("boom")

    tr._subscribe(raises)
    tr._subscribe(received.append)

    # _event itself must not raise even though `raises` does.
    with patch("inspect_ai.log._transcript.logger.warning") as warning:
        tr._event(_info("survivor"))

    assert _info_data(received) == ["survivor"]
    warning.assert_called_once_with(
        "Transcript subscriber failed",
        exc_info=True,
        extra={SKIP_TRANSCRIPT_DISPATCH: True},
    )


def test_subscriber_failure_warning_does_not_fan_out() -> None:
    """Subscriber-failure warnings must not re-enter the subscriber loop.

    Drives the *real* re-injection path used by the eval ``LogHandler``: a
    WARNING record is converted back into a transcript ``LoggerEvent``. A
    handler attached to the transcript logger mirrors that dispatch decision,
    honoring the ``SKIP_TRANSCRIPT_DISPATCH`` marker. With two always-raising
    subscribers, each must fire exactly once for the single real event —
    without the marker this fans out factorially (``T(2) = 4``).
    """
    tr = Transcript()
    calls = {"a": 0, "b": 0}

    def raises_a(_e: Event) -> None:
        calls["a"] += 1
        raise RuntimeError("boom-a")

    def raises_b(_e: Event) -> None:
        calls["b"] += 1
        raise RuntimeError("boom-b")

    class ReinjectHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            # mirror LogHandler.emit's transcript-dispatch decision
            if getattr(record, SKIP_TRANSCRIPT_DISPATCH, False):
                return
            tr._event(LoggerEvent(message=LoggingMessage._from_log_record(record)))

    handler = ReinjectHandler()
    transcript_logger = logging.getLogger("inspect_ai.log._transcript")
    transcript_logger.addHandler(handler)
    previous_level = transcript_logger.level
    transcript_logger.setLevel(logging.WARNING)
    try:
        tr._subscribe(raises_a)
        tr._subscribe(raises_b)
        tr._event(_info("outer"))
    finally:
        transcript_logger.removeHandler(handler)
        transcript_logger.setLevel(previous_level)

    assert calls == {"a": 1, "b": 1}


def test_reentrant_event_reaches_other_subscribers_once() -> None:
    tr = Transcript()
    first_seen: list[Event] = []
    second_seen: list[Event] = []

    def reentrant(event: Event) -> None:
        first_seen.append(event)
        if isinstance(event, InfoEvent) and event.data == "outer":
            tr._event(_info("inner"))

    tr._subscribe(reentrant)
    tr._subscribe(second_seen.append)

    tr._event(_info("outer"))

    assert _info_data(first_seen) == ["outer"]
    assert _info_data(second_seen) == ["inner", "outer"]


def test_reentrant_duplicate_callback_subscriptions_use_independent_guards() -> None:
    tr = Transcript()
    seen: list[str] = []

    def reentrant(event: Event) -> None:
        assert isinstance(event, InfoEvent)
        assert isinstance(event.data, str)
        seen.append(event.data)
        if event.data == "outer":
            tr._event(_info("inner"))

    tr._subscribe(reentrant)
    tr._subscribe(reentrant)

    tr._event(_info("outer"))

    assert seen == ["outer", "inner", "outer", "inner"]
