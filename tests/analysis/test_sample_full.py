from pathlib import Path

from inspect_ai._util.version import has_required_version
from inspect_ai.analysis._dataframe.columns import parse
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
    assert "metadata_nested" in df.columns


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


def test_sample_full_inferred_from_path() -> None:
    assert SampleColumn("completion", path="output.completion")._full
    assert not SampleColumn("id", path="id")._full
    assert not SampleColumn("id", path=parse("id"))._full
    # jsonpath-ng < 1.9 renders parsed paths with parentheses, so the
    # full-sample prefix match misses them
    assert SampleColumn(
        "completion", path=parse("output.completion")
    )._full == has_required_version("jsonpath-ng", "1.9.0")
