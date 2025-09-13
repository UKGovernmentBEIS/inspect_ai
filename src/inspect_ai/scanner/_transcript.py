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
