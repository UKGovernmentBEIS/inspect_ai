from pathlib import Path
from typing import Any

from inspect_ai.analysis import (
    evals_df,
    frontier,
    log_viewer,
    model_info,
    prepare,
    task_info,
)
from inspect_ai.analysis._dataframe.samples.table import samples_df
from inspect_ai.analysis._prepare.score_to_float import score_to_float

LOGS_DIR = Path(__file__).parent / "test_logs"


def test_task_info():
    df = evals_df(LOGS_DIR / "2025-05-12T20-27-36-04-00_browser.json")
    df = prepare(df, task_info({}))
    assert df["task_display_name"].to_list() == ["browser"]
    df = prepare(df, task_info({"browser": "Browser Task"}))
    assert df["task_display_name"].to_list() == ["Browser Task"]


def test_prepare_log_viewer():
    df = evals_df(LOGS_DIR)
    check_log_viewer(df, {LOGS_DIR.as_posix(): "https://logs.example.com"})
    check_log_viewer(df, {LOGS_DIR.as_posix(): "https://logs.example.com/"})
    check_log_viewer(df, {f"{LOGS_DIR.as_posix()}/": "https://logs.example.com"})
    check_log_viewer(
        df,
        {f"{LOGS_DIR.parent.as_posix()}/": "https://logs.example.com"},
        "/test_logs/",
    )
    check_log_viewer(df, {"tests/analysis": "https://logs.example.com"}, "/test_logs/")


def test_score_to_float():
    df = samples_df(LOGS_DIR / "2025-05-12T20-27-36-04-00_browser.json")
    df = prepare(df, score_to_float(["score_includes"]))
    assert df["score_includes"].dtype == "float64"
    assert df["score_includes"].isnull().sum() == 0
    assert df["score_includes"].unique().tolist() == [1]


def test_score_to_float_with_na():
    """Ensure score_to_float handles pd.NA in pyarrow-backed columns.

    When loading multiple logs with different scorers, score columns are
    pyarrow-backed with pd.NA for samples scored by other scorers. score_to_float
    must handle these NA values rather than crashing on bool(pd.NA).
    """
    import math

    import pandas as pd

    df = samples_df(LOGS_DIR)
    # precondition: multi-scorer fixture produces NA values
    assert df["score_match"].isna().any()

    out = prepare(df, score_to_float("score_match"))

    # NA inputs map to NaN, real values convert to float
    for original, converted in zip(df["score_match"], out["score_match"]):
        if pd.isna(original):
            assert math.isnan(converted)
        else:
            assert isinstance(converted, float) and not math.isnan(converted)


def test_frontier_all_na_scores_in_date_group():
    """frontier() must not crash when a release-date group has only NA scores.

    When logs from multiple models are combined, a model_release_date group can
    contain only missing headline scores (e.g. a model that wasn't run on the
    task). Grouping by date and calling idxmax() over such an all-NA group
    raises (pandas >= 3) or returns NaN (pandas < 3, breaking the subsequent
    .loc), so rows with a missing score must be dropped before grouping.
    """
    import pandas as pd

    nan = float("nan")
    df = pd.DataFrame(
        {
            "task_name": ["t", "t", "t", "t"],
            "model_release_date": [
                "2024-01-01",
                "2024-01-01",
                "2024-02-01",
                "2024-03-01",
            ],
            "score_headline_value": [nan, nan, 0.5, 0.7],
        }
    )

    out = prepare(df, frontier())

    # the all-NA-score date group (2024-01-01) is skipped; the later scored
    # models are each an improvement, so both are on the frontier
    assert list(out["frontier"]) == [False, False, True, True]


def test_model_info():
    import pandas as pd
    import pytest

    # empty DataFrame should return empty DataFrame without error
    df_empty = pd.DataFrame()
    out_empty = prepare(df_empty, model_info())
    assert out_empty.empty

    # missing 'model' column should raise ValueError
    df_no_model = pd.DataFrame({"task_name": ["t1"]})
    with pytest.raises(ValueError, match="Required column 'model' not found"):
        prepare(df_no_model, model_info())

    # normal operation with valid model column (built-in model vs custom model)
    df = pd.DataFrame({"model": ["openai/gpt-4o", "unknown_model"]})
    out = prepare(df, model_info())
    assert "model_display_name" in out.columns
    assert out["model_display_name"].to_list() == ["GPT-4o", "unknown_model"]


def check_log_viewer(
    df: Any, url_mappings: dict[str, str], includes: str | None = None
):
    df = prepare(df, log_viewer("eval", url_mappings))
    urls = df["log_viewer"].to_list()

    # are all urls
    all(url.startswith("https://") for url in urls)

    # only one double-slash
    assert all(url.count("//") == 1 for url in urls)

    # all log files represented
    log_files = LOGS_DIR.glob("*")
    for log_file in log_files:
        assert any(log_file.name in url for url in urls)

    # check optional includes
    if includes:
        assert all(includes in url for url in urls)
