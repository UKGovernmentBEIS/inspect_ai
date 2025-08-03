import tempfile
from pathlib import Path

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai.analysis import (
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
from inspect_ai.analysis._dataframe.evals.columns import EvalTask
from inspect_ai.log import EvalLog, list_eval_logs

LOGS_DIR = Path(__file__).parent / "test_logs"


def test_evals_df():
    df = evals_df(LOGS_DIR)
    assert len(df) == 4


def test_evals_df_columns():
    df = evals_df(LOGS_DIR, columns=EvalInfo + EvalModel + EvalResults + EvalTask)
    assert (
        len(df.columns)
        == 1 + len(EvalInfo) + len(EvalModel) + len(EvalResults) + len(EvalTask) - 1
    )
    assert "eval_id" in df.columns
    assert "task_display_name" in df.columns


def test_evals_df_strict():
    df, errors = evals_df(LOGS_DIR, strict=False)
    assert len(df) == 4
    assert len(errors) == 0


def test_evals_df_filter():
    logs = list_eval_logs(
        LOGS_DIR.as_posix(), filter=lambda log: log.status == "success"
    )
    df = evals_df(logs)
    assert len(df) == 2

    def task_filter(log: EvalLog) -> bool:
        return log.eval.task == "popularity"

    logs = list_eval_logs(LOGS_DIR.as_posix(), filter=task_filter)
    df = evals_df(logs)
    assert len(df) == 1


def test_samples_df():
    df = samples_df(LOGS_DIR)
    assert len(df) == 7


def test_samples_df_columns():
    df = samples_df(LOGS_DIR, columns=SampleSummary)
    assert len(df.columns) == 1 + 1 + len(SampleSummary) + 1 + 1 + 1
    assert "eval_id" in df.columns
    assert "sample_id" in df.columns
    assert "log" in df.columns


def test_messages_df():
    df = messages_df(LOGS_DIR)
    assert len(df) == 34


def test_messages_df_columns():
    df = messages_df(LOGS_DIR, columns=EvalModel + MessageColumns)
    assert len(df.columns) == 1 + 1 + 1 + 1 + len(EvalModel) + len(MessageColumns)
    assert "eval_id" in df.columns
    assert "sample_id" in df.columns
    assert "message_id" in df.columns
    assert "log" in df.columns


def test_messages_df_filter():
    df = messages_df(LOGS_DIR, filter=lambda m: m.role == "assistant")
    assert len(df) == 14


def test_events_df():
    df = events_df(LOGS_DIR)
    assert len(df) == 124


def test_events_df_columns():
    df = events_df(LOGS_DIR, columns=EvalModel + EventInfo + EventTiming)
    assert len(df.columns) == 1 + 1 + 1 + 1 + len(EvalModel) + len(EventInfo) + len(
        EventTiming
    )
    assert "eval_id" in df.columns
    assert "sample_id" in df.columns
    assert "event_id" in df.columns
    assert "log" in df.columns


def test_events_df_filter():
    df = events_df(LOGS_DIR, filter=lambda e: e.event == "tool")
    assert len(df) == 4


def test_eval_df_display_name():
    with tempfile.TemporaryDirectory() as log_dir:
        eval(Task(display_name="My Task"), model="mockllm/model", log_dir=log_dir)
        df = evals_df(log_dir)
        assert df["task_display_name"].to_list() == ["My Task"]
        eval(Task(name="my_task"), model="mockllm/model", log_dir=log_dir)
        df = evals_df(log_dir)
        assert df["task_display_name"].to_list().sort() == ["My Task", "my_task"].sort()
