import tempfile
from pathlib import Path

import pandas as pd
import pytest
from pydantic import JsonValue

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai.analysis import (
    EvalInfo,
    EvalModel,
    EvalResults,
    EventInfo,
    EventTiming,
    MessageColumns,
    ModelEventColumns,
    SampleSummary,
    evals_df,
    events_df,
    messages_df,
    samples_df,
)
from inspect_ai.analysis._dataframe.evals.columns import EvalTask
from inspect_ai.analysis._dataframe.extract import score_details
from inspect_ai.analysis._dataframe.samples.columns import SampleScores
from inspect_ai.analysis._dataframe.util import resolve_logs
from inspect_ai.dataset import Sample
from inspect_ai.log import (
    EvalLog,
    MetadataEdit,
    ProvenanceData,
    TagsEdit,
    edit_eval_log,
    list_eval_logs,
    read_eval_log,
    write_eval_log,
)
from inspect_ai.model import get_model
from inspect_ai.model._model import requested_model
from inspect_ai.solver import Generate, TaskState, solver

LOGS_DIR = Path(__file__).parent / "test_logs"
SECURITY_GUIDE_LOG = LOGS_DIR / "2025-05-12T20-28-26-04-00_security-guide.json"


def test_evals_df():
    df = evals_df(LOGS_DIR)
    assert len(df) == 4


def test_evals_df_scores_with_reducers():
    """Ensure per-reducer score metrics get distinct columns.

    When the same scorer appears with multiple reducers (e.g. epochs with
    epochs_reducer=["mean","max"]), each reducer's metrics must get distinct
    columns rather than the last one silently overwriting the first.
    """
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalMetric,
        EvalResults,
        EvalScore,
        EvalSpec,
    )

    log = EvalLog(
        status="success",
        eval=EvalSpec(
            created="2024-01-01T00:00:00+00:00",
            task="t",
            dataset=EvalDataset(),
            model="test/model",
            config=EvalConfig(epochs=4, epochs_reducer=["mean", "max"]),
        ),
        results=EvalResults(
            scores=[
                EvalScore(
                    name="match",
                    scorer="match",
                    reducer="mean",
                    metrics={"accuracy": EvalMetric(name="accuracy", value=0.50)},
                ),
                EvalScore(
                    name="match",
                    scorer="match",
                    reducer="max",
                    metrics={"accuracy": EvalMetric(name="accuracy", value=0.90)},
                ),
            ]
        ),
    )

    df = evals_df([log], quiet=True)
    assert "score_match_mean_accuracy" in df.columns
    assert "score_match_max_accuracy" in df.columns
    assert df.iloc[0]["score_match_mean_accuracy"] == 0.50
    assert df.iloc[0]["score_match_max_accuracy"] == 0.90


def test_evals_df_single_reducer_preserves_column_name():
    """A single explicit reducer must NOT rename score columns.

    Disambiguation only kicks in when multiple scores share a name; logs with
    a single reducer keep `score_<name>_<metric>` so existing data frames are
    not silently broken.
    """
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalMetric,
        EvalResults,
        EvalScore,
        EvalSpec,
    )

    log = EvalLog(
        status="success",
        eval=EvalSpec(
            created="2024-01-01T00:00:00+00:00",
            task="t",
            dataset=EvalDataset(),
            model="test/model",
            config=EvalConfig(epochs=4, epochs_reducer=["mean"]),
        ),
        results=EvalResults(
            scores=[
                EvalScore(
                    name="match",
                    scorer="match",
                    reducer="mean",
                    metrics={"accuracy": EvalMetric(name="accuracy", value=0.75)},
                ),
            ]
        ),
    )

    df = evals_df([log], quiet=True)
    assert "score_match_accuracy" in df.columns
    assert "score_match_mean_accuracy" not in df.columns
    assert df.iloc[0]["score_match_accuracy"] == 0.75


def test_evals_df_scores_with_mixed_score_views():
    """Mixed score views keep legacy columns when metric keys don't collide."""
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalMetric,
        EvalResults,
        EvalScore,
        EvalSpec,
    )

    log = EvalLog(
        status="success",
        eval=EvalSpec(
            created="2024-01-01T00:00:00+00:00",
            task="t",
            dataset=EvalDataset(),
            model="test/model",
            config=EvalConfig(epochs=2),
        ),
        results=EvalResults(
            scores=[
                EvalScore(
                    name="match",
                    scorer="match",
                    reducer="mean",
                    metrics={"accuracy": EvalMetric(name="accuracy", value=0.50)},
                ),
                EvalScore(
                    name="match",
                    scorer="match",
                    reducer=None,
                    metrics={"C": EvalMetric(name="C", value=0.50)},
                ),
            ]
        ),
    )

    df = evals_df([log], quiet=True)
    assert "score_match_accuracy" in df.columns
    assert "score_match_mean_accuracy" not in df.columns
    assert "score_match_C" in df.columns
    assert df.iloc[0]["score_match_accuracy"] == 0.50
    assert df.iloc[0]["score_match_C"] == 0.50


