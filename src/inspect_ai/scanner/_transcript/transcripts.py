from __future__ import annotations

from copy import deepcopy
from typing import (
    TYPE_CHECKING,
    AsyncGenerator,
)

from .database import EvalLogTranscriptsDB, LogPaths
from .types import Transcript, TranscriptContent, TranscriptDB

if TYPE_CHECKING:
    import pandas as pd


class Transcripts:
    """Collection of transcripts for scanning."""

    def __init__(self, db: TranscriptDB) -> None:
        self._db = db
        self._where: list[str] = []
        self._limit: int | None = None
        self._shuffle: bool | int = False
        self._content = TranscriptContent()

    def where(self, where: str) -> "Transcripts":
        transcripts = deepcopy(self)
        transcripts._where.append(where)
        return transcripts

    def limit(self, n: int) -> "Transcripts":
        transcripts = deepcopy(self)
        transcripts._limit = n
        return transcripts

    def shuffle(self, seed: int | None = None) -> "Transcripts":
        transcripts = deepcopy(self)
        transcripts._shuffle = seed if seed is not None else True
        return transcripts

    def content(self, content: TranscriptContent) -> "Transcripts":
        transcripts = deepcopy(self)
        transcripts._content = content
        return transcripts

    async def collect(self) -> AsyncGenerator[Transcript, None]:
        await self._db.connect()
        try:
            # apply filters
            index = await self._db.query(self._where, self._limit, self._shuffle)

            # yield transcripts
            for t in index:
                yield await self._db.read(t, self._content)
        finally:
            await self._db.disconnect()


def transcripts(logs: LogPaths | "pd.DataFrame") -> Transcripts:
    return Transcripts(EvalLogTranscriptsDB(logs))
