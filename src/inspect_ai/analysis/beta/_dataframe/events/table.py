from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Literal, TypeAlias

from inspect_ai.analysis.beta._dataframe.events.columns import EventInfo
from inspect_ai.log._file import list_eval_logs
from inspect_ai.log._transcript import Event

if TYPE_CHECKING:
    import pandas as pd

from typing_extensions import overload

from ..columns import Column, ColumnErrors
from ..samples.table import EventsDetail, _read_samples_df
from ..util import LogPaths, verify_prerequisites

EventFilter: TypeAlias = (
    list[
        Literal[
            "sample_init",
            "sample_limit",
            "sandbox",
            "state",
            "store",
            "model",
            "tool",
            "sandbox",
            "approval",
            "input",
            "score",
            "error",
            "logger",
            "info",
            "span_begin",
            "span_end",
            "subtask",
        ]
    ]
    | Callable[[Event], bool]
)
"""Filter for `events_df()` rows."""


@overload
def events_df(
    logs: LogPaths = list_eval_logs(),
    columns: list[Column] = EventInfo,
    filter: EventFilter | None = None,
    strict: Literal[True] = True,
) -> "pd.DataFrame": ...


@overload
def events_df(
    logs: LogPaths = list_eval_logs(),
    columns: list[Column] = EventInfo,
    filter: EventFilter | None = None,
    strict: Literal[False] = False,
) -> tuple["pd.DataFrame", ColumnErrors]: ...


def events_df(
    logs: LogPaths = list_eval_logs(),
    columns: list[Column] = EventInfo,
    filter: EventFilter | None = None,
    strict: bool = True,
) -> "pd.DataFrame" | tuple["pd.DataFrame", ColumnErrors]:
    """Read a dataframe containing events from a set of evals.

    Args:
       logs: One or more paths to log files or log directories.
          Defaults to the contents of the currently active log directory
          (e.g. ./logs or INSPECT_LOG_DIR).
       columns: Specification for what columns to read from log files.
       filter: List of event types to include or callable that performs the filter.
       strict: Raise import errors immediately. Defaults to `True`.
          If `False` then a tuple of `DataFrame` and errors is returned.

    Returns:
       For `strict`, a Pandas `DataFrame` with information for the specified logs.
       For `strict=False`, a tuple of Pandas `DataFrame` and a dictionary of errors
       encountered (by log file) during import.
    """
    verify_prerequisites()

    # resolve filter/detail
    if filter is None:
        detail = EventsDetail(filter=lambda e: True)
    elif callable(filter):
        detail = EventsDetail(filter=filter)
    else:
        detail = EventsDetail(filter=lambda e: e.event in filter)

    return _read_samples_df(
        logs=logs,
        columns=columns,
        strict=strict,
        detail=detail,
    )