def test_evals_df_scores_with_mixed_score_view_metric_collision():
    """Reducer suffixes are still used when metric columns would collide."""
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalMetric,
        EvalResults,
        EvalScore,
        EvalSpec,
    )

    log = EvalLog(
        status="success",
        eval=EvalSpec(
            created="2024-01-01T00:00:00+00:00",
            task="t",
            dataset=EvalDataset(),
            model="test/model",
            config=EvalConfig(epochs=2),
        ),
        results=EvalResults(
            scores=[
                EvalScore(
                    name="match",
                    scorer="match",
                    reducer="mean",
                    metrics={"accuracy": EvalMetric(name="accuracy", value=0.50)},
                ),
                EvalScore(
                    name="match",
                    scorer="match",
                    reducer=None,
                    metrics={"accuracy": EvalMetric(name="accuracy", value=0.75)},
                ),
            ]
        ),
    )

    df = evals_df([log], quiet=True)
    assert "score_match_mean_accuracy" in df.columns
    assert "score_match_accuracy" in df.columns
    assert df.iloc[0]["score_match_mean_accuracy"] == 0.50
    assert df.iloc[0]["score_match_accuracy"] == 0.75


def test_evals_df_headline_metric_uses_metric_key():
    """Headline metric names should stay stable for expanded metric outputs."""
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalMetric,
        EvalResults,
        EvalScore,
        EvalSpec,
    )

    log = EvalLog(
        status="success",
        eval=EvalSpec(
            created="2024-01-01T00:00:00+00:00",
            task="t",
            dataset=EvalDataset(),
            model="test/model",
            config=EvalConfig(),
        ),
        results=EvalResults(
            scores=[
                EvalScore(
                    name="one",
                    scorer="dict_scorer",
                    metrics={
                        "nested_dict_metric_key1": EvalMetric(
                            name="key1",
                            group="nested_dict_metric",
                            value=0.25,
                        ),
                        "nested_dict_metric_key2": EvalMetric(
                            name="key2",
                            group="nested_dict_metric",
                            value=0.75,
                        ),
                    },
                ),
            ]
        ),
    )

    df = evals_df([log], quiet=True)
    assert df.iloc[0]["score_headline_metric"] == "nested_dict_metric_key1"
    assert df.iloc[0]["score_headline_value"] == 0.25
    assert df.iloc[0]["score_one_nested_dict_metric_key1"] == 0.25


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
    assert "eval_id" in df.columns
    assert "sample_id" in df.columns
    assert "log" in df.columns


def test_samples_df_includes_turn_and_token_limit_usage_columns():
    df = samples_df(LOGS_DIR, columns=SampleSummary)
    assert "turn_count" in df.columns
    assert "token_limit_usage" in df.columns


def test_evals_df_includes_token_limit_type_column():
    from inspect_ai.analysis._dataframe.evals.columns import EvalConfiguration

    df = evals_df(LOGS_DIR, columns=EvalConfiguration)
    assert "token_limit" in df.columns
    assert "token_limit_type" in df.columns


def test_evals_df_sentinel_column(tmp_path: Path) -> None:
    from inspect_ai.log import SentinelConfig

    [plain] = eval(Task(), model="mockllm/model", log_dir=str(tmp_path / "plain"))
    with_sentinel = plain.model_copy(deep=True)
    with_sentinel.eval.config.sentinel = SentinelConfig.model_validate(
        [{"name": "d4_rule", "params": {"reason": "no"}}]
    )
    write_eval_log(with_sentinel, str(tmp_path / "sentinel" / "log.eval"))

    df = evals_df(tmp_path / "sentinel")
    assert "d4_rule" in df["sentinel"].iloc[0]
    df = evals_df(tmp_path / "plain")
    assert "sentinel" in df.columns
    assert df["sentinel"].isna().all()


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


def test_events_df_model_event_requested_model(tmp_path: Path):
    @solver
    def bridged_then_direct():
        async def solve(state: TaskState, generate: Generate):
            model = get_model()
            with requested_model("gpt-4o-mini"):
                await model.generate("bridged")
            await model.generate("direct")
            return state

        return solve

    task = Task(dataset=[Sample(input="Say hello.")], solver=bridged_then_direct())
    log = eval(task, model="mockllm/model", log_dir=str(tmp_path))[0]

    df = events_df(
        log,
        columns=EventInfo + ModelEventColumns,
        filter=lambda e: e.event == "model",
    )
    assert df["model_event_model"].tolist() == ["mockllm/model", "mockllm/model"]
    requested = df["model_event_requested_model"]
    assert requested.iloc[0] == "gpt-4o-mini"
    assert pd.isna(requested.iloc[1])

    # logs written before the field have no value
    old = events_df(
        LOGS_DIR, columns=ModelEventColumns, filter=lambda e: e.event == "model"
    )
    assert len(old) > 0
    assert old["model_event_requested_model"].isna().all()


def test_eval_df_display_name():
    with tempfile.TemporaryDirectory() as log_dir:
        eval(Task(display_name="My Task"), model="mockllm/model", log_dir=log_dir)
        df = evals_df(log_dir)
        assert df["task_display_name"].to_list() == ["My Task"]
        eval(Task(name="my_task"), model="mockllm/model", log_dir=log_dir)
        df = evals_df(log_dir)
        assert df["task_display_name"].to_list().sort() == ["My Task", "my_task"].sort()


