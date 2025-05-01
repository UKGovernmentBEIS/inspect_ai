from datetime import date, datetime, time
from typing import Type, TypeAlias, TypedDict

from jsonpath_ng import JSONPath  # type: ignore

FieldType: TypeAlias = int | float | bool | str | date | time | datetime | None
"""Valid types for fields.

Values of `list` and `dict` are read by converting them to JSON `str`.
"""


class FieldOptions(TypedDict, total=False):
    """Options for importing and converting fields."""

    required: bool
    """Is the field required? (error is raised if required fields aren't found)."""

    type: Type[FieldType] | None
    """Field type (import will attempt to coerce to the specified type)."""


FieldSpec: TypeAlias = str | JSONPath | tuple[str | JSONPath, FieldOptions]
"""Field specification.

Field specifications are expressed as [JSONPath](https://github.com/h2non/jsonpath-ng) expressions.

Fields can be specified by expression or`JSONPath` object. Field import options can be specified by passing a `tuple` of the field path and `FieldOptions`.
"""

ImportSpec: TypeAlias = dict[str, FieldSpec]
"""Specification of fields reading eval logs into a data frame."""
