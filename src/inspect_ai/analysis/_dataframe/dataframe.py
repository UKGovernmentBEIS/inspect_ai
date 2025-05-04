from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Sequence, TypeAlias, overload

from inspect_ai._display import display
from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.file import FileInfo, filesystem
from inspect_ai._util.path import pretty_path
from inspect_ai._util.version import verify_required_version
from inspect_ai.log._file import (
    log_files_from_ls,
    read_eval_log,
    read_eval_log_sample_summaries,
)

from .columns.columns import ColumnErrors, Columns, ColumnType
from .columns.eval import EvalDefault, EvalId
from .columns.sample import (
    SampleColumns,
    SampleDefault,
    SampleSummaryDefault,
)
from .extract import model_to_record
from .record import import_record
from .validate import (
    eval_log_schema,
    sample_summary_schema,
)

if TYPE_CHECKING:
    import pandas as pd

LogPaths: TypeAlias = PathLike[str] | str | Sequence[PathLike[str] | str]


@overload
def evals_df(
    logs: LogPaths,
    columns: Columns = EvalDefault,
    recursive: bool = True,
    reverse: bool = False,
    strict: Literal[True] = True,
) -> "pd.DataFrame": ...


@overload
def evals_df(
    logs: LogPaths,
    columns: Columns = EvalDefault,
    recursive: bool = True,
    reverse: bool = False,
    strict: Literal[False] = False,
) -> tuple["pd.DataFrame", ColumnErrors]: ...


def evals_df(
    logs: LogPaths,
    columns: Columns = EvalDefault,
    recursive: bool = True,
    reverse: bool = False,
    strict: bool = True,
) -> "pd.DataFrame" | tuple["pd.DataFrame", ColumnErrors]:
    """Read a dataframe containing evals.

    Args:
       logs: One or more paths to log files or log directories.
       columns: Specification for what columns to read from the log file.
       recursive: Include recursive contents of directories (defaults to `True`)
       reverse: Reverse the order of the data frame (by default, items
          are ordered from oldest to newest).
       strict: Raise import errors immediately. Defaults to `True`.
          If `False` then a tuple of `DataFrame` and errors is returned.

    Returns:
       For `strict`, a Pandas `DataFrame` with information for the specified logs.
       For `strict=False`, a tuple of Pandas `DataFrame` and a dictionary of errors
       encountered (by log file) during import.
    """
    _verify_prerequisites()
    import pyarrow as pa

    # resolve logs
    log_paths = _resolve_logs(logs, recursive=recursive, reverse=reverse)

    # accumulate errors for strict=False
    all_errors = ColumnErrors()

    # prepare schema for validation of jsonpath expressions
    schema = eval_log_schema()

    # read logs
    records: list[dict[str, ColumnType]] = []
    with display().progress(total=len(log_paths)) as p:
        for log_path in log_paths:
            log = read_eval_log(log_path, header_only=True)
            if strict:
                record = import_record(log, columns, strict=True, schema=schema)
            else:
                record, errors = import_record(
                    log, columns, strict=False, schema=schema
                )
                all_errors[pretty_path(log_path)] = errors
            records.append(record)

            p.update()

    # return table (+errors if strict=False)
    records = _normalize_records(records)
    evals_table = pa.Table.from_pylist(records).to_pandas()

    if strict:
        return evals_table
    else:
        return evals_table, all_errors


@overload
def samples_df(
    logs: LogPaths,
    columns: SampleColumns = SampleDefault,
    recursive: bool = True,
    reverse: bool = False,
    strict: Literal[True] = True,
) -> "pd.DataFrame": ...


@overload
def samples_df(
    logs: LogPaths,
    columns: SampleColumns = SampleDefault,
    recursive: bool = True,
    reverse: bool = False,
    strict: Literal[False] = False,
) -> "pd.DataFrame": ...


