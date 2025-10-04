from dataclasses import dataclass, field
from typing import Iterator, Literal, Protocol, TypeAlias

from pydantic import BaseModel, Field, JsonValue

from inspect_ai.event._event import Event
from inspect_ai.model._chat_message import ChatMessage

from .metadata import Condition

MessageType = Literal["system", "user", "assistant", "tool"]
EventType = Literal[
    "sample_init",
    "sample_limit",
    "sandbox",
    "state",
    "store",
    "model",
    "tool",
    "approval",
    "input",
    "score",
    "error",
    "logger",
    "info",
    "span_begin",
    "span_end",
]

MessageFilter: TypeAlias = Literal["all"] | list[MessageType] | None
EventFilter: TypeAlias = Literal["all"] | list[EventType] | None


@dataclass
class TranscriptContent:
    messages: MessageFilter = field(default=None)
    events: EventFilter = field(default=None)


class TranscriptInfo(BaseModel):
    """Transcript identifier, location, and metadata."""

    id: str
    """Globally unique id for transcript (e.g. sample uuid)."""

    source_id: str
    """Globally unique ID for transcript source (e.g. eval_id)."""

    source_uri: str
    """URI for source data (e.g. log file path)"""

    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    """e.g. eval config (model, scores, task params, etc.)."""


class Transcript(TranscriptInfo):
    """Transcript info and transcript content (messages and events)."""

    messages: list[ChatMessage] = Field(default_factory=list)
    """Main message thread."""

    events: list[Event] = Field(default_factory=list)
    """Events from transcript."""


class TranscriptDB(Protocol):
    async def connect(self) -> None: ...
    async def count(
        self,
        where: list[Condition],
        limit: int | None = None,
    ) -> int: ...
    async def query(
        self,
        where: list[Condition],
        limit: int | None = None,
        shuffle: bool | int = False,
    ) -> Iterator[TranscriptInfo]: ...
    async def read(
        self, t: TranscriptInfo, content: TranscriptContent
    ) -> Transcript: ...
    async def disconnect(self) -> None: ...
