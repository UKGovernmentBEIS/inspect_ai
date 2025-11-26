from datetime import datetime, timezone
from typing import Any, Callable, Literal

from pydantic import ConfigDict, Field, JsonValue, field_serializer

from inspect_ai._util.dateutil import UtcDatetime, datetime_to_iso_format_safe
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCallContent, ToolCallError

from ._base import BaseEvent


class ToolEvent(BaseEvent):
    """Call to a tool."""

    event: Literal["tool"] = Field(default="tool")
    """Event type."""

    type: Literal["function"] = Field(default="function")
    """Type of tool call (currently only 'function')"""

    id: str
    """Unique identifier for tool call."""

    function: str
    """Function called."""

    arguments: dict[str, JsonValue]
    """Arguments to function."""

    view: ToolCallContent | None = Field(default=None)
    """Custom view of tool call input."""

    result: ToolResult = Field(default_factory=str)
    """Function return value."""

    truncated: tuple[int, int] | None = Field(default=None)
    """Bytes truncated (from,to) if truncation occurred"""

    error: ToolCallError | None = Field(default=None)
    """Error that occurred during tool call."""

    events: list[Any] = Field(default_factory=list)
    """Transcript of events for tool.

    Note that events are no longer recorded separately within
    tool events but rather all events are recorded in the main
    transcript. This field is deprecated and here for backwards
    compatibility with transcripts that have sub-events.
    """

    completed: UtcDatetime | None = Field(default=None)
    """Time that tool call completed (see `timestamp` for started)"""

    working_time: float | None = Field(default=None)
    """Working time for tool call (i.e. time not spent waiting on semaphores)."""

    agent: str | None = Field(default=None)
    """Name of agent if the tool call was an agent handoff."""

    failed: bool | None = Field(default=None)
    """Did the tool call fail with a hard error?."""

    message_id: str | None = Field(default=None)
    """Id of ChatMessageTool associated with this event."""

    def _set_result(
        self,
        result: ToolResult,
        truncated: tuple[int, int] | None,
        error: ToolCallError | None,
        waiting_time: float,
        agent: str | None,
        failed: bool | None,
        message_id: str | None,
    ) -> None:
        self.result = result
        self.truncated = truncated
        self.error = error
        self.pending = None
        completed = datetime.now(timezone.utc)
        self.completed = completed
        self.working_time = (completed - self.timestamp).total_seconds() - waiting_time
        self.agent = agent
        self.failed = failed
        self.message_id = message_id

    # mechanism for operator to cancel the tool call

    def _set_cancel_fn(self, cancel_fn: Callable[[], None]) -> None:
        """Set the tool task (for possible cancellation)"""
        self._cancel_fn = cancel_fn

    def _cancel(self) -> None:
        """Cancel the tool task."""
        if self._cancel_fn and not self.cancelled:
            self._cancelled = True
            self._cancel_fn()

    @property
    def cancelled(self) -> bool:
        """Was the task cancelled?"""
        return self._cancelled is True

    _cancelled: bool | None = None
    """Was this tool call cancelled?"""

    _cancel_fn: Callable[[], None] | None = None
    """Function which can be used to cancel the tool call."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    """Required so that we can include '_cancel_fn' as a member."""

    @field_serializer("completed")
    def serialize_completed(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return datetime_to_iso_format_safe(dt)
