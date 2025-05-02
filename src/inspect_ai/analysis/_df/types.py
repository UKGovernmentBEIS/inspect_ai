from dataclasses import KW_ONLY, dataclass, field
from datetime import date, datetime, time
from typing import Type, TypeAlias

from jsonpath_ng import JSONPath  # type: ignore

ColumnType: TypeAlias = int | float | bool | str | date | time | datetime | None
"""Valid types for columns.

Values of `list` and `dict` are read by converting them to JSON `str`.
"""


@dataclass
class Column:
    path: str | JSONPath
    """Extract column value using this path.

    Column specifications are expressed as [JSONPath](https://github.com/h2non/jsonpath-ng) expressions.
    """
    _: KW_ONLY

    required: bool = field(default=False)
    """Is the field required? (error is raised if required fields aren't found)."""

    type: Type[ColumnType] | None = field(default=None)
    """Field type (import will attempt to coerce to the specified type)."""


Columns: TypeAlias = dict[str, Column]
"""Specification of columns to read from eval log into data frame."""


@dataclass
class ColumnError:
    """Error which occurred parsing a column."""

    column: str
    """Target column name."""

    _: KW_ONLY

    path: str
    """Path to select column value. """

    message: str
    """Error message."""

    def __str__(self) -> str:
        return f"Error reading column '{self.column}' from path '{self.path}': {self.message}"


class ColumnErrors(dict[str, list[ColumnError]]):
    pass
