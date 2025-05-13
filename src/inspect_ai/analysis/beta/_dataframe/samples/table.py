from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import (
    TYPE_CHECKING,
    Callable,
    Generator,
    Literal,
    overload,
)

from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.path import pretty_path
from inspect_ai.analysis.beta._dataframe.progress import import_progress, no_progress
from inspect_ai.log._file import (
    list_eval_logs,
    read_eval_log_sample_summaries,
    read_eval_log_samples,
)
from inspect_ai.log._log import EvalSample, EvalSampleSummary
from inspect_ai.log._transcript import Event
from inspect_ai.model._chat_message import ChatMessage

from ..columns import Column, ColumnErrors, ColumnType
from ..evals.columns import EvalColumn
from ..evals.table import EVAL_ID, EVAL_SUFFIX, _read_evals_df, ensure_eval_id
from ..events.columns import EventColumn
from ..extract import message_as_str
from ..messages.columns import MessageColumn
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
    logs: LogPaths = list_eval_logs(),
    columns: list[Column] = SampleSummary,
    strict: Literal[True] = True,
) -> "pd.DataFrame": ...


@overload
def samples_df(
    logs: LogPaths = list_eval_logs(),
    columns: list[Column] = SampleSummary,
    strict: Literal[False] = False,
) -> tuple["pd.DataFrame", ColumnErrors]: ...


def samples_df(
    logs: LogPaths = list_eval_logs(),
    columns: list[Column] = SampleSummary,
    strict: bool = True,
) -> "pd.DataFrame" | tuple["pd.DataFrame", ColumnErrors]:
    """Read a dataframe containing samples from a set of evals.

    Args:
       logs: One or more paths to log files or log directories.
          Defaults to the contents of the currently active log directory
          (e.g. ./logs or INSPECT_LOG_DIR).
       columns: Specification for what columns to read from log files.
       strict: Raise import errors immediately. Defaults to `True`.
          If `False` then a tuple of `DataFrame` and errors is returned.

    Returns:
       For `strict`, a Pandas `DataFrame` with information for the specified logs.
       For `strict=False`, a tuple of Pandas `DataFrame` and a dictionary of errors
       encountered (by log file) during import.
    """
    return _read_samples_df(logs, columns, strict=strict)


@dataclass
class MessagesDetail:
    name: str = "message"
    col_type = MessageColumn
    filter: Callable[[ChatMessage], bool] = lambda m: True


@dataclass
class EventsDetail:
    name: str = "event"
    col_type = EventColumn
    filter: Callable[[Event], bool] = lambda e: True


def _read_samples_df(
    logs: LogPaths,
    columns: list[Column],
    *,
    strict: bool = True,
    detail: MessagesDetail | EventsDetail | None = None,
    progress: bool = True,
) -> "pd.DataFrame" | tuple["pd.DataFrame", ColumnErrors]:
    verify_prerequisites()

    # resolve logs
    logs = resolve_logs(logs)

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

    # establish progress
    progress_cm = (
        import_progress("scanning logs", total=len(logs)) if progress else no_progress()
    )

    # determine how we will allocate progress
    with progress_cm as p:
        # read samples from each log
        sample_records: list[dict[str, ColumnType]] = []
        detail_records: list[dict[str, ColumnType]] = []
        all_errors = ColumnErrors()

        # read logs and note total samples
        evals_table, total_samples = _read_evals_df(
            logs, columns=columns_eval, strict=True, progress=p.update
        )

        # update progress now that we know the total samples
        entity = detail.name if detail else "sample"
        p.reset(description=f"reading {entity}s", completed=0, total=total_samples)

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
                        detail_items: list[ChatMessage] | list[Event] = (
                            sample_messages_from_events(sample.events, detail.filter)
                        )
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


def sample_messages_from_events(
    events: list[Event], filter: Callable[[ChatMessage], bool]
) -> list[ChatMessage]:
    # don't yield the same event twice
    ids: set[str] = set()

    # we need to look at the full input to every model event and add
    # messages we haven't seen before
    messages: list[ChatMessage] = []
    for event in events:
        if event.event == "model":
            event_messages = event.input + (
                [event.output.message] if not event.output.empty else []
            )
            for message in event_messages:
                id = message.id or message_hash(message_as_str(message))
                if id not in ids:
                    messages.append(message)
                    ids.add(id)

    # then apply the filter
    return [message for message in messages if filter(message)]


@lru_cache(maxsize=100)
def message_hash(message: str) -> str:
    return mm3_hash(message)


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