def test_df_description_columns():
    with tempfile.TemporaryDirectory() as log_dir:
        eval(
            Task(
                dataset=[
                    Sample(id=1, input="x", description="Say x."),
                    Sample(id=2, input="y"),
                ],
                description="Say the input.",
            ),
            model="mockllm/model",
            log_dir=log_dir,
        )
        assert evals_df(log_dir)["task_description"].to_list() == ["Say the input."]
        for full in [False, True]:
            df = samples_df(log_dir, full=full).sort_values("id")
            descriptions = df["description"].to_list()
            assert descriptions[0] == "Say x."
            assert pd.isna(descriptions[1])

    # logs written before descriptions existed read as missing
    assert evals_df(LOGS_DIR)["task_description"].isna().all()
    assert samples_df(LOGS_DIR)["description"].isna().all()


def test_samples_df_with_sample_scores():
    """Test that SampleSummary + SampleScores combination works correctly."""
    df = samples_df(LOGS_DIR, columns=SampleSummary + SampleScores)

    assert "eval_id" in df.columns
    assert "sample_id" in df.columns
    assert "input" in df.columns
    assert "target" in df.columns

    # Check that score columns are present
    score_columns = [col for col in df.columns if col.startswith("score_")]
    assert len(score_columns) > 0


def test_samples_df_message_count():
    """Test that message_count column is available in samples dataframe."""
    df = samples_df(LOGS_DIR, columns=SampleSummary)

    assert "message_count" in df.columns
    assert all(pd.isna(df["message_count"]) | (df["message_count"] >= 0))
    assert any(df["message_count"] > 0)


def test_samples_df_eval_log():
    log = read_eval_log(str(SECURITY_GUIDE_LOG))
    df = samples_df(log)
    assert len(df) == 3


def test_samples_df_multiple_eval_logs():
    logs = list_eval_logs(str(LOGS_DIR))
    logs = [read_eval_log(log) for log in logs]
    df = samples_df(logs)
    assert len(df) == 7


def test_evals_df_eval_log():
    log = read_eval_log(str(SECURITY_GUIDE_LOG))
    df = evals_df(log)
    assert len(df) == 1


def test_evals_df_multiple_eval_logs():
    logs = list_eval_logs(str(LOGS_DIR))
    logs = [read_eval_log(log) for log in logs]
    df = evals_df(logs)
    assert len(df) == 4


def test_messages_df_eval_log():
    log = read_eval_log(str(SECURITY_GUIDE_LOG))
    df = messages_df(log)
    assert len(df) == 15


def test_messages_df_multiple_eval_logs():
    logs = list_eval_logs(str(LOGS_DIR))
    logs = [read_eval_log(log) for log in logs]
    df = messages_df(logs)
    assert len(df) == 34


def test_events_df_eval_log():
    log = read_eval_log(str(SECURITY_GUIDE_LOG))
    df = events_df(log)
    assert len(df) == 42


def test_events_df_multiple_eval_logs():
    logs = list_eval_logs(str(LOGS_DIR))
    logs = [read_eval_log(log) for log in logs]
    df = events_df(logs)
    assert len(df) == 124


def test_evals_df_reflects_edited_tags_and_metadata(tmp_path: Path):
    log_dir = str(tmp_path)
    eval(
        Task(tags=["original"], metadata={"key": "original"}),
        model="mockllm/model",
        log_dir=log_dir,
    )
    log_info = list_eval_logs(log_dir)[0]
    log = read_eval_log(log_info)
    log = edit_eval_log(
        log,
        [
            TagsEdit(tags_add=["added"], tags_remove=["original"]),
            MetadataEdit(metadata_set={"key": "edited"}),
        ],
        ProvenanceData(author="test"),
    )
    write_eval_log(log, log.location)

    df = evals_df(log_dir)
    assert df["tags"].to_list() == ["added"]
    assert df["metadata"].to_list() == ['{"key": "edited"}']


def test_score_details_includes_reason() -> None:
    scores: JsonValue = {
        "match": {
            "value": "I",
            "answer": "foo",
            "reason": "invalid_response_format",
        },
        "other": {"value": "C"},
    }
    details = score_details(scores)
    assert details["match"] == "I"
    assert details["match_reason"] == "invalid_response_format"
    assert details["match_answer"] == "foo"
    # None-safety: absent reason produces no column entry
    assert "other_reason" not in details


def test_dataframe_functions_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    log_dir = str(tmp_path)
    eval(
        Task(),
        model="mockllm/model",
        log_dir=log_dir,
    )
    monkeypatch.setenv("INSPECT_LOG_DIR", log_dir)
    assert len(list_eval_logs()) > 0

    assert resolve_logs([]) == []
    assert resolve_logs(()) == []
    assert len(evals_df([])) == 0
    assert len(samples_df([])) == 0
    assert len(messages_df([])) == 0
    assert len(events_df([])) == 0
