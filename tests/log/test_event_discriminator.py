import re
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import TypeAdapter, ValidationError

import inspect_ai
from inspect_ai.event._event import DiscriminatedEvent, Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sentinel import SentinelAction, SentinelEvent


def test_event_public_alias_stays_introspectable() -> None:
    # The plain `Event` alias must remain a bare Union so `get_args()` and other
    # type introspection keep working. Wrapping the *public* alias in a
    # discriminator is what forced the revert of #2714, so the discriminated
    # variant is a separate alias and `Event` itself is left untouched.
    members = get_args(Event)
    assert ModelEvent in members
    assert InfoEvent in members
    assert len(members) == 25


def test_discriminated_event_validates_by_tag() -> None:
    adapter = TypeAdapter(list[DiscriminatedEvent])

    dumped = [
        InfoEvent(data="one").model_dump(),
        InfoEvent(data="two").model_dump(),
    ]
    events = adapter.validate_python(dumped)

    # `isinstance` both asserts the discriminator routed to InfoEvent and
    # narrows the union so mypy accepts the `.data` access below.
    assert all(isinstance(event, InfoEvent) for event in events)
    assert [event.data for event in events if isinstance(event, InfoEvent)] == [
        "one",
        "two",
    ]
    # The discriminator only changes how validation routes; serialization is
    # unchanged (every member already emits its `event` tag).
    assert [event.model_dump() for event in events] == dumped


def test_discriminated_event_rejects_unknown_tag() -> None:
    adapter = TypeAdapter(list[DiscriminatedEvent])
    with pytest.raises(ValidationError):
        adapter.validate_python([{"event": "not_a_real_event"}])


def test_no_bare_event_list_typeadapter_in_src() -> None:
    # Tripwire for the Event vs DiscriminatedEvent convention: any site that
    # validates events from JSON/dicts must route through the discriminated
    # alias (directly or via validate_events), never a bare
    # `TypeAdapter(list[Event])`, or the #2714 slow-path regression returns.
    # Full enforcement isn't possible (the invariant is about call paths, not
    # annotations), but a bare adapter is the most likely regression to guard.
    src_root = Path(inspect_ai.__file__).parent
    pattern = re.compile(r"TypeAdapter\(\s*list\[Event\]\s*\)")
    allowlist: set[str] = set()
    offenders = sorted(
        rel
        for path in src_root.rglob("*.py")
        if (rel := str(path.relative_to(src_root))) not in allowlist
        and pattern.search(path.read_text(encoding="utf-8"))
    )
    assert not offenders, (
        "Validate events through DiscriminatedEvent (see event/_validate.py) "
        f"rather than a bare TypeAdapter(list[Event]): {offenders}"
    )


def _sentinel_event(**kwargs: Any) -> SentinelEvent:
    fields: dict[str, Any] = dict(
        name="threshold",
        path="",
        function="threshold",
        step_id="call_1",
        conversation="conv_1",
        stage="tool_call",
        kind="decision",
        decision="reject",
        outcome="reject",
        explanation="too suspicious",
    )
    fields.update(kwargs)
    return SentinelEvent.model_validate(fields)


@pytest.mark.parametrize(
    "suspicion", [None, 0.25, {"exfiltration": 0.9, "sabotage": 0.1}]
)
def test_sentinel_event_round_trips(suspicion: float | dict[str, float] | None) -> None:
    event = _sentinel_event(suspicion=suspicion, audit=True, metadata={"k": 1})
    adapter: TypeAdapter[Event] = TypeAdapter(DiscriminatedEvent)
    restored = adapter.validate_json(adapter.dump_json(event))
    assert isinstance(restored, SentinelEvent)
    assert restored == event


def test_sentinel_event_rejects_invalid_suspicion() -> None:
    for suspicion in [float("nan"), float("inf"), {}]:
        with pytest.raises(ValidationError):
            _sentinel_event(suspicion=suspicion)


def test_sentinel_event_renders_in_tui() -> None:
    from inspect_ai._display.textual.widgets.transcript import render_event

    displays = render_event(_sentinel_event(suspicion=0.5))
    assert displays is not None and len(displays) == 1
    assert displays[0].title == "sentinel: tool_call"


def test_sentinel_action_matches_inspect_sentinel() -> None:
    # SentinelEvent is always in the Event union, so it declares its own
    # Action rather than importing inspect_sentinel.
    report = pytest.importorskip("inspect_sentinel._report")
    assert get_args(SentinelAction) == get_args(report.Action)
