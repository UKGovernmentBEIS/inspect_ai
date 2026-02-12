from __future__ import annotations

import functools
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache, partial
from itertools import chain
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterable,
    Literal,
    Sequence,
    cast,
    overload,
)

from inspect_ai._util.asyncfiles import AsyncFilesystem, run_tg_collect_with_fs
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.platform import running_in_notebook
from inspect_ai.analysis._dataframe.progress import import_progress, no_progress
from inspect_ai.event._event import Event
from inspect_ai.log._file import (
    read_eval_log_async,
    read_eval_log_sample_summaries_async,
)
from inspect_ai.log._log import EvalLog, EvalSample, EvalSampleSummary
from inspect_ai.model._chat_message import ChatMessage

from ..columns import Column, ColumnError, ColumnType
from ..evals.columns import EvalColumn
from ..evals.table import EVAL_ID, EVAL_SUFFIX, _read_evals_df, ensure_eval_data
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
    logs: LogPaths | EvalLog | Sequence[EvalLog] | None = None,
    columns: Sequence[Column] = SampleSummary,
    full: bool = False,
    strict: Literal[True] = True,
    parallel: bool | int = False,
    quiet: bool | None = None,
) -> "pd.DataFrame": ...


@overload
def samples_df(
    logs: LogPaths | EvalLog | Sequence[EvalLog] | None = None,
    columns: Sequence[Column] = SampleSummary,
    full: bool = False,
    strict: Literal[False] = False,
    parallel: bool | int = False,
    quiet: bool | None = None,
) -> tuple["pd.DataFrame", list[ColumnError]]: ...


def samples_df(
    logs: LogPaths | EvalLog | Sequence[EvalLog] | None = None,
    columns: Sequence[Column] = SampleSummary,
    full: bool = False,
    strict: bool = True,
    parallel: bool | int = False,
    quiet: bool | None = None,
) -> "pd.DataFrame" | tuple["pd.DataFrame", list[ColumnError]]:
    """Read a dataframe containing samples from a set of evals.

    Args:
       logs: One or more paths to log files, log directories, or EvalLog objects.
          Defaults to the contents of the currently active log directory
          (e.g. ./logs or INSPECT_LOG_DIR).
       columns: Specification for what columns to read from log files.
       full: Read full sample `metadata`. This will be much slower, but will include
          the unfiltered values of sample `metadata` rather than the abbreviated
          metadata from sample summaries (which includes only scalar values and limits
          string values to 1k).
       strict: Raise import errors immediately. Defaults to `True`.
          If `False` then a tuple of `DataFrame` and errors is returned.
       parallel: If `True`, use `ProcessPoolExecutor` to read logs in parallel
          (with workers based on `mp.cpu_count()`, capped at 8). If `int`, read
          in parallel with the specified number of workers. If `False` (the default)
          do not read in parallel.
       quiet: If `True`, do not show any output or progress. Defaults to `False`
          for terminal environments, and `True` for notebooks.

    Returns:
       For `strict`, a Pandas `DataFrame` with information for the specified logs.
       For `strict=False`, a tuple of Pandas `DataFrame` and a dictionary of errors
       encountered (by log file) during import.
    """
    verify_prerequisites()

    quiet = quiet if quiet is not None else running_in_notebook()
    logs = resolve_logs(logs)

    return _read_samples_df(
        logs,
        columns,
        full=full,
        strict=strict,
        progress=not quiet,
        parallel=parallel,
    )


@dataclass
class MessagesDetail:
    name: str = "message"
    col_type = MessageColumn
    filter: Callable[[ChatMessage], bool] | None = None


@dataclass
class EventsDetail:
    name: str = "event"
    col_type = EventColumn
    filter: Callable[[Event], bool] | None = None


