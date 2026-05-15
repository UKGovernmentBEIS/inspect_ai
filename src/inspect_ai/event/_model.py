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

OPERATOR_CANCEL_ERROR = "Cancelled by operator"
"""Sentinel string stamped on ``ModelEvent.error`` when an external
operator (e.g. ``AcpSession.cancel_current_turn``) cancels an in-flight
``generate`` call. Read sites:

- ``inspect_ai.model._model.complete()`` short-circuits its
  natural-completion overwrite when the event already carries this
  marker (the model can return successfully inside the cancellation
  propagation window).
- TUI / log renderers can suppress display of cancelled events.

The value is intentionally a fixed string so it round-trips through
the JSON eval log; downstream tooling can detect operator cancels
without depending on the agent/ACP layer.
"""


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
    """Retries for the model API request."""

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
    """Time that model call completed (see `timestamp` for started)"""

    working_time: float | None = Field(default=None)
    """working time for model call that succeeded (i.e. was not retried)."""

    @field_serializer("completed")
    def serialize_completed(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return datetime_to_iso_format_safe(dt)
