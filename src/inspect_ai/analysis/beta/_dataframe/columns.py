from copy import deepcopy
from dataclasses import KW_ONLY, dataclass
from datetime import date, datetime, time
from typing import Any, Callable, Mapping, Type, TypeAlias

from jsonpath_ng import JSONPath  # type: ignore
from jsonpath_ng.ext import parse  # type: ignore
from pydantic import JsonValue
from typing_extensions import Literal

from inspect_ai.log._log import EvalLog

from .validate import jsonpath_in_schema

ColumnType: TypeAlias = int | float | bool | str | date | time | datetime | None
"""Valid types for columns.

Values of `list` and `dict` are converted into column values as JSON `str`.
"""


class Column:
    """
    Specification for importing a column into a data frame.

    Extract columns from an `EvalLog` either using [JSONPath](https://github.com/h2non/jsonpath-ng) expressions
    or a function that takes `EvalLog` and returns a value.

    By default, columns are not required, pass `required=True` to make them required. Non-required
    columns are extracted as `None`, provide a `default` to yield an alternate value.

    The `type` option serves as both a validation check and a directive to attempt to coerce the
    data into the specified `type`. Coercion from `str` to other types is done after interpreting
    the string using YAML (e.g. `"true"` -> `True`).

    The `value` function provides an additional hook for transformation of the value read
    from the log before it is realized as a column (e.g. list to a comma-separated string).

    The `validate` option controls whether the specified JSONPath is validated against the
    log file schema.

    The `root` option indicates which root eval log context the columns select from.
    """

    def __init__(
        self,
        extract: str | JSONPath | Callable[[EvalLog], JsonValue],
        *,
        required: bool = False,
        default: JsonValue | None = None,
        type: Type[ColumnType] | None = None,
        value: Callable[[JsonValue], JsonValue] | None = None,
        validate: bool = True,
        root: Literal["eval", "sample", "message", "event"] = "eval",
    ) -> None:
        if isinstance(extract, str | JSONPath):
            self._path: str | JSONPath | None = extract
            self._extract: Callable[[EvalLog], JsonValue] | None = None
        else:
            self._path = None
            self._extract = extract
        self._required = required
        self._default = default
        self._type = type
        self._value = value
        self._validate = validate
        self._validated: bool | None = None
        self._root = root

    @property
    def path(self) -> JSONPath | None:
        """Path to column in `EvalLog`"""
        if isinstance(self._path, str):
            self._path = parse(self._path)
        return self._path

    @property
    def extract(self) -> Callable[[EvalLog], JsonValue] | None:
        """Function that extracts column value from `EvalLog`"""
        return self._extract

    @property
    def required(self) -> bool:
        """Is the column required? (error is raised if required columns aren't found)."""
        return self._required

    @property
    def default(self) -> JsonValue | None:
        """Default value for column when it is read from the log as `None`."""
        return self._default

    @property
    def type(self) -> Type[ColumnType] | None:
        """Column type (import will attempt to coerce to the specified type)."""
        return self._type

    def value(self, x: JsonValue) -> JsonValue:
        """Convert extracted value into a column value (defaults to identity function).

        Params:
            x: Value to convert.

        Returns:
            Converted value.
        """
        if self._value:
            return self._value(x)
        else:
            return x

    def validate_path(self, schema: Mapping[str, Any]) -> bool:
        if self._validate and self.path is not None:
            if self._validated is None:
                self._validated = jsonpath_in_schema(self.path, schema)
            return self._validated
        else:
            return True


class ColumnsSet(dict[str, Column]):
    def __init__(
        self,
        root: Literal["eval", "sample", "message", "event"],
        columns: dict[str, Column] | None = None,
    ) -> None:
        self._root = root
        columns_with_root: dict[str, Column] = {}
        if columns:
            for key, value in columns.items():
                column = deepcopy(value)
                column._root = root
                columns_with_root[key] = column
        super().__init__(columns_with_root)

    # def __or__(self, other: dict[str, Column]) -> dict[str, Column]:
    #     result = ColumnsSet(self._root)
    #     result.update(self)
    #     result.update(other)

    #     return result


Columns: TypeAlias = dict[str, Column]
"""Specification of columns to read from eval log into data frame."""


@dataclass
class ColumnError:
    """Error which occurred parsing a column."""

    column: str
    """Target column name."""

    _: KW_ONLY

    path: str | None
    """Path to select column value. """

    message: str
    """Error message."""

    def __str__(self) -> str:
        msg = f"Error reading column '{self.column}'"
        if self.path:
            msg = f"{msg} from path '{self.path}'"
        return f"{msg}: {self.message}"


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