def samples_df(
    logs: LogPaths,
    columns: SampleColumns = SampleDefault,
    recursive: bool = True,
    reverse: bool = False,
    strict: bool = True,
) -> pd.DataFrame | tuple["pd.DataFrame", ColumnErrors]:
    _verify_prerequisites()
    import pyarrow as pa

    # resolve logs
    logs = _resolve_logs(logs, recursive=recursive, reverse=reverse)

    # get eval records (column spec must include eval_id)
    columns_eval = columns.eval or SampleDefault.eval or EvalId
    if "eval_id" not in columns_eval:
        raise ValueError("eval_id must be inclueed in the columns for a samples_df.")
    columns_sample = columns.sample or SampleDefault.sample or SampleSummaryDefault

    # read samples from each log
    schema = sample_summary_schema()
    records: list[dict[str, ColumnType]] = []
    all_errors = ColumnErrors()
    evals_table = evals_df(logs, columns=columns_eval)
    with display().progress(total=len(evals_table)) as p:
        # read samples from sample summary
        for eval_id, log in zip(evals_table["eval_id"].to_list(), logs):
            sample_summaries = read_eval_log_sample_summaries(log)
            for sample_summary in sample_summaries:
                sample_record = model_to_record(sample_summary)
                if strict:
                    record = import_record(
                        sample_record, columns_sample, strict=True, schema=schema
                    )
                else:
                    record, errors = import_record(
                        sample_record, columns_sample, strict=False, schema=schema
                    )
                    error_key = f"{pretty_path(log)} [{sample_summary.id}, {sample_summary.epoch}]"
                    all_errors[error_key] = errors

                records.append({"eval_id": eval_id} | record)
            p.update()

    # normalize records and produce samples table
    records = _normalize_records(records)
    samples_table = pa.Table.from_pylist(records).to_pandas()

    # join eval_records
    samples_table = samples_table.merge(
        evals_table, on="eval_id", how="left", suffixes=("_sample", "_eval")
    )

    # return
    if strict:
        return samples_table
    else:
        return samples_table, all_errors


def messages_df(logs: LogPaths, recursive: bool = True) -> pd.DataFrame:
    _verify_prerequisites()
    import pandas as pd

    return pd.DataFrame()


def events_df(logs: LogPaths, recursive: bool = True) -> pd.DataFrame:
    _verify_prerequisites()
    import pandas as pd

    return pd.DataFrame()


def _resolve_logs(logs: LogPaths, recursive: bool, reverse: bool) -> list[str]:
    # normalize to list of str
    logs = [logs] if isinstance(logs, str | PathLike) else logs
    logs = [Path(log).as_posix() if isinstance(log, PathLike) else log for log in logs]

    # expand directories
    log_paths: list[FileInfo] = []
    for log in logs:
        if isinstance(log, PathLike):
            log = Path(log).as_posix()
        fs = filesystem(log)
        info = fs.info(log)
        if info.type == "directory":
            log_paths.extend(
                [
                    fi
                    for fi in fs.ls(info.name, recursive=recursive)
                    if fi.type == "file"
                ]
            )
        else:
            log_paths.append(info)

    log_files = log_files_from_ls(log_paths, descending=reverse)
    return [log_file.name for log_file in log_files]


def _verify_prerequisites() -> None:
    # ensure we have all of the optional packages we need
    required_packages: list[str] = []
    try:
        import pandas  # noqa: F401
    except ImportError:
        required_packages.append("pandas")

    try:
        import pyarrow  # noqa: F401
    except ImportError:
        required_packages.append("pyarrow")

    if len(required_packages) > 0:
        raise pip_dependency_error("inspect_ai.analysis", required_packages)

    # enforce version constraints
    verify_required_version("inspect_ai.analysis", "pandas", "2.0.0")
    verify_required_version("inspect_ai.analysis", "pyarrow", "10.0.1")


def _normalize_records(
    records: list[dict[str, ColumnType]],
) -> list[dict[str, ColumnType]]:
    all_keys = _get_all_keys(records)
    normalized_records = []
    for record in records:
        normalized_record = {key: record.get(key, None) for key in all_keys}
        normalized_records.append(normalized_record)
    return normalized_records


def _get_all_keys(records: list[dict[str, ColumnType]]) -> set[str]:
    all_keys: set[str] = set()
    for record in records:
        all_keys.update(record.keys())
    return all_keys
