import abc
import base64
import pickle
from copy import deepcopy
from typing import (
    Any,
    AsyncGenerator,
)

from .metadata import Condition
from .types import Transcript, TranscriptContent


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

    @abc.abstractmethod
    async def count(self) -> int: ...

    @abc.abstractmethod
    async def collect(
        self, content: TranscriptContent
    ) -> AsyncGenerator[Transcript, None]: ...

    @abc.abstractmethod
    def type(self) -> str: ...

    def save_spec(self) -> dict[str, Any]:
        return dict(
            type=self.type(),
            where=base64.b64encode(pickle.dumps(self._where)).decode("utf-8"),
            limit=self._limit,
            shuffle=self._shuffle,
        )

    def load_spec(self, spec: dict[str, Any]) -> None:
        self._where = pickle.loads(base64.b64decode(spec["where"]))
        self._limit = spec["limit"]
        self._shuffle = spec["shuffle"]
