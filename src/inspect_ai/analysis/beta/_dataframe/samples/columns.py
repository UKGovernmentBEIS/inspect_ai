from typing import Any, Callable, Mapping, Type

from jsonpath_ng import JSONPath  # type: ignore
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai.log._log import EvalSample, EvalSampleSummary

from ..columns import Column, ColumnType
from ..extract import input_as_str, list_as_str, score_values
from ..validate import resolved_schema
from .extract import sample_messages_as_str, sample_path_requires_full


class SampleColumn(Column):
    """Column which maps to `EvalSample` or `EvalSampleSummary`."""

    def __init__(
        self,
        name: str,
        *,
        path: str
        | JSONPath
        | Callable[[EvalSampleSummary], JsonValue]
        | Callable[[EvalSample], JsonValue],
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
        )
        self._extract_sample = path if callable(path) else None
        self._full = full or sample_path_requires_full(path)

    @override
    def path_schema(self) -> Mapping[str, Any]:
        if self._full:
            return self.full_schema
        else:
            return self.summary_schema

    summary_schema = resolved_schema(EvalSampleSummary)
    full_schema = resolved_schema(EvalSample)


SampleSummary: list[Column] = [
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

SampleMessages: list[Column] = [
    SampleColumn("messages", path=sample_messages_as_str, required=True, full=True)
]
"""Sample messages as a string."""
