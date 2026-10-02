import io
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import TypeAdapter, ValidationError

import inspect_ai
from inspect_ai.event._event import DiscriminatedEvent, Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sentinel import SentinelEvent
from inspect_ai.scorer import Reference
from inspect_ai.tool import ToolCall


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
        factory="threshold",
        path="",
        function="threshold",
        step_id="call_1",
        conversation="conv_1",
        stage="tool_call",
        kind="decision",
        status="reported",
        action="reject",
        explanation="too suspicious",
    )
    fields.update(kwargs)
    return SentinelEvent.model_validate(fields)


_MODIFIED = ToolCall(id="call_1", function="bash", arguments={"cmd": "ls"})

_REFERENCES = [
    Reference(type="message", id="msg_22", cite="[M22]"),
    Reference(type="event", id="evt_7"),
]


def _observation(**kwargs: Any) -> SentinelEvent:
    fields: dict[str, Any] = dict(kind="observation", action=None, suspicion=0.5)
    fields.update(kwargs)
    return _sentinel_event(**fields)


@pytest.mark.parametrize(
    "event",
    [
        _sentinel_event(),
        _sentinel_event(status="superseded", audit=True, metadata={"k": 1}),
        _sentinel_event(message="use X instead"),
        _sentinel_event(status="superseded", message="use X instead"),
        _observation(),
        _observation(suspicion={"exfiltration": 0.9, "sabotage": 0.1}),
        _sentinel_event(status="bypassed", function=None, action=None),
        _observation(status="cancelled", function=None, suspicion=None),
        _sentinel_event(action="modify", modified=_MODIFIED),
        _sentinel_event(status="superseded", action="modify", modified=_MODIFIED),
        _observation(references=_REFERENCES),
        _sentinel_event(references=_REFERENCES),
        _observation(status="error", suspicion=None, error="ValueError: no model"),
    ],
)
def test_sentinel_event_round_trips(event: SentinelEvent) -> None:
    adapter: TypeAdapter[Event] = TypeAdapter(DiscriminatedEvent)
    restored = adapter.validate_json(adapter.dump_json(event))
    assert isinstance(restored, SentinelEvent)
    assert restored == event


def test_sentinel_event_rejects_invalid_suspicion() -> None:
    for suspicion in [float("nan"), float("inf"), {}]:
        with pytest.raises(ValidationError):
            _observation(suspicion=suspicion)


@pytest.mark.parametrize("kind", ["observation", "decision"])
@pytest.mark.parametrize("status", ["cancelled", "bypassed"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("function", "f"),
        ("suspicion", 0.5),
        ("action", "continue"),
        ("references", [{"type": "message", "id": "msg_22"}]),
    ],
)
def test_sentinel_event_without_report_rejects_report_fields(
    kind: str, status: str, field: str, value: Any
) -> None:
    fields: dict[str, Any] = dict(kind=kind, status=status, function=None, action=None)
    _sentinel_event(**fields)
    fields[field] = value
    with pytest.raises(ValidationError, match=field):
        _sentinel_event(**fields)


@pytest.mark.parametrize(
    "overrides",
    [dict(suspicion=None), dict(action="continue"), dict(function=None)],
)
def test_sentinel_observation_requires_suspicion_only(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _observation(**overrides)


@pytest.mark.parametrize("status", ["reported", "superseded"])
@pytest.mark.parametrize(
    "overrides",
    [dict(action=None), dict(suspicion=0.5), dict(function=None)],
)
def test_sentinel_decision_requires_action_only(
    status: str, overrides: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        _sentinel_event(status=status, **overrides)


@pytest.mark.parametrize(
    "overrides,match",
    [
        (dict(error=None), "only on, an 'error'"),
        (dict(kind="decision"), "Only an 'observation'"),
        (dict(suspicion=0.5), "suspicion"),
        (dict(action="continue"), "action"),
        (dict(references=_REFERENCES), "references"),
        (dict(function=None), "requires function"),
    ],
)
def test_sentinel_error_records_only_the_error(
    overrides: dict[str, Any], match: str
) -> None:
    fields: dict[str, Any] = dict(status="error", suspicion=None, error="boom")
    _observation(**fields)
    fields.update(overrides)
    with pytest.raises(ValidationError, match=match):
        _observation(**fields)


@pytest.mark.parametrize("status", ["reported", "cancelled", "superseded"])
def test_sentinel_error_is_only_on_an_error_event(status: str) -> None:
    with pytest.raises(ValidationError, match="only on, an 'error'"):
        _sentinel_event(status=status, error="boom")


def test_sentinel_superseded_is_only_for_decisions() -> None:
    with pytest.raises(ValidationError, match="superseded"):
        _observation(status="superseded")


@pytest.mark.parametrize("status", ["reported", "superseded"])
def test_sentinel_modify_requires_modified(status: str) -> None:
    with pytest.raises(ValidationError, match="requires modified"):
        _sentinel_event(status=status, action="modify")


@pytest.mark.parametrize(
    "event",
    [
        dict(action="reject"),
        dict(status="superseded", action="continue"),
        dict(kind="observation", action=None, suspicion=0.5),
        dict(status="cancelled", function=None, action=None),
    ],
)
def test_sentinel_modified_is_only_for_modify(event: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="modified is set only"):
        _sentinel_event(modified=_MODIFIED, **event)


@pytest.mark.parametrize(
    "event",
    [
        dict(action="continue"),
        dict(action="terminate"),
        dict(kind="observation", action=None, suspicion=0.5),
        dict(status="bypassed", function=None, action=None),
    ],
)
def test_sentinel_message_is_only_for_reject(event: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="message is set only"):
        _sentinel_event(message="use X instead", **event)


def test_sentinel_event_renders_in_tui() -> None:
    from rich.console import Console

    from inspect_ai._display.textual.widgets.transcript import render_event

    event = _sentinel_event(
        path="[bold]attempt [/red]",
        explanation="matched [/red] in output",
        message="use [/red] instead",
    )
    displays = render_event(event)
    assert displays is not None and len(displays) == 1
    assert displays[0].title == "sentinel: tool_call"
    buffer = io.StringIO()
    Console(file=buffer, width=200).print(displays[0].content)
    output = buffer.getvalue()
    assert "[bold]attempt [/red]" in output
    assert "matched [/red] in output" in output
    assert "use [/red] instead" in output


def test_sentinel_event_tui_shows_unreported_status() -> None:
    from rich.console import Console

    from inspect_ai._display.textual.widgets.transcript import render_event

    displays = render_event(_sentinel_event(status="superseded"))
    assert displays is not None
    buffer = io.StringIO()
    Console(file=buffer, width=200).print(displays[0].content)
    assert "reject (superseded)" in buffer.getvalue()


def test_sentinel_event_tui_shows_the_error() -> None:
    from rich.console import Console

    from inspect_ai._display.textual.widgets.transcript import render_event

    event = _observation(status="error", suspicion=None, error="ValueError: [/red]")
    displays = render_event(event)
    assert displays is not None
    buffer = io.StringIO()
    Console(file=buffer, width=200).print(displays[0].content)
    assert "observation (error): ValueError: [/red]" in buffer.getvalue()
