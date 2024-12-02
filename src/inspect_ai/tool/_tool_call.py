from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field


class ToolCallContent(BaseModel):
    """Content to include in tool call view."""

    title: str | None = Field(default=None)
    """Optional (plain text) title for tool call content."""

    format: Literal["text", "markdown"]
    """Format."""

    content: str
    """Content."""


class ToolCallView(BaseModel):
    """Custom view of a tool call.

    Both `context` and `call` are optional. If `call` is not specified
    then the view will default to a syntax highlighted Python function call.
    """

    context: ToolCallContent | None = Field(default=None)
    """Context for the tool call (i.e. current tool state)."""

    call: ToolCallContent | None = Field(default=None)
    """Custom representation of tool call."""


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

    view: ToolCallContent | None = field(default=None)
    """Custom view of tool call input."""


@dataclass
class ToolCallError:
    type: Literal[
        "parsing",
        "timeout",
        "unicode_decode",
        "permission",
        "file_not_found",
        "is_a_directory",
        "output_limit",
        "approval",
        "unknown",
    ]

    message: str


ToolCallViewer = Callable[[ToolCall], ToolCallView]
"""Custom view renderer for tool calls."""
