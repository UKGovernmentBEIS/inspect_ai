from typing import Literal

from pydantic import Field, JsonValue

from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._base import BaseEvent


class SampleInitEvent(BaseEvent):
    """Beginning of processing a Sample."""

    event: Literal["sample_init"] = Field(default="sample_init")
    """Event type."""

    sample: Sample
    """Sample."""

    state: JsonValue
    """Initial state."""
