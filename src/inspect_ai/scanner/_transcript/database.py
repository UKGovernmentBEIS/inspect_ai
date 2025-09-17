from __future__ import annotations

import sqlite3
from os import PathLike
from typing import (
    TYPE_CHECKING,
    Iterator,
    Sequence,
    TypeAlias,
)

from typing_extensions import override

from inspect_ai.analysis._dataframe.evals.columns import EvalColumns
from inspect_ai.analysis._dataframe.evals.table import EVAL_LOG_PATH
from inspect_ai.analysis._dataframe.samples.columns import SampleSummary
from inspect_ai.analysis._dataframe.samples.table import SAMPLE_ID, samples_df
from inspect_ai.analysis._dataframe.util import (
    verify_prerequisites as verify_df_prerequisites,
)
from inspect_ai.log._file import (
    EvalLogInfo,
    read_eval_log_sample_async,
)
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

        # resolve logs or df to transcript_df (sample per row)
        if not isinstance(logs, pd.DataFrame):
            self._transcripts_df = samples_df(logs, EvalColumns + SampleSummary)
        else:
            # ensure we have a log path
            if EVAL_LOG_PATH not in logs.columns:
                raise ValueError(
                    f"Transcripts data frame does not have a '{EVAL_LOG_PATH}' column."
                )

            # if there is no sample id then we need to blow out the samples from the logs
            if SAMPLE_ID not in logs.columns:
                logs = logs[EVAL_LOG_PATH].to_list()
                self._transcripts_df = samples_df(logs, EvalColumns + SampleSummary)
            else:
                self._transcripts_df = logs

        # sqlite connection (starts out none)
        self._conn: sqlite3.Connection | None = None

    @override
    async def connect(self) -> None:
        assert self._conn is None
        self._conn = sqlite3.connect(":memory:")
        self._transcripts_df.to_sql(
            "transcripts", self._conn, index=False, if_exists="replace"
        )

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
        sample = await read_eval_log_sample_async(
            t.source, uuid=t.id, resolve_attachments=True
        )
        return Transcript(
            id=t.id,
            source=t.source,
            metadata=t.metadata,
            messages=sample.messages,
            events=sample.events,
        )

    @override
    async def disconnect(self) -> None:
        assert self._conn is not None
        self._conn.close()
