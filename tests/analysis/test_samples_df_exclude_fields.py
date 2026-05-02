from pathlib import Path

from inspect_ai.analysis import samples_df
from inspect_ai.analysis._dataframe.samples.columns import SampleScores

LOGS_DIR = Path(__file__).parent / "test_logs"
POPULARITY_LOG = LOGS_DIR / "2025-05-12T20-28-13-04-00_popularity.json"


def test_samples_df_exclude_fields_no_error():
    """Smoke test: exclude_fields threads through without error.

    Uses a .json fixture where exclude_fields is a no-op at the recorder
    level — this verifies the parameter plumbing, not field exclusion.
    """
    df = samples_df(
        POPULARITY_LOG,
        columns=SampleScores,
        exclude_fields={"messages", "events", "store", "attachments"},
    )
    assert len(df) > 0
    score_cols = [c for c in df.columns if c.startswith("score_")]
    assert len(score_cols) > 0
