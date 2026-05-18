from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from pydantic import JsonValue, TypeAdapter

from inspect_ai.log._log import EventsData
from inspect_ai.log._recorders.buffer.types import EventData, JsonData
from inspect_ai.model import ChatMessage

_chat_message_list_adapter: TypeAdapter[list[ChatMessage]] = TypeAdapter(
    list[ChatMessage]
)
_json_value_list_adapter: TypeAdapter[list[JsonValue]] = TypeAdapter(list[JsonValue])


@dataclass
class SampleHistory:
    """Latest logical sample history with .eval positional pool refs."""

    raw_event_rows: list[EventData]
    message_pool: list[ChatMessage]
    call_pool: list[JsonValue]
    attachments: dict[str, str]
    events_data: EventsData = field(init=False)

    def __post_init__(self) -> None:
        self.message_pool = _chat_message_list_adapter.validate_python(
            self.message_pool, context={"deserializing": True}
        )
        self.call_pool = _json_value_list_adapter.validate_python(self.call_pool)
        self.events_data = EventsData(messages=self.message_pool, calls=self.call_pool)

    def event_dicts(self) -> Iterator[JsonData]:
        for row in self.raw_event_rows:
            yield row.event

    def attachment(self, hash: str) -> str | None:
        return self.attachments.get(hash)
