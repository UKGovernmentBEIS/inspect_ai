from pathlib import Path

import pandas as pd
import pyarrow as pa
from pydantic import JsonValue

from inspect_ai import Task, eval
from inspect_ai.analysis import (
    SampleColumn,
    events_df,
    messages_df,
    samples_df,
)
from inspect_ai.analysis._dataframe.samples.columns import (
    SampleMessages,
    SampleSummary,
)
from inspect_ai.analysis._dataframe.samples.table import SAMPLE_ID
from inspect_ai.dataset import Sample

LOGS_DIR = Path(__file__).parent / "test_logs"

EVENT_ID = "event_id"
MESSAGE_ID = "message_id"


def test_samples_df_parallel() -> None:
    dfs = samples_df(LOGS_DIR)
    dfs_parallel = samples_df(LOGS_DIR, parallel=2)
    assert dfs[SAMPLE_ID].to_list() == dfs_parallel[SAMPLE_ID].to_list()


def test_samples_df_messages_parallel() -> None:
    columns = SampleSummary + SampleMessages
    dfs = samples_df(LOGS_DIR, columns=columns)
    dfs_parallel = samples_df(LOGS_DIR, columns=columns, parallel=2)
    assert dfs[SAMPLE_ID].to_list() == dfs_parallel[SAMPLE_ID].to_list()


def test_events_df_parallel() -> None:
    dfs = events_df(LOGS_DIR)
    dfs_parallel = events_df(LOGS_DIR, parallel=2)
    assert dfs[EVENT_ID].to_list() == dfs_parallel[EVENT_ID].to_list()


def test_messages_df_parallel() -> None:
    dfs = messages_df(LOGS_DIR)
    dfs_parallel = messages_df(LOGS_DIR, parallel=2)
    assert dfs[MESSAGE_ID].to_list() == dfs_parallel[MESSAGE_ID].to_list()


def test_samples_df_parallel_reconciles_string_columns(tmp_path: Path) -> None:
    """A column read as strings from one log is strings for every log."""
    logs: list[list[dict[str, JsonValue]]] = [
        [{"big": 1, "mixed": "C"}],
        [{}, {"big": 2**63 + 1, "mixed": 0.5, "note": "x"}],
    ]
    for metadata in logs:
        eval(
            Task(dataset=[Sample(input="hi", metadata=m) for m in metadata]),
            model="mockllm/model",
            log_dir=str(tmp_path),
            display="none",
        )
    columns = SampleSummary + [
        SampleColumn("big", path="metadata.big"),
        SampleColumn("note", path="metadata.note"),
    ]

    def read(parallel: bool | int) -> pd.DataFrame:
        df = samples_df(tmp_path, columns=columns, parallel=parallel)
        return df.sort_values(SAMPLE_ID, ignore_index=True)

    serial, parallel = read(False), read(2)
    for column in ["big", "note", "metadata_big", "metadata_mixed"]:
        pd.testing.assert_series_equal(parallel[column], serial[column])
    assert sorted(parallel["big"].dropna()) == ["1", str(2**63 + 1)]
    assert sorted(serial["metadata_mixed"].dropna()) == ["0.5", "C"]
    pa.Table.from_pandas(parallel)
