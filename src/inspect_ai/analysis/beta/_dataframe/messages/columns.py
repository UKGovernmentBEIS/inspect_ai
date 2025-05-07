from typing import Any, Callable, Mapping, Type

from jsonpath_ng import JSONPath  # type: ignore
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai._util.format import format_function_call
from inspect_ai.model._chat_message import ChatMessage, ChatMessageAssistant

from ..columns import Column, ColumnType


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


def message_text(message: ChatMessage) -> str:
    return message.text


def message_tool_calls(message: ChatMessage) -> str | None:
    if isinstance(message, ChatMessageAssistant) and message.tool_calls is not None:
        tool_calls = "\n".join(
            [
                format_function_call(
                    tool_call.function, tool_call.arguments, width=1000
                )
                for tool_call in message.tool_calls
            ]
        )
        return tool_calls
    else:
        return None


MessageColumns: list[Column] = [
    MessageColumn("role", path="role", required=True),
    MessageColumn("content", path=message_text),
    MessageColumn("source", path="source"),
    MessageColumn("tool_calls", path=message_tool_calls),
    MessageColumn("tool_call_id", path="tool_call_id"),
    MessageColumn("tool_call_function", path="function"),
    MessageColumn("tool_call_error", path="error.message"),
]
"""Chat message columns."""
