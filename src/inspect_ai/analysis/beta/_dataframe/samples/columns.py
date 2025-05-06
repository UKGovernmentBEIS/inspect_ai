from typing import Callable, Type

from jsonpath_ng import JSONPath  # type: ignore
from pydantic import JsonValue

from inspect_ai.log._log import EvalSampleSummary

from ..columns import Column, ColumnType
from ..extract import input_as_str, list_as_str, score_values


class SampleColumn(Column):
    def __init__(
        self,
        name: str,
        *,
        path: str | JSONPath | Callable[[EvalSampleSummary], JsonValue],
        required: bool = False,
        default: JsonValue | None = None,
        type: Type[ColumnType] | None = None,
        value: Callable[[JsonValue], JsonValue] | None = None,
        full: bool = False,
    ) -> None:
        super().__init__(
            name=name,
            path=path if not callable(path) else None,
            required=required,
            default=default,
            type=type,
            value=value,
            root="sample",
        )
        self._extract_sample = path if callable(path) else None
        self._full = full


SampleSummary = [
    SampleColumn("id", path="id", required=True, type=str),
    SampleColumn("epoch", path="epoch", required=True),
    SampleColumn("input", path="input", required=True, value=input_as_str),
    SampleColumn("target", path="target", required=True, value=list_as_str),
    SampleColumn("metadata_*", path="metadata"),
    SampleColumn("score_*", path="scores", value=score_values),
    SampleColumn("model_usage", path="model_usage"),
    SampleColumn("total_time", path="total_time"),
    SampleColumn("working_time", path="total_time"),
    SampleColumn("error", path="error"),
    SampleColumn("limit", path="limit"),
    SampleColumn("retries", path="retries"),
]
"""Sample summary columns."""
