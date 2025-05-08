from __future__ import annotations

from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Callable,
    Generator,
    Literal,
    overload,
)

from inspect_ai._display import display
from inspect_ai._util.path import pretty_path
from inspect_ai.analysis.beta._dataframe.events.columns import EventColumn
from inspect_ai.analysis.beta._dataframe.messages.columns import MessageColumn
from inspect_ai.log._file import (
    read_eval_log_sample_summaries,
    read_eval_log_samples,
)
from inspect_ai.log._log import EvalSample, EvalSampleSummary
from inspect_ai.log._transcript import BaseEvent, Event
from inspect_ai.model._chat_message import ChatMessage

from ..columns import Column, ColumnErrors, ColumnType
from ..evals.columns import EvalColumn
from ..evals.table import EVAL_ID, EVAL_SUFFIX, ensure_eval_id, evals_df
from ..record import import_record, resolve_duplicate_columns
from ..util import (
    LogPaths,
    add_unreferenced_columns,
    records_to_pandas,
    resolve_columns,
    resolve_logs,
    verify_prerequisites,
)
from .columns import SampleColumn, SampleSummary
from .extract import auto_detail_id, auto_sample_id

if TYPE_CHECKING:
    import pandas as pd


SAMPLE_ID = "sample_id"
SAMPLE_SUFFIX = "_sample"


@overload
def samples_df(
    logs: LogPaths,
    columns: list[Column] = SampleSummary,
    recursive: bool = True,
    reverse: bool = False,
    strict: Literal[True] = True,
) -> "pd.DataFrame": ...


@overload
def samples_df(
    logs: LogPaths,
    columns: list[Column] = SampleSummary,
    recursive: bool = True,
    reverse: bool = False,
    strict: Literal[False] = False,
) -> tuple["pd.DataFrame", ColumnErrors]: ...


def samples_df(
    logs: LogPaths,
    columns: list[Column] = SampleSummary,
    recursive: bool = True,
    reverse: bool = False,
    strict: bool = True,
) -> "pd.DataFrame" | tuple["pd.DataFrame", ColumnErrors]:
    """Read a dataframe containing samples from a set of evals.

    Args:
       logs: One or more paths to log files or log directories.
       columns: Specification for what columns to read from log files.
       recursive: Include recursive contents of directories (defaults to `True`)
       reverse: Reverse the order of the dataframe (by default, items
          are ordered from oldest to newest).
       strict: Raise import errors immediately. Defaults to `True`.
          If `False` then a tuple of `DataFrame` and errors is returned.

    Returns:
       For `strict`, a Pandas `DataFrame` with information for the specified logs.
       For `strict=False`, a tuple of Pandas `DataFrame` and a dictionary of errors
       encountered (by log file) during import.
    """
    return _read_samples_df(
        logs, columns, recursive=recursive, reverse=reverse, strict=strict
    )


@dataclass
class MessagesDetail:
    name: str = "message"
    col_type = MessageColumn
    filter: Callable[[ChatMessage], bool] = lambda m: True


@dataclass
class EventsDetail:
    name: str = "message"
    col_type = EventColumn
    filter: Callable[[BaseEvent], bool] = lambda e: True


