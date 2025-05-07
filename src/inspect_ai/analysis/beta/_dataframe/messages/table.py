from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import pandas as pd

from typing_extensions import overload

from ..columns import Column, ColumnErrors
from ..samples.table import MessagesDetail, _read_samples_df
from ..util import LogPaths, verify_prerequisites
from .columns import MessageColumns


@overload
def messages_df(
    logs: LogPaths,
    columns: list[Column] = MessageColumns,
    recursive: bool = True,
    reverse: bool = False,
    strict: Literal[True] = True,
) -> "pd.DataFrame": ...


@overload
def messages_df(
    logs: LogPaths,
    columns: list[Column] = MessageColumns,
    recursive: bool = True,
    reverse: bool = False,
    strict: Literal[False] = False,
) -> tuple["pd.DataFrame", ColumnErrors]: ...


def messages_df(
    logs: LogPaths,
    columns: list[Column] = MessageColumns,
    recursive: bool = True,
    reverse: bool = False,
    strict: bool = True,
) -> "pd.DataFrame" | tuple["pd.DataFrame", ColumnErrors]:
    """Read a dataframe containing messages from a set of evals.

    Args:
       logs: One or more paths to log files or log directories.
       columns: Specification for what columns to read from log files.
       recursive: Include recursive contents of directories (defaults to `True`)
       reverse: Reverse the order of the data frame (by default, items
          are ordered from oldest to newest).
       strict: Raise import errors immediately. Defaults to `True`.
          If `False` then a tuple of `DataFrame` and errors is returned.

    Returns:
       For `strict`, a Pandas `DataFrame` with information for the specified logs.
       For `strict=False`, a tuple of Pandas `DataFrame` and a dictionary of errors
       encountered (by log file) during import.
    """
    verify_prerequisites()

    return _read_samples_df(
        logs=logs,
        columns=columns,
        recursive=recursive,
        reverse=reverse,
        strict=strict,
        detail=MessagesDetail(),
    )
