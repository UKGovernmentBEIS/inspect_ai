from pathlib import Path

from inspect_ai.analysis._dataframe.samples.columns import (
    SampleColumn,
    SampleSummary,
)
from inspect_ai.analysis._dataframe.samples.table import samples_df

LOGS_DIR = Path(__file__).parent / "test_logs"

POPULARITY_LOG = LOGS_DIR / "2025-05-12T20-28-13-04-00_popularity.json"


def test_sample_not_full():
    df = samples_df(POPULARITY_LOG)
    assert "metadata_label_confidence" in df.columns
    assert "metadata_nested" not in df.columns


def test_sample_metadata_full():
    df = samples_df(
        POPULARITY_LOG,
        columns=SampleSummary
        + [SampleColumn("metadata_*", path="metadata", full=True)],
    )
    assert "metadata_label_confidence" in df.columns
    assert "metadata_nested" in df.columns


def test_sample_param_full():
    df = samples_df(POPULARITY_LOG, columns=SampleSummary, full=True)
    assert "metadata_label_confidence" in df.columns
    assert "metadata_nested" in df.columns
