from __future__ import annotations

from os import PathLike
from typing import (
    TYPE_CHECKING,
    Iterator,
    Sequence,
    TypeAlias,
)

from typing_extensions import override

from inspect_ai.analysis._dataframe.evals.table import evals_df
from inspect_ai.analysis._dataframe.util import (
    verify_prerequisites as verify_df_prerequisites,
)
from inspect_ai.log._file import EvalLogInfo
from inspect_ai.scanner._transcript.types import TranscriptDB

from .types import Transcript, TranscriptContent, TranscriptInfo

if TYPE_CHECKING:
    import pandas as pd

LogPaths: TypeAlias = (
    PathLike[str] | str | EvalLogInfo | Sequence[PathLike[str] | str | EvalLogInfo]
)


class EvalLogTranscriptsDB(TranscriptDB):
    def __init__(self, logs: LogPaths | "pd.DataFrame"):
        # pandas required
        verify_df_prerequisites()
        import pandas as pd

        # resolve logs to df
        if not isinstance(logs, pd.DataFrame):
            logs = evals_df(logs)

        # resolve evals_df to samples_df if required
        # samples_df = pd.DataFrame()

    @override
    async def connect(self) -> None:
        pass

    @override
    async def query(
        self,
        where: list[str],
        limit: int | None = None,
        shuffle: bool | int = False,
    ) -> Iterator[TranscriptInfo]:
        return iter([])

    @override
    async def read(self, t: TranscriptInfo, content: TranscriptContent) -> Transcript:
        return Transcript(id="foo", source="bar")

    @override
    async def disconnect(self) -> None:
        pass
