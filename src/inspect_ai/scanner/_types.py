from typing import Any, Literal, Protocol, Sequence, TypeVar

from pydantic import BaseModel, Field, JsonValue

from inspect_ai.log._transcript import Event
from inspect_ai.model._chat_message import ChatMessage


class Transcript(BaseModel):
    """Transcript to be scanned."""

    id: str
    """Globally unique id for transcript (e.g. sample uuid)."""

    source: str
    """URI for source data (e.g. log file path)"""

    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    """e.g. eval config (model, scores, task params, etc.)."""

    messages: list[ChatMessage] = Field(default_factory=list)
    """Main message thread."""

    events: list[Event] = Field(default_factory=list)
    """Events from transcript."""


InputT = TypeVar(
    "InputT",
    bound=Transcript
    | Sequence[Transcript]
    | ChatMessage
    | Sequence[ChatMessage]
    | Event
    | Sequence[Event],
    contravariant=True,
)
"""Input type required by a scanner."""


class Reference(BaseModel):
    """Reference to scanned content."""

    type: Literal["message", "event"]
    """Reference type."""

    id: str
    """Reference id (message or event id)"""


class Result(BaseModel):
    """Scanner result."""

    value: JsonValue
    """Scanner value."""

    answer: str | None = Field(default=None)
    """Answer extracted from model output (optional)"""

    explanation: str | None = Field(default=None)
    """Explanation of result (optional)."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional metadata related to the result"""

    references: list[Reference] = Field(default_factory=list)
    """References to relevant messages or events."""


# scanner protocol
class Scanner(Protocol[InputT]):
    async def __call__(self, input: InputT) -> Result | None: ...


async def foo(input: ChatMessage) -> Result:
    return Result(value=0)
