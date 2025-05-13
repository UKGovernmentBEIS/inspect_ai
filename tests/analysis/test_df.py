from pathlib import Path

from inspect_ai.analysis.beta import (
    EvalInfo,
    EvalModel,
    EvalResults,
    EventInfo,
    EventTiming,
    MessageColumns,
    SampleSummary,
    evals_df,
    events_df,
    messages_df,
    samples_df,
)

LOGS_DIR = Path(__file__).parent / "logs"


def test_evals_df():
    df = evals_df(LOGS_DIR)
    assert len(df) == 3


def test_evals_df_columns():
    df = evals_df(LOGS_DIR, columns=EvalInfo + EvalModel + EvalResults)
    assert len(df.columns) == 1 + len(EvalInfo) + len(EvalModel) + len(EvalResults)
    assert "eval_id" in df.columns


def test_samples_df():
    df = samples_df(LOGS_DIR)
    assert len(df) == 7


def test_samples_df_columns():
    df = samples_df(LOGS_DIR, columns=SampleSummary)
    assert len(df.columns) == 1 + 1 + len(SampleSummary) + 2
    assert "eval_id" in df.columns
    assert "sample_id" in df.columns


def test_messages_df():
    df = messages_df(LOGS_DIR)
    assert len(df) == 34


def test_messages_df_columns():
    df = messages_df(LOGS_DIR, columns=EvalModel + MessageColumns)
    assert len(df.columns) == 1 + 1 + 1 + len(EvalModel) + len(MessageColumns)
    assert "eval_id" in df.columns
    assert "sample_id" in df.columns
    assert "message_id" in df.columns


def test_events_df():
    df = events_df(LOGS_DIR)
    assert len(df) == 124


def test_events_df_columns():
    df = events_df(LOGS_DIR, columns=EvalModel + EventInfo + EventTiming)
    assert len(df.columns) == 1 + 1 + 1 + len(EvalModel) + len(EventInfo) + len(
        EventTiming
    )
    assert "eval_id" in df.columns
    assert "sample_id" in df.columns
    assert "event_id" in df.columns