def _read_samples_df(
    logs: list[str] | list[EvalLog],
    columns: Sequence[Column],
    *,
    full: bool = False,
    strict: bool = True,
    detail: MessagesDetail | EventsDetail | None = None,
    progress: bool = True,
    parallel: bool | int = False,
) -> "pd.DataFrame" | tuple["pd.DataFrame", list[ColumnError]]:
    import pandas as pd

    # Parallel only makes sense for path-based reads
    is_paths = len(logs) == 0 or isinstance(logs[0], str)

    if parallel and is_paths:
        # resolve number of workers (cap at 8 as eventually we run into disk/memory contention)
        if parallel is True:
            parallel = max(min(mp.cpu_count(), 8), 2)

        log_paths = cast(list[str], logs)

        # establish progress
        entity = detail.name if detail else "sample"
        progress_cm = (
            import_progress(f"reading {entity}s", total=len(log_paths))
            if progress
            else no_progress()
        )

        # run the parallel reads (setup arrays for holding results in order)
        df_results: list[pd.DataFrame | None] = [None] * len(log_paths)
        error_results: list[list[ColumnError] | None] = [None] * len(log_paths)
        executor = ProcessPoolExecutor(max_workers=parallel)
        try:
            with progress_cm as p:
                futures = {
                    executor.submit(
                        _read_samples_df_serial,  # type: ignore[arg-type]
                        logs=[log_path],
                        columns=columns,
                        full=full,
                        strict=strict,
                        detail=detail,
                        progress=False,
                    ): idx
                    for idx, log_path in enumerate(log_paths)
                }
                for fut in as_completed(futures):
                    idx = futures[fut]
                    if strict:
                        df_results[idx] = cast(pd.DataFrame, fut.result())
                    else:
                        df, errs = cast(
                            tuple[pd.DataFrame, list[ColumnError]], fut.result()
                        )
                        df_results[idx] = df
                        error_results[idx] = errs
                    p.update()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        # recombine df
        df = pd.concat(df_results, ignore_index=True)
        subset = f"{detail.name}_id" if detail else SAMPLE_ID
        try:
            df.drop_duplicates(subset=subset, ignore_index=True, inplace=True)
        except Exception as e:
            # Check if it's specifically the pyarrow offset overflow error
            if "offset overflow" in str(e):
                # Convert to large_string and retry
                df = _convert_to_large_string(df)
                df.drop_duplicates(subset=subset, ignore_index=True, inplace=True)
            else:
                raise

        # recombine errors
        errors: list[ColumnError] = list(
            chain.from_iterable(e for e in error_results if e)
        )

        # return as required
        if strict:
            return df
        else:
            return df, errors

    # non-parallel (or EvalLog objects which don't benefit from parallel)
    else:
        return _read_samples_df_serial(
            logs=logs,
            columns=columns,
            full=full,
            strict=strict,
            detail=detail,
            progress=progress,
        )


