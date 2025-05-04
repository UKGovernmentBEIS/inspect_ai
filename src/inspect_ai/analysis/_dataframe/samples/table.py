from __future__ import annotations

from typing import TYPE_CHECKING, Literal, overload

from inspect_ai._display import display
from inspect_ai._util.path import pretty_path
from inspect_ai.log._file import (
    read_eval_log_sample_summaries,
)

from ..columns import ColumnErrors, Columns, ColumnType
from ..evals.columns import EvalId
from ..evals.table import evals_df
from ..extract import auto_sample_id, model_to_record
from ..record import import_record
from ..util import (
    LogPaths,
    normalize_records,
    resolve_columns,
    resolve_logs,
    verify_prerequisites,
)
from ..validate import (
    sample_summary_schema,
)
from .columns import SampleColumns, SampleDefault, SampleSummary

if TYPE_CHECKING:
    import pandas as pd


SAMPLE_ID = "sample_id"
SAMPLE_SUFFIX = "_sample"
EVAL_ID = "eval_id"
EVAL_SUFFIX = "_eval"


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
) -> "pd.DataFrame" | tuple["pd.DataFrame", ColumnErrors]:
    verify_prerequisites()
    import pyarrow as pa

    # resolve logs
    logs = resolve_logs(logs, recursive=recursive, reverse=reverse)

    # get eval records (column spec must include eval_id)
    columns_eval = columns.eval or SampleDefault.eval or EvalId
    if EVAL_ID not in columns_eval:
        raise ValueError("eval_id must be inclueed in the columns for a samples_df.")
    columns_sample = columns.sample or SampleDefault.sample or SampleSummary

    # read samples from each log
    schema = sample_summary_schema()
    records: list[dict[str, ColumnType]] = []
    all_errors = ColumnErrors()
    evals_table = evals_df(logs, columns=columns_eval)
    with display().progress(total=len(evals_table)) as p:
        # read samples from sample summary
        for eval_id, log in zip(evals_table[EVAL_ID].to_list(), logs):
            sample_summaries = read_eval_log_sample_summaries(log)
            for index, sample_summary in enumerate(sample_summaries):
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

                # inject ids
                ids: dict[str, ColumnType] = {
                    EVAL_ID: eval_id,
                    "sample_id": sample_summary.uuid
                    or auto_sample_id(eval_id, sample_summary),
                }

                records.append(ids | record)
            p.update()

    # normalize records and produce samples table
    records = normalize_records(records)
    samples_table = pa.Table.from_pylist(records).to_pandas()

    # join eval_records
    samples_table = samples_table.merge(
        evals_table, on=EVAL_ID, how="left", suffixes=(SAMPLE_SUFFIX, EVAL_SUFFIX)
    )

    # re-order based on original specification
    samples_table = reorder_samples_df_columns(
        samples_table, columns_eval, columns_sample
    )

    # return
    if strict:
        return samples_table
    else:
        return samples_table, all_errors


def reorder_samples_df_columns(
    df: "pd.DataFrame", eval_columns: Columns, sample_columns: Columns
) -> "pd.DataFrame":
    """Reorder columns in the merged DataFrame.

    Order with:
    1. sample_id first
    2. eval_id second
    3. eval columns
    4. sample columns
    5. any remaining columns
    """
    actual_columns = list(df.columns)
    ordered_columns: list[str] = []

    # sample_id first
    if SAMPLE_ID in actual_columns:
        ordered_columns.append(SAMPLE_ID)

    # eval_id next
    if EVAL_ID in actual_columns:
        ordered_columns.append(EVAL_ID)

    # eval columns
    for col_pattern in eval_columns:
        if col_pattern == EVAL_ID or col_pattern == SAMPLE_ID:
            continue  # Already handled

        ordered_columns.extend(
            resolve_columns(col_pattern, EVAL_SUFFIX, actual_columns, ordered_columns)
        )

    # then sample columns
    for col_pattern in sample_columns:
        if col_pattern == EVAL_ID or col_pattern == SAMPLE_ID:
            continue  # Already handled

        ordered_columns.extend(
            resolve_columns(col_pattern, SAMPLE_SUFFIX, actual_columns, ordered_columns)
        )

    # Add any remaining columns
    remaining_cols = sorted([c for c in actual_columns if c not in ordered_columns])
    ordered_columns.extend(remaining_cols)

    # Make sure we haven't missed any columns
    assert len(ordered_columns) == len(actual_columns), "Column count mismatch"
    assert set(ordered_columns) == set(actual_columns), "Column set mismatch"

    # Reorder the DataFrame
    return df[ordered_columns]
