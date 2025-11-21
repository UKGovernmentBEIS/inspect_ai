from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_serializer, field_validator

from inspect_ai._util.dateutil import UtcDatetime, datetime_to_iso_format_safe
from inspect_ai.event._base import BaseEvent


class SubtaskEvent(BaseEvent):
    """Subtask spawned."""

    event: Literal["subtask"] = Field(default="subtask")
    """Event type."""

    name: str
    """Name of subtask function."""

    type: str | None = Field(default=None)
    """Type of subtask"""

    input: dict[str, Any]
    """Subtask function inputs."""

    @field_validator("input", mode="before")
    @classmethod
    def validate_input(cls, v: Any) -> dict[str, Any]:
        """Handle backward compatibility for old logs where input was a list."""
        if not isinstance(v, dict):
            return {}
        return v

    result: Any = Field(default=None)
    """Subtask function result."""

    events: list[Any] = Field(default_factory=list)
    """Transcript of events for subtask.

    Note that events are no longer recorded separately within
    subtasks but rather all events are recorded in the main
    transcript. This field is deprecated and here for backwards
    compatibility with transcripts that have sub-events.
    """

    completed: UtcDatetime | None = Field(default=None)
    """Time that subtask completed (see `timestamp` for started)"""

    working_time: float | None = Field(default=None)
    """Working time for subtask (i.e. time not spent waiting on semaphores or model retries)."""

    @field_serializer("completed")
    def serialize_completed(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return datetime_to_iso_format_safe(dt)
