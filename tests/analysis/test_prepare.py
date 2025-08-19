from pathlib import Path
from typing import Any

from inspect_ai.analysis import evals_df, log_viewer, prepare, task_info
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
