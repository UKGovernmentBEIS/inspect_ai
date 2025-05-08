from typing import Any, Callable, Mapping, Type

from jsonpath_ng import JSONPath  # type: ignore
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai.log._transcript import Event

from ..columns import Column, ColumnType


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
