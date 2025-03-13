from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator
from shortuuid import uuid


class ChatMessageUser(BaseModel):
    """Base class for chat messages."""

    id: str | None = Field(default=None)
    """Unique identifer for message."""

    content: str
    """Content"""

    @field_validator("id", mode="before")
    @classmethod
    def maybe_generate_id(cls, v: Any, info: ValidationInfo):
        # auto-generate an id, but don't do so when deserializing
        if (
            v is None
            and isinstance(info.context, dict)
            and not info.context.get("deserializing", False)
        ):
            return uuid()
        else:
            return v


def test_message_id_auto_assign():
    message = ChatMessageUser(content="foo")
    assert message.id


def test_message_id_no_deserialize():
    # create a message w/o an id
    message = ChatMessageUser(content="foo")
    message_dict = message.model_dump(exclude="id", exclude_none=True)

    # deserialize and confirm there is no id
    message = ChatMessageUser.model_validate(
        message_dict, context={"deserializing": True}
    )
    assert message.id is None
