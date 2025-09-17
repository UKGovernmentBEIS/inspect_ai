from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from inspect_ai.log._transcript import Event
from inspect_ai.model._chat_message import ChatMessage

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


@dataclass
class TranscriptContent:
    messages: Literal["all"] | list[MessageType] | None = field(default=None)
    events: Literal["all"] | list[EventType] | None = field(default=None)


class TranscriptInfo(BaseModel):
    """Transcript identifier, location, and metadata."""

    id: str
    """Unique id for transcript (e.g. sample uuid)."""

    source: str
    """URI for source data (e.g. log file path)"""

    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    """e.g. eval config (model, scores, task params, etc.)."""


class Transcript(TranscriptInfo):
    """Transcript info and transcript content (messages and events)."""

    messages: list[ChatMessage] = Field(default_factory=list)
    """Main message thread."""

    events: list[Event] = Field(default_factory=list)
    """Events from transcript."""
