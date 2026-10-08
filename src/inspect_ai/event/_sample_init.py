from typing import Annotated, Literal

from pydantic import Field, JsonValue, PlainSerializer

from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._base import BaseEvent


class SampleInitEvent(BaseEvent):
    """Beginning of processing a Sample."""

    event: Literal["sample_init"] = Field(default="sample_init")
    """Event type."""

    sample: Annotated[
        Sample,
        PlainSerializer(
            lambda sample: sample.model_copy(update={"description": None}),
            return_type=Sample,
        ),
    ]
    """Sample."""

    state: JsonValue = None
    """Initial state.

    Defaults to None so events round-trip through log serialization,
    which writes with exclude_none=True (a None state is omitted from
    the written JSON and must not fail validation on read).
    """
