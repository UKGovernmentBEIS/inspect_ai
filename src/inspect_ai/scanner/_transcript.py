from copy import deepcopy
from typing import AsyncGenerator, Protocol

from pydantic import BaseModel, Field, JsonValue

from inspect_ai.log._transcript import Event
from inspect_ai.model._chat_message import ChatMessage

from ._filter import TranscriptContent


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


class TranscriptSource(Protocol):
    async def index(self) -> list[TranscriptInfo]: ...
    async def load(
        self, t: TranscriptInfo, content: TranscriptContent
    ) -> Transcript: ...


class Transcripts:
    """Async generator class that yields Transcript objects"""

    def __init__(self, source: TranscriptSource) -> None:
        self._source = source
        self._index: list[TranscriptInfo] | None = None
        self._filters: list[str] = []
        self._content = TranscriptContent()

    # TODO: pypika queries
    def filter(self, filter: str) -> "Transcripts":
        transcripts = deepcopy(self)
        transcripts._filters.append(filter)
        return transcripts

    def content(self, content: TranscriptContent) -> "Transcripts":
        transcripts = deepcopy(self)
        transcripts._content = content
        return transcripts

    async def collect(self) -> AsyncGenerator[Transcript, None]:
        # ensure we have loaded the index
        if self._index is None:
            self._index = await self._source.index()

        # TODO: apply filters
        transcripts = self._index.copy()

        # load transcripts
        for t in iter(transcripts):
            yield await self._source.load(t, self._content)


# from inspect_ai.scanner import metadata as m

# metadata['task_status']
# lambda m: m[]
