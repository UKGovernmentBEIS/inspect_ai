from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Literal, Sequence, TypeAlias

from inspect_ai.analysis.beta._dataframe.events.columns import EventInfo
from inspect_ai.log._file import list_eval_logs
from inspect_ai.log._transcript import Event

if TYPE_CHECKING:
    import pandas as pd

from typing_extensions import overload

from ..columns import Column, ColumnError
from ..samples.table import EventsDetail, _read_samples_df
from ..util import LogPaths, verify_prerequisites

EventFilter: TypeAlias = Callable[[Event], bool]
"""Filter for `events_df()` rows."""


@overload
def events_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = EventInfo,
    filter: EventFilter | None = None,
    strict: Literal[True] = True,
    parallel: bool | int = False,
    quiet: bool = False,
) -> "pd.DataFrame": ...


@overload
def events_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = EventInfo,
    filter: EventFilter | None = None,
    strict: Literal[False] = False,
    parallel: bool | int = False,
    quiet: bool = False,
) -> tuple["pd.DataFrame", list[ColumnError]]: ...


def events_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = EventInfo,
    filter: EventFilter | None = None,
    strict: bool = True,
    parallel: bool | int = False,
    quiet: bool = False,
) -> "pd.DataFrame" | tuple["pd.DataFrame", list[ColumnError]]:
    """Read a dataframe containing events from a set of evals.

    Args:
       logs: One or more paths to log files or log directories.
          Defaults to the contents of the currently active log directory
          (e.g. ./logs or INSPECT_LOG_DIR).
       columns: Specification for what columns to read from log files.
       filter: Callable that filters event types.
       strict: Raise import errors immediately. Defaults to `True`.
          If `False` then a tuple of `DataFrame` and errors is returned.
       parallel: If `True`, use `ProcessPoolExecutor` to read logs in parallel
          (with workers based on `mp.cpu_count()`, capped at 8). If `int`, read
          in parallel with the specified number of workers. If `False` (the default)
          do not read in parallel.
       quiet: If `True` do not print any output or progress (defaults to `False`).

    Returns:
       For `strict`, a Pandas `DataFrame` with information for the specified logs.
       For `strict=False`, a tuple of Pandas `DataFrame` and a dictionary of errors
       encountered (by log file) during import.
    """
    verify_prerequisites()

    # resolve filter/detail
    if callable(filter):
        detail = EventsDetail(filter=filter)
    else:
        detail = EventsDetail()

    return _read_samples_df(
        logs=logs,
        columns=columns,
        strict=strict,
        detail=detail,
        progress=not quiet,
        parallel=parallel,
    )
