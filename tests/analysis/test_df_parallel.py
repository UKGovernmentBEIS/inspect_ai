from pathlib import Path

from inspect_ai.analysis.beta import (
    events_df,
    messages_df,
    samples_df,
)
from inspect_ai.analysis.beta._dataframe.samples.columns import (
    SampleMessages,
    SampleSummary,
)
from inspect_ai.analysis.beta._dataframe.samples.table import SAMPLE_ID

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
