from pathlib import Path

from inspect_ai.analysis import SampleColumn, samples_df
from inspect_ai.analysis._dataframe.samples.columns import SampleScores

LOGS_DIR = Path(__file__).parent / "test_logs"
JSON_LOG = LOGS_DIR / "2025-05-12T20-28-13-04-00_popularity.json"
EVAL_LOG = Path(__file__).parent / "test_logs_choices" / "mmlu-summary-choices.eval"


def test_samples_df_json_exclude_fields_no_error():
    """Smoke test: exclude_fields threads through without error.

    Uses a .json fixture where exclude_fields is a no-op at the recorder
    level — this verifies the parameter plumbing, not field exclusion.
    """
    df = samples_df(
        JSON_LOG,
        columns=SampleScores,
        exclude_fields={"messages", "events", "store", "attachments"},
    )
    assert len(df) > 0
    score_cols = [c for c in df.columns if c.startswith("score_")]
    assert len(score_cols) > 0


def test_samples_df_eval_exclude_fields():
    columns = SampleScores + [
        SampleColumn("num_messages", path=lambda s: len(s.messages), full=True)
    ]
    df = samples_df(
        EVAL_LOG,
        columns=columns,
        exclude_fields={"messages", "events", "store", "attachments"},
    )
    assert len(df) == 1
    score_cols = [c for c in df.columns if c.startswith("score_")]
    assert len(score_cols) > 0
    assert df["score_choice"].iloc[0] == "I"
    # excluded: messages were skipped during the read, so none are extracted
    assert df["num_messages"].iloc[0] == 0
