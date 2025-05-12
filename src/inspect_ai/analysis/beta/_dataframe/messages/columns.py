from typing import Any, Callable, Mapping, Type

from jsonpath_ng import JSONPath  # type: ignore
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai.model._chat_message import ChatMessage

from ..columns import Column, ColumnType
from .extract import (
    message_text,
    message_tool_calls,
)


class MessageColumn(Column):
    """Column which maps to `ChatMessage`."""

    def __init__(
        self,
        name: str,
        *,
        path: str | JSONPath | Callable[[ChatMessage], JsonValue],
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
        self._extract_message = path if callable(path) else None

    @override
    def path_schema(self) -> Mapping[str, Any] | None:
        return None


MessageContent: list[Column] = [
    MessageColumn("role", path="role", required=True),
    MessageColumn("source", path="source"),
    MessageColumn("content", path=message_text),
]
"""Message content columns."""

MessageToolCalls: list[Column] = [
    MessageColumn("tool_calls", path=message_tool_calls),
    MessageColumn("tool_call_id", path="tool_call_id"),
    MessageColumn("tool_call_function", path="function"),
    MessageColumn("tool_call_error", path="error.message"),
]
"""Message tool call columns."""

MessageColumns: list[Column] = MessageContent + MessageToolCalls
"""Chat message columns."""
