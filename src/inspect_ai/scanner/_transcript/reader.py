from __future__ import annotations

from os import PathLike
from typing import (
    TYPE_CHECKING,
    Iterator,
    Sequence,
    TypeAlias,
)

from inspect_ai.analysis._dataframe.evals.table import evals_df
from inspect_ai.analysis._dataframe.util import (
    verify_prerequisites as verify_df_prerequisites,
)
from inspect_ai.log._file import EvalLogInfo

from .transcripts import Transcripts
from .types import Transcript, TranscriptContent, TranscriptInfo

if TYPE_CHECKING:
    import pandas as pd

LogPaths: TypeAlias = (
    PathLike[str] | str | EvalLogInfo | Sequence[PathLike[str] | str | EvalLogInfo]
)


def transcripts(logs: LogPaths | "pd.DataFrame") -> Transcripts:
    # pandas required
    verify_df_prerequisites()
    import pandas as pd

    # resolve logs to df
    if not isinstance(logs, pd.DataFrame):
        logs = evals_df(logs)

    # resolve evals_df to samples_df if required
    samples_df = pd.DataFrame()

    # return transcripts w/ function for creating reader
    return Transcripts(lambda: EvalLogReader(samples_df))


class EvalLogReader(Transcripts.Reader):
    def __init__(self, samples_df: "pd.DataFrame") -> None:
        # TODO: turn samples_df into a sqlite in-memory db for resolving queries
        self._transcripts = transcripts

    def query(
        self,
        where: list[str],
        limit: int | None = None,
        shuffle: bool | int = False,
    ) -> Iterator[TranscriptInfo]:
        return iter([])

    async def read(self, t: TranscriptInfo, content: TranscriptContent) -> Transcript:
        return Transcript(id=t.id, source=t.source)

    async def close(self) -> None:
        pass
