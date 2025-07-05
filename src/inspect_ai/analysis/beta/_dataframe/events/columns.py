from datetime import datetime
from typing import Any, Callable, Mapping, Type

from jsonpath_ng import JSONPath  # type: ignore
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai.log._transcript import Event

from ..columns import Column, ColumnType
from .extract import (
    completion_as_str,
    model_event_input_as_str,
    tool_choice_as_str,
    tool_view_as_str,
)


class EventColumn(Column):
    """Column which maps to `Event`."""

    def __init__(
        self,
        name: str,
        *,
        path: str | JSONPath | Callable[[Event], JsonValue],
        required: bool = False,
        default: JsonValue | None = None,
        type: Type[ColumnType] | None = None,
        value: Callable[[JsonValue], JsonValue] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            path=path if not callable(path) else None,
            required=required,
            default=default,
            type=type,
            value=value,
        )
        self._extract_event = path if callable(path) else None

    @override
    def path_schema(self) -> Mapping[str, Any] | None:
        return None


EventInfo: list[Column] = [
    EventColumn("event_id", path="uuid"),
    EventColumn("event", path="event"),
    EventColumn("span_id", path="span_id"),
]
"""Event basic information columns."""

EventTiming: list[Column] = [
    EventColumn("timestamp", path="timestamp", type=datetime),
    EventColumn("completed", path="completed", type=datetime),
    EventColumn("working_start", path="working_start"),
    EventColumn("working_time", path="working_time"),
]
"""Event timing columns."""

ModelEventColumns: list[Column] = [
    EventColumn("model_event_model", path="model"),
    EventColumn("model_event_role", path="role"),
    EventColumn("model_event_input", path=model_event_input_as_str),
    EventColumn("model_event_tools", path="tools"),
    EventColumn("model_event_tool_choice", path=tool_choice_as_str),
    EventColumn("model_event_config", path="config"),
    EventColumn("model_event_usage", path="output.usage"),
    EventColumn("model_event_time", path="output.time"),
    EventColumn("model_event_completion", path=completion_as_str),
    EventColumn("model_event_retries", path="retries"),
    EventColumn("model_event_error", path="error"),
    EventColumn("model_event_cache", path="cache"),
    EventColumn("model_event_call", path="call"),
]
"""Model event columns."""

ToolEventColumns: list[Column] = [
    EventColumn("tool_event_function", path="function"),
    EventColumn("tool_event_arguments", path="arguments"),
    EventColumn("tool_event_view", path=tool_view_as_str),
    EventColumn("tool_event_result", path="result"),
    EventColumn("tool_event_truncated", path="truncated"),
    EventColumn("tool_event_error_type", path="error.type"),
    EventColumn("tool_event_error_message", path="error.message"),
]
"""Tool event columns."""