def _read_samples_df_serial(
    logs: list[str] | list[EvalLog],
    columns: Sequence[Column],
    *,
    full: bool = False,
    strict: bool = True,
    detail: MessagesDetail | EventsDetail | None = None,
    progress: bool = True,
) -> "pd.DataFrame" | tuple["pd.DataFrame", list[ColumnError]]:
    # split columns by type
    columns_eval: list[Column] = []
    columns_sample: list[Column] = []
    columns_detail: list[Column] = []
    for column in columns:
        if isinstance(column, EvalColumn):
            columns_eval.append(column)
        elif isinstance(column, SampleColumn):
            if full and not column._full and (column.name == "metadata_*"):
                column = deepcopy(column)
                column._full = True
            columns_sample.append(column)
            if column._full:
                require_full_samples = True
        elif detail and isinstance(column, detail.col_type):
            columns_detail.append(column)
        else:
            raise ValueError(
                f"Unexpected column type passed to samples_df: {type(column)}"
            )
    # resolve duplicates
    columns_eval = resolve_duplicate_columns(columns_eval)
    columns_sample = resolve_duplicate_columns(columns_sample)
    columns_detail = resolve_duplicate_columns(columns_detail)

    # determine if we require full samples
    require_full_samples = len(columns_detail) > 0 or any(
        [isinstance(column, SampleColumn) and column._full for column in columns_sample]
    )

    # make sure eval_id is present
    columns_eval = list(ensure_eval_data(columns_eval))

    # determine if we have paths or EvalLog objects
    is_eval_logs = len(logs) > 0 and isinstance(logs[0], EvalLog)

    # establish progress
    progress_cm = (
        import_progress("scanning logs", total=len(logs)) if progress else no_progress()
    )

    # determine how we will allocate progress
    with progress_cm as p:
        # read samples from each log
        sample_records: list[dict[str, ColumnType]] = []
        detail_records: list[dict[str, ColumnType]] = []
        all_errors: list[ColumnError] = []

        # read logs and note total samples
        evals_table, eval_logs, total_samples = _read_evals_df(
            logs, columns=columns_eval, strict=True, progress=p.update
        )

        # update progress now that we know the total samples
        entity = detail.name if detail else "sample"
        p.reset(description=f"reading {entity}s", completed=0, total=total_samples)

        # read samples
        async def read_samples_async(
            eval_id: str, eval_log: EvalLog, async_fs: AsyncFilesystem
        ) -> Iterable[EvalSample | EvalSampleSummary]:
            # get samples (in-memory, full log, or summaries from disk)
            if (
                is_eval_logs
                and eval_log.samples is not None
                and len(eval_log.samples) > 0
            ):
                samples: Iterable[EvalSample | EvalSampleSummary] = eval_log.samples
            elif require_full_samples:
                full_log = await read_eval_log_async(
                    eval_log.location, resolve_attachments=True, async_fs=async_fs
                )
                samples = full_log.samples or []
            else:
                samples = await read_eval_log_sample_summaries_async(
                    eval_log.location, async_fs=async_fs
                )
            p.update()
            return samples

        log_samples = run_tg_collect_with_fs(
            [
                partial(read_samples_async, eval_id, eval_log)
                for eval_id, eval_log in zip(evals_table[EVAL_ID].to_list(), eval_logs)
            ]
        )

        for samples, eval_id, eval_log in zip(
            log_samples, evals_table[EVAL_ID].to_list(), eval_logs
        ):
            for sample in samples:
                if strict:
                    record = import_record(
                        eval_log, sample, columns_sample, strict=True
                    )
                else:
                    record, errors = import_record(
                        eval_log, sample, columns_sample, strict=False
                    )
                    all_errors.extend(errors)

                # inject ids
                sample_id = sample.uuid or auto_sample_id(eval_id, sample)
                ids: dict[str, ColumnType] = {
                    EVAL_ID: eval_id,
                    SAMPLE_ID: sample_id,
                }

                # record with ids
                record = ids | record

                # if there are detail columns then blow out w/ detail
                if detail is not None:
                    # filter detail records
                    assert isinstance(sample, EvalSample)
                    if isinstance(detail, MessagesDetail):
                        detail_items: list[ChatMessage] | list[Event] = (
                            sample_messages_from_events(sample.events, detail.filter)
                        )
                    elif isinstance(detail, EventsDetail):
                        detail_items = [
                            e
                            for e in sample.events
                            if detail.filter is None or detail.filter(e)
                        ]
                    else:
                        detail_items = []

                    # read detail records (provide auto-ids)
                    for index, item in enumerate(detail_items):
                        if strict:
                            detail_record = import_record(
                                eval_log,
                                item,
                                columns_detail,
                                strict=True,
                            )
                        else:
                            detail_record, errors = import_record(
                                eval_log,
                                item,
                                columns_detail,
                                strict=False,
                            )
                            all_errors.extend(errors)

                        # ensure ids
                        detail_id_field = f"{detail.name}_id"
                        detail_id = detail_record.get(detail_id_field, None)
                        if detail_id is None:
                            detail_record[detail_id_field] = auto_detail_id(
                                sample_id, detail.name, index
                            )
                        ids = {SAMPLE_ID: sample_id}
                        detail_record = ids | detail_record

                        # inject order
                        detail_record["order"] = index + 1

                        # append detail record
                        detail_records.append(detail_record)

                # record sample record
                sample_records.append(record)

    # normalize records and produce samples table
    samples_table = records_to_pandas(sample_records)
    samples_table.drop_duplicates(
        "sample_id", keep="first", inplace=True, ignore_index=True
    )

    # if we have detail records then join them into the samples table
    if detail is not None:
        details_table = records_to_pandas(detail_records)
        details_table.drop_duplicates(
            f"{detail.name}_id", keep="first", inplace=True, ignore_index=True
        )
        if len(details_table) > 0:
            samples_table = details_table.merge(
                samples_table,
                on=SAMPLE_ID,
                how="left",
                suffixes=(f"_{detail.name}", SAMPLE_SUFFIX),
            )

    # join eval_records
    if len(samples_table) > 0:
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
    events: list[Event], filter: Callable[[ChatMessage], bool] | None
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

    # remove duplicated assistant messages (can happen in agent bridge or any other
    # time that the message list is fully re-constituted)
    messages = functools.reduce(duplicate_assistant_message_reducer, messages, [])

    # then apply the filter
    return [message for message in messages if filter is None or filter(message)]


