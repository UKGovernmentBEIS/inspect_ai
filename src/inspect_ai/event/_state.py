from typing import Literal

from pydantic import Field

from inspect_ai._util.json import JsonChange
from inspect_ai.event._base import BaseEvent


class StateEvent(BaseEvent):
    """Change to the current `TaskState`"""

    event: Literal["state"] = Field(default="state")
    """Event type."""

    changes: list[JsonChange]
    """List of changes to the `TaskState`"""
