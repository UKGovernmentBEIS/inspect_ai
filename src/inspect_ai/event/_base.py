from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_serializer
from shortuuid import uuid

from inspect_ai._util.constants import DESERIALIZING
from inspect_ai._util.dateutil import (
    UtcDatetime,
    datetime_now_utc,
    datetime_to_iso_format_safe,
)
from inspect_ai._util.working import sample_working_time


class BaseEvent(BaseModel):
    uuid: str | None = Field(default=None)
    """Unique identifer for event."""

    span_id: str | None = Field(default=None)
    """Span the event occurred within."""

    timestamp: UtcDatetime = Field(default_factory=datetime_now_utc)
    """Clock time at which event occurred."""

    working_start: float = Field(default_factory=sample_working_time)
    """Working time (within sample) at which the event occurred."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional event metadata."""

    pending: bool | None = Field(default=None)
    """Is this event pending?"""

    def model_post_init(self, __context: Any) -> None:
        from inspect_ai.util._span import current_span_id

        # check if deserializing
        is_deserializing = isinstance(__context, dict) and __context.get(
            DESERIALIZING, False
        )

        # Generate id fields if not deserializing
        if not is_deserializing:
            if self.uuid is None:
                self.uuid = uuid()
            if self.span_id is None:
                self.span_id = current_span_id()

    @field_serializer("timestamp")
    def serialize_timestamp(self, dt: datetime) -> str:
        return datetime_to_iso_format_safe(dt)
