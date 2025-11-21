from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue, field_serializer

from inspect_ai.event._base import BaseEvent


class SandboxEvent(BaseEvent):
    """Sandbox execution or I/O"""

    event: Literal["sandbox"] = Field(default="sandbox")
    """Event type"""

    action: Literal["exec", "read_file", "write_file"]
    """Sandbox action"""

    cmd: str | None = Field(default=None)
    """Command (for exec)"""

    options: dict[str, JsonValue] | None = Field(default=None)
    """Options (for exec)"""

    file: str | None = Field(default=None)
    """File (for read_file and write_file)"""

    input: str | None = Field(default=None)
    """Input (for cmd and write_file). Truncated to 100 lines."""

    result: int | None = Field(default=None)
    """Result (for exec)"""

    output: str | None = Field(default=None)
    """Output (for exec and read_file). Truncated to 100 lines."""

    completed: datetime | None = Field(default=None)
    """Time that sandbox action completed (see `timestamp` for started)"""

    @field_serializer("completed")
    def serialize_completed(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.astimezone().isoformat()
