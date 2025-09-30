from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from datetime import datetime
from functools import reduce
from os import PathLike
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Iterator,
    Sequence,
    Type,
    TypeAlias,
    overload,
)
from zipfile import ZipFile

from typing_extensions import override

from inspect_ai.analysis._dataframe.columns import Column
from inspect_ai.analysis._dataframe.evals.columns import (
    EvalColumn,
    EvalColumns,
    EvalId,
    EvalLogPath,
)
from inspect_ai.analysis._dataframe.evals.table import EVAL_ID, EVAL_LOG_PATH
from inspect_ai.analysis._dataframe.extract import (
    list_as_str,
    remove_namespace,
    score_value,
    score_values,
)
from inspect_ai.analysis._dataframe.samples.columns import SampleColumn, SampleSummary
from inspect_ai.analysis._dataframe.samples.extract import sample_total_tokens
from inspect_ai.analysis._dataframe.samples.table import SAMPLE_ID, samples_df
from inspect_ai.analysis._dataframe.util import (
    verify_prerequisites as verify_df_prerequisites,
)
from inspect_ai.log._file import (
    EvalLogInfo,
    read_eval_log_sample_summaries,
)
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.scanner._scanspec import ScanTranscripts, TranscriptField
from inspect_ai.scanner._transcript.transcripts import Transcripts

from .json.load_filtered import load_filtered_transcript
from .metadata import Condition
from .types import Transcript, TranscriptContent, TranscriptInfo

if TYPE_CHECKING:
    import pandas as pd

TRANSCRIPTS = "transcripts"

LogPaths: TypeAlias = (
    PathLike[str] | str | EvalLogInfo | Sequence[PathLike[str] | str | EvalLogInfo]
)


class EvalLogTranscripts(Transcripts):
    """Collection of transcripts for scanning."""

    def __init__(self, logs: LogPaths | "pd.DataFrame" | ScanTranscripts) -> None:
        super().__init__()
        if isinstance(logs, ScanTranscripts):
            self._logs: LogPaths | "pd.DataFrame" = self._logs_df_from_snapshot(logs)
        else:
            self._logs = logs
        self._db: EvalLogTranscriptsDB | None = None

    @override
    async def __aenter__(self) -> "Transcripts":
        await self.db.connect()
        return self

    @override
    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        await self.db.disconnect()
        return None

    @override
    async def count(self) -> int:
        return await self.db.count(self._where, self._limit)

    @override
    async def index(self) -> Iterator[TranscriptInfo]:
        return await self.db.query(self._where, self._limit, self._shuffle)

    @override
    async def read(
        self, transcript: TranscriptInfo, content: TranscriptContent
    ) -> Transcript:
        return await self.db.read(transcript, content)

    @override
    async def snapshot(self) -> ScanTranscripts:
        # get the subset of the transcripts df that matches our current query
        df = self.db._transcripts_df
        sample_ids = [item.id for item in await self.index()]
        df = df[df["sample_id"].isin(sample_ids)]

        # get fields
        fields: list[TranscriptField] = json.loads(df.to_json(orient="table"))[
            "schema"
        ]["fields"]

        # get data as csv
        buffer = io.StringIO()
        df.to_csv(buffer, index=False)
        data = buffer.getvalue()

        return ScanTranscripts(
            type="eval_log",
            fields=fields,
            data=data,
        )

    @staticmethod
    def _logs_df_from_snapshot(snapshot: ScanTranscripts) -> "pd.DataFrame":
        import pandas as pd

        # Read CSV data from snapshot
        df = pd.read_csv(io.StringIO(snapshot.data))

        # Process field definitions to apply correct dtypes
        for field in snapshot.fields:
            col_name = field["name"]
            col_type = field["type"]

            # Skip if column doesn't exist in DataFrame
            if col_name not in df.columns:
                continue

            # Handle datetime columns with timezone
            if col_type == "datetime":
                tz = field.get("tz")
                if tz:
                    # Parse datetime with timezone
                    df[col_name] = pd.to_datetime(df[col_name]).dt.tz_localize(tz)
                else:
                    df[col_name] = pd.to_datetime(df[col_name])

            # Handle other specific types
            elif col_type == "integer":
                # Handle nullable integers
                if df[col_name].isnull().any():
                    df[col_name] = df[col_name].astype("Int64")
                else:
                    df[col_name] = df[col_name].astype("int64")

            elif col_type == "number":
                df[col_name] = pd.to_numeric(df[col_name], errors="coerce")

            elif col_type == "boolean":
                df[col_name] = df[col_name].astype("bool")

            elif col_type == "string":
                df[col_name] = df[col_name].astype("string")

            # For any other type, let pandas infer or keep as-is

        return df

    @property
    def db(self) -> EvalLogTranscriptsDB:
        if self._db is None:
            if self._logs is None:
                raise RuntimeError(
                    "Attempted to use eval log transcripts without specifying 'logs'"
                )
            self._db = EvalLogTranscriptsDB(self._logs)
        return self._db


