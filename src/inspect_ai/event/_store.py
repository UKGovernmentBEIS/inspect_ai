from typing import Literal

from pydantic import Field

from inspect_ai._util.json import JsonChange

from ._base import BaseEvent


class StoreEvent(BaseEvent):
    """Change to data within the current `Store`."""

    event: Literal["store"] = Field(default="store")
    """Event type."""

    changes: list[JsonChange]
    """List of changes to the `Store`."""
