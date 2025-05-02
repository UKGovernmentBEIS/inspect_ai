from dataclasses import KW_ONLY, dataclass
from datetime import date, datetime, time
from typing import Callable, Type, TypeAlias

from jsonpath_ng import JSONPath  # type: ignore
from jsonpath_ng.ext import parse  # type: ignore
from pydantic import JsonValue

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
        value: Callable[[JsonValue], JsonValue] | None = None,
    ) -> None:
        self._path = path
        self._required = required
        self._type = type
        self._value = value

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

    def value(self, x: JsonValue) -> JsonValue:
        """Convert extracted value into a column value (defaults to identity function)."""
        if self._value:
            return self._value(x)
        else:
            return x


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
    """Dictionary of column errors keyed by log file."""

    def __str__(self) -> str:
        lines: list[str] = [""]
        for file, errors in self.items():
            lines.append(file)
            for error in errors:
                lines.append(f" - {error}")
            lines.append("")
        return "\n".join(lines)
