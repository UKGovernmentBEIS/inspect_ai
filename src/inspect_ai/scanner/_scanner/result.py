from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue

from inspect_ai._util.json import to_json_str_safe


class Reference(BaseModel):
    """Reference to scanned content."""

    type: Literal["message", "event"]
    """Reference type."""

    id: str
    """Reference id (message or event id)"""


class Result(BaseModel):
    """Scanner result."""

    value: JsonValue
    """Scanner value."""

    answer: str | None = Field(default=None)
    """Answer extracted from model output (optional)"""

    explanation: str | None = Field(default=None)
    """Explanation of result (optional)."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional metadata related to the result"""

    references: list[Reference] = Field(default_factory=list)
    """References to relevant messages or events."""


class ResultReport(BaseModel):
    input_type: Literal["transcript", "event", "message"]

    input_id: str

    result: Result

    def to_df_columns(self) -> dict[str, str | bool | int | float | None]:
        columns: dict[str, str | bool | int | float | None] = {}

        columns["input_type"] = self.input_type
        columns["input_id"] = self.input_id

        if isinstance(self.result.value, str | bool | int | float | None):
            columns["value"] = self.result.value
            if isinstance(self.result.value, str):
                columns["value_type"] = "string"
            elif isinstance(self.result.value, int | float):
                columns["value_type"] = "number"
            elif isinstance(self.result.value, bool):
                columns["value_type"] = "boolean"
            else:
                columns["value_type"] = "null"

        else:
            columns["value"] = to_json_str_safe(self.result.value)
            columns["value_type"] = (
                "array" if isinstance(self.result.value, list) else "object"
            )

        columns["answer"] = self.result.answer or ""
        columns["explanation"] = self.result.explanation or ""
        columns["metadata"] = to_json_str_safe(self.result.metadata or {})
        columns["references"] = to_json_str_safe(self.result.references)
        return columns
