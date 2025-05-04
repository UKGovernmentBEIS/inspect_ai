from __future__ import annotations

from typing import TYPE_CHECKING, Literal, overload

from inspect_ai._display import display
from inspect_ai._util.path import pretty_path
from inspect_ai.log._file import (
    read_eval_log_sample_summaries,
)

from ..columns import ColumnErrors, ColumnType
from ..evals.columns import EvalId
from ..evals.table import evals_df
from ..extract import auto_sample_id, model_to_record
from ..record import import_record
from ..util import (
    LogPaths,
    normalize_records,
    resolve_logs,
    verify_prerequisites,
)
from ..validate import (
    sample_summary_schema,
)
from .columns import SampleColumns, SampleDefault, SampleSummary

if TYPE_CHECKING:
    import pandas as pd


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
    verify_prerequisites()
    import pyarrow as pa

    # resolve logs
    logs = resolve_logs(logs, recursive=recursive, reverse=reverse)

    # get eval records (column spec must include eval_id)
    columns_eval = columns.eval or SampleDefault.eval or EvalId
    if "eval_id" not in columns_eval:
        raise ValueError("eval_id must be inclueed in the columns for a samples_df.")
    columns_sample = columns.sample or SampleDefault.sample or SampleSummary

    # read samples from each log
    schema = sample_summary_schema()
    records: list[dict[str, ColumnType]] = []
    all_errors = ColumnErrors()
    evals_table = evals_df(logs, columns=columns_eval)
    with display().progress(total=len(evals_table)) as p:
        # read samples from sample summary
        for eval_id, log in zip(evals_table["eval_id"].to_list(), logs):
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
                    "eval_id": eval_id,
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
        evals_table, on="eval_id", how="left", suffixes=("_sample", "_eval")
    )

    # return
    if strict:
        return samples_table
    else:
        return samples_table, all_errors
