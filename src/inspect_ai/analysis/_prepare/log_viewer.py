import os
from typing import Literal

from inspect_ai._util.file import absolute_file_path
from inspect_ai.analysis._prepare.operation import Operation


def log_viewer(
    target: Literal["eval", "sample", "event", "message"],
    url_mappings: dict[str, str],
    log_column: str = "log",
    log_viewer_column: str = "log_viewer",
) -> Operation:
    """Add a log viewer column to an eval data frame.

    Tranform operation to add a log_viewer column to a data frame based on one more more `url_mappings`.

    URL mappings define the relationship between log file paths (either fileystem or S3) and URLs where logs are published. The URL target should be the location where the output of the [`inspect view bundle`](../log-viewer.qmd#sec-publishing) command was published.

    Args:
        target: Target for log viewer ("eval", "sample", "event", or "message").
        url_mappings: Map log file paths (either filesystem or S3) to URLs where logs are published.
        log_column: Column in the data frame containing log file path (defaults to "log").
        log_viewer_column: Column to create with log viewer URL (defaults to "log_viewer")
    """
    import pandas as pd

    # normalize mappings
    url_mappings = {
        _normalize_log_dir(k): _ensure_trailing_slash(v)
        for k, v in url_mappings.items()
    }

    def resolve_base_url(
        row: pd.Series,  # type: ignore[type-arg]
        log_column: str,
        url_mappings: dict[str, str],
    ) -> str:
        """Resolve base URL from log path using URL mappings."""
        log = _normalize_file_path(row[log_column])
        for k, v in url_mappings.items():
            if log.startswith(k):
                return log.replace(k, f"{v}#/logs/", 1)

        raise ValueError(
            f"Unable to resolve log viewer URL for log {row[log_column]} "
            + "(no valid url mapping provided for log)"
        )

    def validate_required_columns(row: pd.Series, required_columns: list[str]) -> None:  # type: ignore[type-arg]
        """Validate that row contains all required columns."""
        missing = [col for col in required_columns if col not in row]
        if missing:
            raise ValueError(
                f"Row must contain {', '.join(repr(col) for col in required_columns)} "
                f"columns to generate {target} log viewer URL"
            )

    # function to resolve mappings
    def log_viewer_url(row: pd.Series) -> str:  # type: ignore[type-arg]
        return resolve_base_url(row, log_column, url_mappings)

    def sample_log_viewer_url(row: pd.Series) -> str:  # type: ignore[type-arg]
        # validate columns
        validate_required_columns(row, ["id", "epoch"])

        # form the url
        base_url = resolve_base_url(row, log_column, url_mappings)
        return f"{base_url}/samples/sample/{row.id}/{row.epoch}"

    def sample_event_log_viewer_url(row: pd.Series) -> str:  # type: ignore[type-arg]
        ## validate columns
        validate_required_columns(row, ["sample_id", "event_id"])

        # form the url
        base_url = resolve_base_url(row, log_column, url_mappings)
        return f"{base_url}/samples/sample_uuid/{row.sample_id}/transcript?event={row.event_id}"

    def sample_message_log_viewer_url(row: pd.Series) -> str:  # type: ignore[type-arg]
        ## validate columns
        validate_required_columns(row, ["sample_id", "message_id"])

        # form the url
        base_url = resolve_base_url(row, log_column, url_mappings)
        return f"{base_url}/samples/sample_uuid/{row.sample_id}/messages?message={row.message_id}"

    def transform(df: pd.DataFrame) -> pd.DataFrame:
        if target == "sample":
            df[log_viewer_column] = df.apply(sample_log_viewer_url, axis=1)
        elif target == "event":
            df[log_viewer_column] = df.apply(sample_event_log_viewer_url, axis=1)
        elif target == "message":
            df[log_viewer_column] = df.apply(sample_message_log_viewer_url, axis=1)
        else:
            df[log_viewer_column] = df.apply(log_viewer_url, axis=1)
        return df

    return transform


def _normalize_file_path(file: str) -> str:
    file = os.path.expanduser(file)
    return absolute_file_path(file)


def _normalize_log_dir(dir: str) -> str:
    dir = _normalize_file_path(dir)
    return _ensure_trailing_slash(dir)


def _ensure_trailing_slash(dir: str) -> str:
    if not dir.endswith("/"):
        return f"{dir}/"
    else:
        return dir
