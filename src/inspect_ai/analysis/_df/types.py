from dataclasses import KW_ONLY, dataclass
from datetime import date, datetime, time
from typing import Type, TypeAlias

from jsonpath_ng import JSONPath  # type: ignore
from jsonpath_ng.ext import parse  # type: ignore

ColumnType: TypeAlias = int | float | bool | str | date | time | datetime | None
"""Valid types for columns.

Values of `list` and `dict` are read by converting them to JSON `str`.
"""


class Column:
    """
    Specification for importing a column into a data frame.

    Paths to columns within the `EvalLog` are expressed as [JSONPath](https://github.com/h2non/jsonpath-ng) expressions.
    """

    def __init__(
        self,
        path: str | JSONPath,
        *,
        required: bool = False,
        type: Type[ColumnType] | None = None,
    ) -> None:
        self._path = path
        self._required = required
        self._type = type

    @property
    def path(self) -> JSONPath:
        """Path to column in `EvalLog`"""
        if isinstance(self._path, str):
            self._path = parse(self._path)
        return self._path

    @property
    def required(self) -> bool:
        """Is the column required? (error is raised if required columns aren't found)."""
        return self._required

    @property
    def type(self) -> Type[ColumnType] | None:
        """Column type (import will attempt to coerce to the specified type)."""
        return self._type


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
