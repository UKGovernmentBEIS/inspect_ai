from __future__ import annotations

import hashlib
import sqlite3
from functools import reduce
from os import PathLike
from typing import (
    TYPE_CHECKING,
    Any,
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

from .metadata import Condition
from .types import Transcript, TranscriptContent, TranscriptInfo

if TYPE_CHECKING:
    import pandas as pd

TRANSCRIPTS = "transcripts"

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
            TRANSCRIPTS, self._conn, index=False, if_exists="replace"
        )

    @override
    async def count(
        self,
        where: list[Condition],
        limit: int | None = None,
    ) -> int:
        assert self._conn is not None

        # build sql with where clause
        where_clause, where_params = self._build_where_clause(where)

        if limit is not None:
            # When limit is specified, we need to count from a subquery
            sql = f"SELECT COUNT(*) FROM (SELECT * FROM {TRANSCRIPTS}{where_clause} LIMIT {limit})"
        else:
            # Simple count without limit
            sql = f"SELECT COUNT(*) FROM {TRANSCRIPTS}{where_clause}"

        # execute the query
        cursor = self._conn.execute(sql, where_params)
        result = cursor.fetchone()

        return result[0] if result else 0

    @override
    async def query(
        self,
        where: list[Condition],
        limit: int | None = None,
        shuffle: bool | int = False,
    ) -> Iterator[TranscriptInfo]:
        assert self._conn is not None

        # build sql with where clause
        where_clause, where_params = self._build_where_clause(where)
        sql = f"SELECT * FROM {TRANSCRIPTS}{where_clause}"

        # execute the query
        cursor = self._conn.execute(sql, where_params)

        # get column names
        column_names = [desc[0] for desc in cursor.description]

        # collect all results
        results = []
        for row in cursor:
            # create a dict of column name to value
            row_dict = dict(zip(column_names, row))

            # extract required fields
            transcript_id = row_dict.pop("sample_id", None)
            transcript_source = row_dict.pop("log", None)

            # ensure we have required fields
            if transcript_id is None or transcript_source is None:
                raise ValueError(
                    f"Missing required fields: sample_id={transcript_id}, log={transcript_source}"
                )

            # everything else goes into metadata
            metadata = {k: v for k, v in row_dict.items() if v is not None}

            results.append(
                TranscriptInfo(
                    id=transcript_id, source=transcript_source, metadata=metadata
                )
            )

        # shuffle if specified
        if shuffle:
            # If shuffle is True, use a default seed of 0; otherwise use the provided seed
            seed = 0 if shuffle is True else shuffle

            def hash_key(info: TranscriptInfo) -> str:
                # Create a deterministic hash based on id and seed
                content = f"{info.id}:{seed}"
                return hashlib.sha256(content.encode()).hexdigest()

            results.sort(key=hash_key)

        # apply limit if specified
        if limit is not None:
            results = results[:limit]

        return iter(results)

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

    def _build_where_clause(self, where: list[Condition]) -> tuple[str, list[Any]]:
        """Build WHERE clause and parameters from conditions.

        Args:
            where: List of conditions to combine with AND.

        Returns:
            Tuple of (where_clause, parameters). where_clause is empty string if no conditions.
        """
        if len(where) > 0:
            condition: Condition = (
                where[0] if len(where) == 1 else reduce(lambda a, b: a & b, where)
            )
            where_sql, where_params = condition.to_sql()
            return f" WHERE {where_sql}", where_params
        return "", []
