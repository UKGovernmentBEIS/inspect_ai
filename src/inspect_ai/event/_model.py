from datetime import datetime
from typing import Literal

from pydantic import Field, field_serializer

from inspect_ai._util.dateutil import UtcDatetime, datetime_to_iso_format_safe
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from ._base import BaseEvent


class ModelEvent(BaseEvent):
    """Call to a language model."""

    event: Literal["model"] = Field(default="model")
    """Event type."""

    model: str
    """Model name."""

    role: str | None = Field(default=None)
    """Model role."""

    input: list[ChatMessage]
    """Model input (list of messages)."""

    input_refs: list[tuple[int, int]] | None = Field(default=None)
    """Message pool references for input. Each element is a (start, end_exclusive) range."""

    tools: list[ToolInfo]
    """Tools available to the model."""

    tool_choice: ToolChoice
    """Directive to the model which tools to prefer."""

    config: GenerateConfig
    """Generate config used for call to model."""

    output: ModelOutput
    """Output from model."""

    retries: int | None = Field(default=None)
    """Legacy retry count.

    On terminal post-fix events, mirrors ``http_retries`` if non-zero, else
    ``call_retries``. Prefer ``call_retries`` and ``http_retries`` for new code.
    """

    error: str | None = Field(default=None)
    """Error which occurred during model call."""

    traceback: str | None = Field(default=None)
    """Error traceback (plain text)."""

    traceback_ansi: str | None = Field(default=None)
    """Error traceback with ANSI color codes for display."""

    cache: Literal["read", "write"] | None = Field(default=None)
    """Was this a cache read or write."""

    call: ModelCall | None = Field(default=None)
    """Raw call made to model API."""

    completed: UtcDatetime | None = Field(default=None)
    """Time this attempt completed."""

    working_time: float | None = Field(default=None)
    """Working-clock duration of this attempt."""

    call_id: str | None = Field(default=None)
    """Stable id shared by all ModelEvents from one logical generate call."""

    attempt: int | None = Field(default=None)
    """1-based outer-attempt number within ``call_id``. None on legacy logs."""

    call_started_at: UtcDatetime | None = Field(default=None)
    """Wall-clock time the logical generate call began. Terminal event only."""

    call_completed_at: UtcDatetime | None = Field(default=None)
    """Wall-clock time the logical generate call completed. Terminal event only."""

    call_working_start: float | None = Field(default=None)
    """Sample working-clock value when the logical generate call began."""

    call_working_time: float | None = Field(default=None)
    """Logical generate working-clock duration. Terminal event only."""

    call_retries: int | None = Field(default=None)
    """Number of outer Tenacity retries actually scheduled. Terminal event only."""

    http_retries: int | None = Field(default=None)
    """Total retry signals reported via ``report_http_retry``. Terminal event only."""

    @field_serializer("completed")
    def serialize_completed(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return datetime_to_iso_format_safe(dt)

    @field_serializer("call_started_at")
    def serialize_call_started_at(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return datetime_to_iso_format_safe(dt)

    @field_serializer("call_completed_at")
    def serialize_call_completed_at(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return datetime_to_iso_format_safe(dt)
