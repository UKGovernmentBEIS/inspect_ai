from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Literal, TypeAlias

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
    logs: LogPaths,
    columns: list[Column],
    filter: EventFilter | None = None,
    recursive: bool = True,
    strict: Literal[True] = True,
) -> "pd.DataFrame": ...


@overload
def events_df(
    logs: LogPaths,
    columns: list[Column],
    filter: EventFilter | None = None,
    recursive: bool = True,
    strict: Literal[False] = False,
) -> tuple["pd.DataFrame", ColumnErrors]: ...


def events_df(
    logs: LogPaths,
    columns: list[Column],
    filter: EventFilter | None = None,
    recursive: bool = True,
    strict: bool = True,
) -> "pd.DataFrame" | tuple["pd.DataFrame", ColumnErrors]:
    """Read a dataframe containing events from a set of evals.

    Args:
       logs: One or more paths to log files or log directories.
       columns: Specification for what columns to read from log files.
       filter: List of event types to include or callable that performs the filter.
       recursive: Include recursive contents of directories (defaults to `True`)
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
        recursive=recursive,
        strict=strict,
        detail=detail,
    )
