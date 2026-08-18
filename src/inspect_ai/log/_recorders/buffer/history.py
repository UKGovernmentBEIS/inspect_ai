from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
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
    """Latest logical sample history with .eval positional pool refs.

    Pools are keyed by .eval positional index: full-history reads carry every
    entry (contiguous positions from 0), while page-scoped reads carry only
    the positions referenced by the page's events.
    """

    raw_event_rows: list[EventData]
    message_pool: dict[int, ChatMessage]
    call_pool: dict[int, JsonValue]
    attachments: dict[str, str]
    page_scoped: bool = False
    """True when pools/attachments carry only the entries referenced by this
    page's events (which may still form a contiguous prefix, so completeness
    can't be inferred from the keys)."""

    def __post_init__(self) -> None:
        validated_messages = validate_chat_messages(
            list(self.message_pool.values()), context={"deserializing": True}
        )
        self.message_pool = dict(
            zip(self.message_pool, validated_messages, strict=True)
        )
        validated_calls = _json_value_list_adapter.validate_python(
            list(self.call_pool.values())
        )
        self.call_pool = dict(zip(self.call_pool, validated_calls, strict=True))

    @property
    def events_data(self) -> EventsData:
        """Dense pools for embedding in an ``EvalSample`` / .eval log.

        Positional refs index into the dense lists, so this requires a
        full-history read (complete pools with contiguous positions from 0);
        page-scoped histories raise rather than silently misalign refs.
        """
        if self.page_scoped:
            raise RuntimeError(
                "events_data requires a full sample history; this history "
                "is page-scoped and carries only referenced pool entries"
            )
        return EventsData(
            messages=[self.message_pool[i] for i in range(len(self.message_pool))],
            calls=[self.call_pool[i] for i in range(len(self.call_pool))],
        )

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
