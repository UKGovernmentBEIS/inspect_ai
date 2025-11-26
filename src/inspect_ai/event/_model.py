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
