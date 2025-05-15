from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING, Callable, Literal, Sequence, overload

from inspect_ai.analysis.beta._dataframe.progress import import_progress, no_progress
from inspect_ai.log._file import (
    list_eval_logs,
    read_eval_log,
)
from inspect_ai.log._log import EvalLog

from ..columns import Column, ColumnError, ColumnType
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

logger = getLogger(__name__)

if TYPE_CHECKING:
    import pandas as pd

EVAL_ID = "eval_id"
EVAL_SUFFIX = "_eval"


@overload
def evals_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = EvalColumns,
    strict: Literal[True] = True,
    quiet: bool = False,
) -> "pd.DataFrame": ...


@overload
def evals_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = EvalColumns,
    strict: Literal[False] = False,
    quiet: bool = False,
) -> tuple["pd.DataFrame", Sequence[ColumnError]]: ...


def evals_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = EvalColumns,
    strict: bool = True,
    quiet: bool = False,
) -> "pd.DataFrame" | tuple["pd.DataFrame", Sequence[ColumnError]]:
    """Read a dataframe containing evals.

    Args:
       logs: One or more paths to log files or log directories.
          Defaults to the contents of the currently active log directory
          (e.g. ./logs or INSPECT_LOG_DIR).
       columns: Specification for what columns to read from log files.
       strict: Raise import errors immediately. Defaults to `True`.
          If `False` then a tuple of `DataFrame` and errors is returned.
       quiet: If `True`, do not show any output or progress. Defaults to `False`.

    Returns:
       For `strict`, a Pandas `DataFrame` with information for the specified logs.
       For `strict=False`, a tuple of Pandas `DataFrame` and a dictionary of errors
       encountered (by log file) during import.
    """
    verify_prerequisites()

    # resolve logs
    log_paths = resolve_logs(logs)

    # establish progress
    progress_cm = (
        import_progress("reading logs", total=len(log_paths))
        if not quiet
        else no_progress()
    )

    with progress_cm as p:
        if strict:
            evals_table, _, _ = _read_evals_df(log_paths, columns, True, p.update)
            return evals_table
        else:
            evals_table, _, all_errors, _ = _read_evals_df(
                log_paths, columns, False, p.update
            )
            return evals_table, all_errors


@overload
def _read_evals_df(
    log_paths: Sequence[str],
    columns: Sequence[Column],
    strict: Literal[True],
    progress: Callable[[], None],
) -> tuple["pd.DataFrame", Sequence[EvalLog], int]: ...


@overload
def _read_evals_df(
    log_paths: Sequence[str],
    columns: Sequence[Column],
    strict: Literal[False],
    progress: Callable[[], None],
) -> tuple["pd.DataFrame", Sequence[EvalLog], Sequence[ColumnError], int]: ...


def _read_evals_df(
    log_paths: Sequence[str],
    columns: Sequence[Column],
    strict: bool,
    progress: Callable[[], None],
) -> (
    tuple["pd.DataFrame", Sequence[EvalLog], int]
    | tuple["pd.DataFrame", Sequence[EvalLog], Sequence[ColumnError], int]
):
    verify_prerequisites()

    # resolve duplicate columns
    columns = resolve_duplicate_columns(columns)

    # accumulate errors for strict=False
    all_errors: list[ColumnError] = []

    # ensure eval_id
    columns = ensure_eval_id(columns)

    # read logs
    total_samples = 0
    eval_ids: set[str] = set()
    eval_logs: list[EvalLog] = []
    records: list[dict[str, ColumnType]] = []
    for log_path in log_paths:
        log = read_eval_log(log_path, header_only=True)
        if strict:
            record = import_record(log, log, columns, strict=True)
        else:
            record, errors = import_record(log, log, columns, strict=False)
            all_errors.extend(errors)

        # don't add duplicate ids
        eval_id = str(record.get(EVAL_ID, ""))
        if eval_id not in eval_ids:
            eval_ids.add(eval_id)
            eval_logs.append(log)
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
        return evals_table, eval_logs, total_samples
    else:
        return evals_table, eval_logs, all_errors, total_samples


def ensure_eval_id(columns: Sequence[Column]) -> Sequence[Column]:
    if not any([column.name == EVAL_ID for column in columns]):
        return list(columns) + EvalId
    else:
        return columns


def reorder_evals_df_columns(
    df: "pd.DataFrame", eval_columns: Sequence[Column]
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
