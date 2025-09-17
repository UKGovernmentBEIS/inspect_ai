from copy import deepcopy
from typing import AsyncGenerator, Callable, Iterator, Protocol

from inspect_ai.scanner._transcript.types import (
    Transcript,
    TranscriptContent,
    TranscriptInfo,
)


class Transcripts:
    """Collection of transcripts for scanning."""

    class Reader(Protocol):
        def query(
            self,
            where: list[str],
            limit: int | None = None,
            shuffle: bool | int = False,
        ) -> Iterator[TranscriptInfo]: ...
        async def read(
            self, t: TranscriptInfo, content: TranscriptContent
        ) -> Transcript: ...
        async def close(self) -> None: ...

    def __init__(self, reader: Callable[[], Reader]) -> None:
        self._reader = reader
        self._where: list[str] = []
        self._content = TranscriptContent()

    # TODO: pypika queries
    def where(self, where: str) -> "Transcripts":
        transcripts = deepcopy(self)
        transcripts._where.append(where)
        return transcripts

    def content(self, content: TranscriptContent) -> "Transcripts":
        transcripts = deepcopy(self)
        transcripts._content = content
        return transcripts

    async def collect(self) -> AsyncGenerator[Transcript, None]:
        # create reader
        reader = self._reader()

        try:
            # apply filters
            index = reader.query(self._where)

            # load transcripts
            for t in index:
                yield await reader.read(t, self._content)
        finally:
            # close the reader
            await reader.close()
