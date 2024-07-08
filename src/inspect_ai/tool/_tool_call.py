from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolCall:
    id: str
    """Unique identifier for tool call."""

    function: str
    """Function called."""

    arguments: dict[str, Any]
    """Arguments to function."""

    type: Literal["function"]
    """Type of tool call (currently only 'function')"""

    parse_error: str | None = field(default=None)
    """Error which occurred parsing tool call."""
