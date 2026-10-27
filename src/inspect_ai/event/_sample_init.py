from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    JsonValue,
    PlainSerializer,
    TypeAdapter,
    ValidationInfo,
    field_validator,
)

from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._base import BaseEvent
from inspect_ai.model._chat_message import ChatMessage

_CHAT_MESSAGES_ADAPTER: TypeAdapter[list[ChatMessage]] = TypeAdapter(list[ChatMessage])


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

    @field_validator("sample", mode="before")
    @classmethod
    def _validate_sample_input(cls, value: Any, info: ValidationInfo) -> Any:
        """Validate the sample's input messages with this validation's context.

        `Sample` has a custom `__init__`, which pydantic calls without the
        validation context, so input messages read from a log would otherwise
        be assigned a new id on every read.
        """
        if isinstance(value, dict) and isinstance(value.get("input"), list):
            value = {
                **value,
                "input": _CHAT_MESSAGES_ADAPTER.validate_python(
                    value["input"], context=info.context
                ),
            }
        return value