class EvalLogTranscriptsDB:
    def __init__(self, logs: LogPaths | "pd.DataFrame"):
        # pandas required
        verify_df_prerequisites()
        import pandas as pd

        # resolve logs or df to transcript_df (sample per row)
        if not isinstance(logs, pd.DataFrame):
            self._transcripts_df = samples_df(logs, TranscriptColumns)
        else:
            # ensure we have an EVAL_ID
            if EVAL_ID not in logs.columns:
                raise ValueError(
                    f"Transcripts data frame does not have an '{EVAL_ID}' column."
                )

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

        # cache for read_eval_log_sample_summaries results (source, summaries_dict)
        self._summaries_cache: tuple[str, dict[str, EvalSampleSummary]] | None = None

    async def connect(self) -> None:
        # Skip if already connected
        if self._conn is not None:
            return
        self._conn = sqlite3.connect(":memory:")
        self._transcripts_df.to_sql(
            TRANSCRIPTS, self._conn, index=False, if_exists="replace"
        )

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
            transcript_source_id = row_dict.pop("eval_id", None)
            transcript_source_uri = row_dict.pop("log", None)

            # ensure we have required fields
            if transcript_id is None or transcript_source_uri is None:
                raise ValueError(
                    f"Missing required fields: sample_id={transcript_id}, log={transcript_source_uri}"
                )

            # everything else goes into metadata
            metadata = {k: v for k, v in row_dict.items() if v is not None}

            results.append(
                TranscriptInfo(
                    id=transcript_id,
                    source_id=transcript_source_id,
                    source_uri=transcript_source_uri,
                    metadata=metadata,
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

    def _get_eval_summary(self, t: TranscriptInfo) -> EvalSampleSummary:
        """Get the eval summary for a transcript, using cache if available.

        This cache assumes that the typical usage pattern will scan through a single
        source rather than jumping across sources randomly.
        """
        if self._summaries_cache is None or self._summaries_cache[0] != t.source_uri:
            self._summaries_cache = (
                t.source_uri,
                {
                    summary.uuid: summary
                    for summary in read_eval_log_sample_summaries(t.source_uri)
                    if summary.uuid is not None
                },
            )
        return self._summaries_cache[1][t.id]

    async def read(self, t: TranscriptInfo, content: TranscriptContent) -> Transcript:
        summary = self._get_eval_summary(t)
        sample_file_name = f"samples/{summary.id}_epoch_{summary.epoch}.json"
        with ZipFile(t.source_uri, mode="r") as zipfile:
            with zipfile.open(sample_file_name, "r") as sample_json:
                return await load_filtered_transcript(
                    sample_json, t, content.messages, content.events
                )

    async def disconnect(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

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


@overload
def transcripts(logs: LogPaths) -> Transcripts: ...


@overload
def transcripts(logs: "pd.DataFrame") -> Transcripts: ...


def transcripts(logs: LogPaths | "pd.DataFrame") -> Transcripts:
    return EvalLogTranscripts(logs)


async def transcripts_from_snapshot(snapshot: ScanTranscripts) -> Transcripts:
    match snapshot.type:
        case "eval_log":
            return EvalLogTranscripts(snapshot)
        case _:
            raise ValueError(f"Unrecognized transcript type '{snapshot.type}")


TranscriptColumns: list[Column] = (
    EvalId
    + EvalLogPath
    + [
        EvalColumn("eval_created", path="eval.created", type=datetime, required=True),
        EvalColumn("eval_tags", path="eval.tags", default="", value=list_as_str),
        EvalColumn("eval_metadata", path="eval.metadata", default={}),
        EvalColumn(
            "task_name", path="eval.task", required=True, value=remove_namespace
        ),
        EvalColumn("task_args", path="eval.task_args", default={}),
        EvalColumn("solver", path="eval.solver"),
        EvalColumn("solver_args", path="eval.solver_args", default={}),
        EvalColumn("model", path="eval.model", required=True),
        EvalColumn("generate_config", path="eval.model_generate_config"),
        EvalColumn("model_roles", path="eval.model_roles", default={}),
        SampleColumn("id", path="id", required=True, type=str),
        SampleColumn("epoch", path="epoch", required=True),
        SampleColumn("sample_metadata", path="metadata", default={}),
        SampleColumn("score", path="scores", value=score_value),
        SampleColumn("score_*", path="scores", value=score_values),
        SampleColumn("total_tokens", path=sample_total_tokens),
        SampleColumn("total_time", path="total_time"),
        SampleColumn("working_time", path="total_time"),
        SampleColumn("error", path="error", default=""),
        SampleColumn("limit", path="limit", default=""),
    ]
)
