from typing import Literal

from pydantic import Field

from inspect_ai.event._base import BaseEvent


class SampleLimitEvent(BaseEvent):
    """The sample was unable to finish processing due to a limit"""

    event: Literal["sample_limit"] = Field(default="sample_limit")
    """Event type."""

    type: Literal["message", "time", "working", "token", "cost", "operator", "custom"]
    """Type of limit that halted processing"""

    message: str
    """A message associated with this limit"""

    limit: float | None = Field(default=None)
    """The limit value (if any)"""
