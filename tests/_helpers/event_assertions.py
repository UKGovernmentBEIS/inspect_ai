"""Event-stream assertion helpers for ModelEvent retry-timing tests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, Protocol, cast

from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._transcript import Transcript

TerminalKind = Literal["success", "exhausted", "cache"]


class HasEvents(Protocol):
    events: Iterable[Event]


def model_events(source: object) -> list[ModelEvent]:
    """Extract ModelEvents from a Transcript, sample-like object, or list."""
    events: Iterable[Event]
    if isinstance(source, Transcript):
        events = source.events
    elif hasattr(source, "events"):
        events = cast(HasEvents, source).events
    elif isinstance(source, list):
        events = source
    else:
        raise TypeError(f"Cannot extract events from {type(source).__name__}")
    return [event for event in events if isinstance(event, ModelEvent)]


def assert_no_legacy_rewrite(events: list[ModelEvent]) -> None:
    """Assert timestamps do not invert within a post-fix call group."""
    by_call: dict[str | None, list[ModelEvent]] = {}
    for event in events:
        by_call.setdefault(event.call_id, []).append(event)
    for call_id, group in by_call.items():
        for prev, curr in zip(group, group[1:]):
            if curr.timestamp < prev.timestamp:
                raise AssertionError(
                    f"timestamp inversion in call_id={call_id!r}: "
                    f"attempt={curr.attempt} timestamp={curr.timestamp.isoformat()} "
                    f"is before previous attempt={prev.attempt} "
                    f"timestamp={prev.timestamp.isoformat()}"
                )


def assert_attempt_group(
    events: list[ModelEvent], *, retries: int, terminal_kind: TerminalKind
) -> None:
    """Assert events form one valid call_id group."""
    if not events:
        raise AssertionError("expected at least one event in attempt group")
    call_ids = {event.call_id for event in events}
    if len(call_ids) != 1 or None in call_ids:
        raise AssertionError(f"events do not share one call_id: {call_ids}")
    attempts = [event.attempt for event in events]
    expected = list(range(1, retries + 2))
    if attempts != expected:
        raise AssertionError(
            f"attempts not contiguous 1..{retries + 1}: got {attempts}"
        )
    assert_no_legacy_rewrite(events)
    assert_call_field_invariants(events[-1], kind=f"terminal-{terminal_kind}")
    for event in events[:-1]:
        assert_call_field_invariants(event, kind="non-terminal")


def assert_call_field_invariants(event: ModelEvent, *, kind: str) -> None:
    """Assert a ModelEvent has the expected call-level field shape."""
    call_fields = (
        event.call_started_at,
        event.call_completed_at,
        event.call_working_start,
        event.call_working_time,
        event.call_retries,
        event.http_retries,
    )
    if kind == "terminal-success":
        if any(field is None for field in call_fields):
            raise AssertionError(
                f"terminal-success missing call_* fields: {call_fields}"
            )
        if event.error is not None:
            raise AssertionError("terminal-success has error set")
        if event.cache == "read":
            raise AssertionError("terminal-success has cache='read'")
    elif kind == "terminal-exhausted":
        if any(field is None for field in call_fields):
            raise AssertionError(
                f"terminal-exhausted missing call_* fields: {call_fields}"
            )
        if event.error is None:
            raise AssertionError("terminal-exhausted has no error")
    elif kind == "terminal-cache":
        if any(field is None for field in call_fields):
            raise AssertionError(f"terminal-cache missing call_* fields: {call_fields}")
        if event.cache != "read":
            raise AssertionError(f"terminal-cache has cache={event.cache!r}")
    elif kind == "non-terminal":
        if any(field is not None for field in call_fields):
            raise AssertionError(f"non-terminal has call_* fields set: {call_fields}")
        if event.error is None:
            raise AssertionError("non-terminal has no error")
    else:
        raise ValueError(f"unknown kind: {kind!r}")
