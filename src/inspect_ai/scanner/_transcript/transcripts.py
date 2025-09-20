from __future__ import annotations

import abc
from copy import deepcopy
from typing import (
    TYPE_CHECKING,
    AsyncGenerator,
)

from pydantic import JsonValue

from .database import EvalLogTranscripts, LogPaths
from .metadata import Condition
from .types import Transcript, TranscriptContent

if TYPE_CHECKING:
    import pandas as pd


class TranscriptsData:
    type: str
    data: JsonValue


class Transcripts(abc.ABC):
    """Collection of transcripts for scanning."""

    def __init__(self) -> None:
        self._where: list[Condition] = []
        self._limit: int | None = None
        self._shuffle: bool | int = False
        self._content = TranscriptContent()

    def where(self, condition: Condition) -> "Transcripts":
        transcripts = deepcopy(self)
        transcripts._where.append(condition)
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

    @abc.abstractmethod
    async def count(self) -> int: ...

    @abc.abstractmethod
    async def collect(self) -> AsyncGenerator[Transcript, None]: ...


def transcripts(logs: LogPaths | "pd.DataFrame") -> Transcripts:
    return EvalLogTranscripts(logs)
