from typing import Literal

from pydantic import Field

from inspect_ai._util.error import EvalError
from inspect_ai.event._base import BaseEvent


class ErrorEvent(BaseEvent):
    """Event with sample error."""

    event: Literal["error"] = Field(default="error")
    """Event type."""

    error: EvalError
    """Sample error"""
