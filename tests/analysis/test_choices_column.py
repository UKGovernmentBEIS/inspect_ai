from pathlib import Path

from inspect_ai.analysis._dataframe.samples.columns import (
    SampleColumn,
    SampleSummary,
)
from inspect_ai.analysis._dataframe.samples.table import samples_df

LOGS_DIR = Path(__file__).parent / "test_logs_choices"
OLD_LOG = LOGS_DIR / "mmlu-no-summary-choices.eval"
NEW_LOG = LOGS_DIR / "mmlu-summary-choices.eval"


def test_choices_auto_detect_reads_full_sample():
    """Auto-detect for choices path should use full=True and read from full sample."""
    # SampleColumn without explicit full should auto-detect full=True for "choices"
    columns = [
        SampleColumn("id", path="id", required=True, type=str),
        SampleColumn("choices", path="choices"),  # No explicit full
    ]

    # Both old and new logs should have choices (read from full sample)
    df_old = samples_df(OLD_LOG, columns=columns)
    df_new = samples_df(NEW_LOG, columns=columns)

    assert "choices" in df_old.columns
    assert "choices" in df_new.columns
    # Full sample read should return choices for both
    assert df_old["choices"].notna().any()
    assert df_new["choices"].notna().any()


def test_choices_in_sample_summary_new_log():
    """SampleSummary (full=False for choices) should read choices from new logs."""
    df = samples_df(NEW_LOG, columns=SampleSummary)

    assert "choices" in df.columns
    # New logs have choices in summary
    assert df["choices"].notna().any()


def test_choices_in_sample_summary_old_log():
    """SampleSummary (full=False for choices) returns None for old logs without summary choices."""
    df = samples_df(OLD_LOG, columns=SampleSummary)

    assert "choices" in df.columns
    # Old logs don't have choices in summary, should be None
    assert df["choices"].isna().all()


def test_choices_explicit_full_true():
    """Explicit full=True should read choices from full sample for both log types."""
    columns = [
        SampleColumn("id", path="id", required=True, type=str),
        SampleColumn("choices", path="choices", full=True),
    ]

    df_old = samples_df(OLD_LOG, columns=columns)
    df_new = samples_df(NEW_LOG, columns=columns)

    assert "choices" in df_old.columns
    assert "choices" in df_new.columns
    # Full sample read should return choices for both
    assert df_old["choices"].notna().any()
    assert df_new["choices"].notna().any()


def test_choices_explicit_full_false_new_log():
    """Explicit full=False should read choices from summary (works for new logs)."""
    columns = [
        SampleColumn("id", path="id", required=True, type=str),
        SampleColumn("choices", path="choices", full=False),
    ]

    df = samples_df(NEW_LOG, columns=columns)

    assert "choices" in df.columns
    assert df["choices"].notna().any()


def test_choices_explicit_full_false_old_log():
    """Explicit full=False should read from summary (None for old logs)."""
    columns = [
        SampleColumn("id", path="id", required=True, type=str),
        SampleColumn("choices", path="choices", full=False),
    ]

    df = samples_df(OLD_LOG, columns=columns)

    assert "choices" in df.columns
    # Old logs don't have choices in summary
    assert df["choices"].isna().all()
