from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Literal, overload

from inspect_ai._util.path import pretty_path
from inspect_ai.analysis.beta._dataframe.progress import import_progress
from inspect_ai.log._file import (
    read_eval_log,
)

from ..columns import Column, ColumnErrors, ColumnType
from ..record import import_record, resolve_duplicate_columns
from ..util import (
    LogPaths,
    add_unreferenced_columns,
    records_to_pandas,
    resolve_columns,
    resolve_logs,
    verify_prerequisites,
)
from .columns import EvalColumns, EvalId

if TYPE_CHECKING:
    import pandas as pd

EVAL_ID = "eval_id"
EVAL_SUFFIX = "_eval"


@overload
def evals_df(
    logs: LogPaths,
    columns: list[Column] = EvalColumns,
    recursive: bool = True,
    strict: Literal[True] = True,
) -> "pd.DataFrame": ...


@overload
def evals_df(
    logs: LogPaths,
    columns: list[Column] = EvalColumns,
    recursive: bool = True,
    strict: Literal[False] = False,
) -> tuple["pd.DataFrame", ColumnErrors]: ...


def evals_df(
    logs: LogPaths,
    columns: list[Column] = EvalColumns,
    recursive: bool = True,
    strict: bool = True,
) -> "pd.DataFrame" | tuple["pd.DataFrame", ColumnErrors]:
    """Read a dataframe containing evals.

    Args:
       logs: One or more paths to log files or log directories.
       columns: Specification for what columns to read from log files.
       recursive: Include recursive contents of directories (defaults to `True`)
       strict: Raise import errors immediately. Defaults to `True`.
          If `False` then a tuple of `DataFrame` and errors is returned.

    Returns:
       For `strict`, a Pandas `DataFrame` with information for the specified logs.
       For `strict=False`, a tuple of Pandas `DataFrame` and a dictionary of errors
       encountered (by log file) during import.
    """
    verify_prerequisites()

    # resolve logs
    log_paths = resolve_logs(logs, recursive=recursive)

    with import_progress("reading logs", total=len(log_paths)) as (p, task_id):
        if strict:
            evals_table, _ = _read_evals_df(
                log_paths, columns, True, lambda: p.update(task_id, advance=1)
            )
            return evals_table
        else:
            evals_table, all_errors, _ = _read_evals_df(
                log_paths, columns, False, lambda: p.update(task_id, advance=1)
            )
            return evals_table, all_errors


@overload
def _read_evals_df(
    log_paths: list[str],
    columns: list[Column],
    strict: Literal[True],
    progress: Callable[[], None],
) -> tuple["pd.DataFrame", int]: ...


@overload
def _read_evals_df(
    log_paths: list[str],
    columns: list[Column],
    strict: Literal[False],
    progress: Callable[[], None],
) -> tuple["pd.DataFrame", ColumnErrors, int]: ...


def _read_evals_df(
    log_paths: list[str],
    columns: list[Column],
    strict: bool,
    progress: Callable[[], None],
) -> tuple["pd.DataFrame", int] | tuple["pd.DataFrame", ColumnErrors, int]:
    verify_prerequisites()

    # resolve duplicate columns
    columns = resolve_duplicate_columns(columns)

    # accumulate errors for strict=False
    all_errors = ColumnErrors()

    # ensure eval_id
    ensure_eval_id(columns)

    # read logs
    total_samples = 0
    records: list[dict[str, ColumnType]] = []
    for log_path in log_paths:
        log = read_eval_log(log_path, header_only=True)
        if strict:
            record = import_record(log, columns, strict=True)
        else:
            record, errors = import_record(log, columns, strict=False)
            all_errors[pretty_path(log_path)] = errors
        records.append(record)
        total_samples += (
            len(log.eval.dataset.sample_ids)
            if log.eval.dataset.sample_ids is not None
            else (log.eval.dataset.samples or 100)
        )
        progress()

    # return table (+errors if strict=False)
    evals_table = records_to_pandas(records)
    evals_table = reorder_evals_df_columns(evals_table, columns)

    if strict:
        return evals_table, total_samples
    else:
        return evals_table, all_errors, total_samples


def ensure_eval_id(columns: list[Column]) -> None:
    if not any([column.name == EVAL_ID for column in columns]):
        columns.extend(EvalId)


def reorder_evals_df_columns(
    df: "pd.DataFrame", eval_columns: list[Column]
) -> "pd.DataFrame":
    actual_columns = list(df.columns)
    ordered_columns: list[str] = []

    # eval_id first
    if EVAL_ID in actual_columns:
        ordered_columns.append(EVAL_ID)

    # eval columns
    for col in eval_columns:
        col_pattern = col.name
        if col_pattern == EVAL_ID:
            continue  # Already handled

        ordered_columns.extend(
            resolve_columns(col_pattern, EVAL_SUFFIX, actual_columns, ordered_columns)
        )

    # add any unreferenced columns
    ordered_columns = add_unreferenced_columns(actual_columns, ordered_columns)

    # reorder the DataFrame
    return df[ordered_columns]