def _read_samples_df(
    logs: LogPaths,
    columns: list[Column],
    *,
    recursive: bool = True,
    reverse: bool = False,
    strict: bool = True,
    detail: MessagesDetail | EventsDetail | None = None,
) -> "pd.DataFrame" | tuple["pd.DataFrame", ColumnErrors]:
    verify_prerequisites()

    # resolve logs
    logs = resolve_logs(logs, recursive=recursive, reverse=reverse)

    # split columns by type
    columns_eval: list[Column] = []
    columns_sample: list[Column] = []
    columns_detail: list[Column] = []
    for column in columns:
        if isinstance(column, EvalColumn):
            columns_eval.append(column)
        elif isinstance(column, SampleColumn):
            columns_sample.append(column)
            if column._full:
                require_full_samples = True
        elif detail and isinstance(column, detail.col_type):
            columns_detail.append(column)
        else:
            raise ValueError(
                f"Unexpected column type passed to samples_df: {type(column)}"
            )
    # resolve duplciates
    columns_eval = resolve_duplicate_columns(columns_eval)
    columns_sample = resolve_duplicate_columns(columns_sample)
    columns_detail = resolve_duplicate_columns(columns_detail)

    # determine if we require full samples
    require_full_samples = len(columns_detail) > 0 or any(
        [isinstance(column, SampleColumn) and column._full for column in columns_sample]
    )

    # make sure eval_id is present
    ensure_eval_id(columns_eval)

    # read samples from each log
    sample_records: list[dict[str, ColumnType]] = []
    detail_records: list[dict[str, ColumnType]] = []
    all_errors = ColumnErrors()
    evals_table = evals_df(logs, columns=columns_eval)
    with display().progress(total=len(evals_table)) as p:
        # read samples
        for eval_id, log in zip(evals_table[EVAL_ID].to_list(), logs):
            # get a generator for the samples (might require reading the full log
            # or might be fine to just read the summaries)
            if require_full_samples:
                samples: Generator[EvalSample | EvalSampleSummary, None, None] = (
                    read_eval_log_samples(
                        log, all_samples_required=False, resolve_attachments=True
                    )
                )
            else:
                samples = (summary for summary in read_eval_log_sample_summaries(log))
            for sample in samples:
                if strict:
                    record = import_record(sample, columns_sample, strict=True)
                else:
                    record, errors = import_record(sample, columns_sample, strict=False)
                    error_key = f"{pretty_path(log)} [{sample.id}, {sample.epoch}]"
                    all_errors[error_key] = errors

                # inject ids
                sample_id = sample.uuid or auto_sample_id(eval_id, sample)
                ids: dict[str, ColumnType] = {
                    EVAL_ID: eval_id,
                    SAMPLE_ID: sample_id,
                }

                # record with ids
                record = ids | record

                # if there are detail columns then we blow out these records w/ detail
                if detail is not None:
                    # filter detail records
                    assert isinstance(sample, EvalSample)
                    if isinstance(detail, MessagesDetail):
                        detail_items: list[ChatMessage] | list[Event] = [
                            m for m in sample.messages if detail.filter(m)
                        ]
                    elif isinstance(detail, EventsDetail):
                        detail_items = [e for e in sample.events if detail.filter(e)]
                    else:
                        detail_items = []

                    # read detail records (provide auto-ids)
                    for index, item in enumerate(detail_items):
                        if strict:
                            detail_record = import_record(
                                item, columns_detail, strict=True
                            )
                        else:
                            detail_record, errors = import_record(
                                item, columns_detail, strict=False
                            )
                            error_key = (
                                f"{pretty_path(log)} [{sample.id}, {sample.epoch}]"
                            )
                            all_errors[error_key] = errors

                        # inject ids
                        detail_id = detail_record.get(
                            "id", auto_detail_id(sample_id, detail.name, index)
                        )
                        ids = {SAMPLE_ID: sample_id, f"{detail.name}_id": detail_id}
                        detail_record = ids | detail_record

                        # append detail record
                        detail_records.append(detail_record)

                # record sample record
                sample_records.append(record)
            p.update()

    # normalize records and produce samples table
    samples_table = records_to_pandas(sample_records)

    # if we have detail records then join them into the samples table
    if detail is not None:
        details_table = records_to_pandas(detail_records)
        samples_table = details_table.merge(
            samples_table,
            on=SAMPLE_ID,
            how="left",
            suffixes=(f"_{detail.name}", SAMPLE_SUFFIX),
        )

    # join eval_records
    samples_table = samples_table.merge(
        evals_table, on=EVAL_ID, how="left", suffixes=(SAMPLE_SUFFIX, EVAL_SUFFIX)
    )

    # re-order based on original specification
    samples_table = reorder_samples_df_columns(
        samples_table,
        columns_eval,
        columns_sample,
        columns_detail,
        detail.name if detail else "",
    )

    # return
    if strict:
        return samples_table
    else:
        return samples_table, all_errors


def reorder_samples_df_columns(
    df: "pd.DataFrame",
    eval_columns: list[Column],
    sample_columns: list[Column],
    detail_columns: list[Column],
    details_name: str,
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

    # detail first if we have detail
    if details_name:
        ordered_columns.append(f"{details_name}_id")

    # sample_id first
    if SAMPLE_ID in actual_columns:
        ordered_columns.append(SAMPLE_ID)

    # eval_id next
    if EVAL_ID in actual_columns:
        ordered_columns.append(EVAL_ID)

    # eval columns
    for column in eval_columns:
        if column.name == EVAL_ID or column.name == SAMPLE_ID:
            continue  # Already handled

        ordered_columns.extend(
            resolve_columns(column.name, EVAL_SUFFIX, actual_columns, ordered_columns)
        )

    # then sample columns
    for column in sample_columns:
        if column.name == EVAL_ID or column.name == SAMPLE_ID:
            continue  # Already handled

        ordered_columns.extend(
            resolve_columns(column.name, SAMPLE_SUFFIX, actual_columns, ordered_columns)
        )

    # then detail columns
    for column in detail_columns:
        if column.name == EVAL_ID or column.name == SAMPLE_ID:
            continue  # Already handled

        ordered_columns.extend(
            resolve_columns(
                column.name, f"_{details_name}", actual_columns, ordered_columns
            )
        )

    # add any unreferenced columns
    ordered_columns = add_unreferenced_columns(actual_columns, ordered_columns)

    # reorder the DataFrame
    return df[ordered_columns]
