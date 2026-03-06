# Sentinel class used until PEP 0661 is accepted
from typing import Any, Literal

from typing_extensions import override


class NotGiven:
    """A sentinel singleton class used to distinguish omitted keyword arguments from those passed in with the value None (which may have different behavior)."""

    def __bool__(self) -> Literal[False]:
        return False

    @override
    def __repr__(self) -> str:
        return "NOT_GIVEN"


def _is_notgiven(value: Any) -> bool:
    return isinstance(value, NotGiven) or type(value).__name__ == "NotGiven"


def sanitize_notgiven(value: Any) -> Any:
    if _is_notgiven(value):
        return None
    if isinstance(value, dict):
        return {
            k: sanitize_notgiven(v)
            for k, v in value.items()  # pyright: ignore[reportUnknownVariableType]
            if not _is_notgiven(v)
        }
    if isinstance(value, list | tuple | set):
        return type(value)(  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
            [
                sanitize_notgiven(v)
                for v in value  # pyright: ignore[reportUnknownVariableType]
                if not _is_notgiven(v)
            ]
        )

    return value


NOT_GIVEN = NotGiven()
