from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Literal, Sequence, TypeAlias

from inspect_ai.log._file import list_eval_logs
from inspect_ai.model._chat_message import ChatMessage

if TYPE_CHECKING:
    import pandas as pd

from typing_extensions import overload

from ..columns import Column, ColumnErrors
from ..samples.table import MessagesDetail, _read_samples_df
from ..util import LogPaths, verify_prerequisites
from .columns import MessageColumns

MessageFilter: TypeAlias = (
    list[Literal["system", "user", "assistant", "tool"]] | Callable[[ChatMessage], bool]
)
"""Filter for `messages_df()` rows."""


@overload
def messages_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = MessageColumns,
    filter: MessageFilter | None = None,
    strict: Literal[True] = True,
) -> "pd.DataFrame": ...


@overload
def messages_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = MessageColumns,
    filter: MessageFilter | None = None,
    strict: Literal[False] = False,
) -> tuple["pd.DataFrame", ColumnErrors]: ...


def messages_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = MessageColumns,
    filter: MessageFilter | None = None,
    strict: bool = True,
) -> "pd.DataFrame" | tuple["pd.DataFrame", ColumnErrors]:
    """Read a dataframe containing messages from a set of evals.

    Args:
       logs: One or more paths to log files or log directories.
          Defaults to the contents of the currently active log directory
          (e.g. ./logs or INSPECT_LOG_DIR).
       columns: Specification for what columns to read from log files.
       filter: List of message role types to include or callable that performs the filter.
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
        detail = MessagesDetail(filter=lambda m: True)
    elif callable(filter):
        detail = MessagesDetail(filter=filter)
    else:
        detail = MessagesDetail(filter=lambda m: m.role in filter)

    return _read_samples_df(
        logs=logs,
        columns=columns,
        strict=strict,
        detail=detail,
    )
