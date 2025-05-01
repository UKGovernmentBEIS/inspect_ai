from datetime import date, datetime, time
from typing import Type, TypeAlias, TypedDict

from jsonpath_ng import JSONPath  # type: ignore

FieldType: TypeAlias = int | float | bool | str | date | time | datetime | None


class FieldOptions(TypedDict, total=False):
    required: bool
    type: Type[FieldType] | None


FieldSpec: TypeAlias = str | JSONPath | tuple[str | JSONPath, FieldOptions]

ImportSpec: TypeAlias = dict[str, FieldSpec]


EvalDefault: ImportSpec = {
    "status": "$.status",
    "error": ("$.error.message"),
    "model": "$.eval.model",
    "task_arg_*": "$.eval.task_args",
}