def duplicate_assistant_message_reducer(
    messages: list[ChatMessage],
    message: ChatMessage,
) -> list[ChatMessage]:
    if (
        message.role == "assistant"
        and len(messages) > 0
        and messages[-1].role == "assistant"
        and message.text == messages[-1].text
        and [tool.function for tool in (message.tool_calls or [])]
        == [tool.function for tool in (messages[-1].tool_calls or [])]
    ):
        return messages
    else:
        messages.append(message)
        return messages


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


def _convert_to_large_string(df: "pd.DataFrame") -> "pd.DataFrame":
    """Convert PyArrow string columns to large_string to avoid offset overflow.

    PyArrow's default string type uses 32-bit offsets, which limits total string
    data to ~2GB. This function converts string columns to large_string (64-bit
    offsets) to handle larger datasets.

    Only columns that are approaching or exceeding the 2GB limit are converted.

    Args:
        df: DataFrame with potential PyArrow string columns

    Returns:
        DataFrame with string columns converted to large_string where needed
    """
    import pandas as pd
    import pyarrow as pa

    # 2^31 bytes is the limit for 32-bit offsets
    # Use a threshold of 1.5GB to catch columns that might be close
    SIZE_THRESHOLD = int(1.5 * 1024**3)

    # Build a new DataFrame with converted columns
    new_columns: dict[str, Any] = {}
    for col in df.columns:
        # Check if this is a PyArrow-backed column
        col_dtype = df[col].dtype
        if hasattr(col_dtype, "pyarrow_dtype"):
            dtype = col_dtype.pyarrow_dtype  # type: ignore[attr-defined]
            if pa.types.is_string(dtype):
                # Check the size of this column's string data
                col_array = df[col].array
                if hasattr(col_array, "_pa_array"):
                    arrow_array = col_array._pa_array  # type: ignore[attr-defined]
                    # Get the total size of string data in this column
                    total_size = arrow_array.nbytes
                    # Only convert if this column is large enough to potentially cause issues
                    if total_size > SIZE_THRESHOLD:
                        large_string_array = arrow_array.cast(pa.large_string())
                        new_columns[col] = pd.arrays.ArrowExtensionArray(  # type: ignore[attr-defined]
                            large_string_array
                        )
                        continue
        # Keep original column if not converted
        new_columns[col] = df[col]

    return pd.DataFrame(new_columns, index=df.index)
