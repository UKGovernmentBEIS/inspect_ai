from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from inspect_ai.event._event import DiscriminatedEvent, Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent


def test_event_public_alias_stays_introspectable() -> None:
    # The plain `Event` alias must remain a bare Union so `get_args()` and other
    # type introspection keep working. Wrapping the *public* alias in a
    # discriminator is what forced the revert of #2714, so the discriminated
    # variant is a separate alias and `Event` itself is left untouched.
    members = get_args(Event)
    assert ModelEvent in members
    assert InfoEvent in members
    assert len(members) == 23


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
