from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TypeAlias

from pydantic import JsonValue, TypeAdapter

from inspect_ai.event._validate import validate_chat_messages
from inspect_ai.log._log import EventsData
from inspect_ai.log._recorders.buffer.types import EventData, JsonData
from inspect_ai.model import ChatMessage

_json_value_list_adapter: TypeAdapter[list[JsonValue]] = TypeAdapter(list[JsonValue])

RawEvent: TypeAlias = JsonData
"""Event payload deserialized from JSON but not validated into a typed Event.

The raw form is the cheap path for consumers that either re-serialize directly
or inspect discriminator fields before validating a subset.
"""


@dataclass
class SampleHistory:
    """Latest logical sample history with .eval positional pool refs."""

    raw_event_rows: list[EventData]
    message_pool: list[ChatMessage]
    call_pool: list[JsonValue]
    attachments: dict[str, str]
    events_data: EventsData = field(init=False)

    def __post_init__(self) -> None:
        self.message_pool = validate_chat_messages(
            self.message_pool, context={"deserializing": True}
        )
        self.call_pool = _json_value_list_adapter.validate_python(self.call_pool)
        self.events_data = EventsData(messages=self.message_pool, calls=self.call_pool)

    @property
    def event_count(self) -> int:
        return len(self.raw_event_rows)

    def iter_events(self) -> Iterator[RawEvent]:
        """Iterate raw event payloads.

        Raw-by-design consumers include the streaming recorder, which writes
        condensed events directly, and retry-error construction, which scans
        event discriminators before validating only the suffix.
        """
        for row in self.raw_event_rows:
            yield row.event

    def attachment(self, hash: str) -> str | None:
        return self.attachments.get(hash)
