from dataclasses import dataclass, field
from typing import Any, Callable, Literal, TypedDict

from pydantic import BaseModel, Field, JsonValue

from inspect_ai._util.content import Content


class ToolCallContent(BaseModel):
    """Content to include in tool call view."""

    title: str | None = Field(default=None)
    """Optional (plain text) title for tool call content."""

    format: Literal["text", "markdown"]
    """Format (text or markdown)."""

    content: str
    """Text or markdown content."""


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

    internal: JsonValue | None = field(default=None)
    """Model provider specific payload - typically used to aid transformation back to model types."""

    parse_error: str | None = field(default=None)
    """Error which occurred parsing tool call."""

    view: ToolCallContent | None = field(default=None)
    """Custom view of tool call input."""

    type: str | None = field(default=None)
    """Tool call type (deprecated)."""


@dataclass
class ToolCallError:
    """Error raised by a tool call."""

    type: Literal[
        "parsing",
        "timeout",
        "unicode_decode",
        "permission",
        "file_not_found",
        "is_a_directory",
        "limit",
        "approval",
        "unknown",
        # Retained for backward compatibility when loading logs created with an older
        # version of inspect.
        "output_limit",
    ]
    """Error type."""

    message: str
    """Error message."""


ToolCallViewer = Callable[[ToolCall], ToolCallView]
"""Custom view renderer for tool calls."""


class ToolCallModelInputHints(TypedDict):
    # This type is a little sketchy but it allows tools to customize their
    # input hook behavior based on model limitations without creating a tight
    # coupling to the model provider.
    disable_computer_screenshot_truncation: bool
    """The model does not support the truncation/redaction of computer screenshots."""


ToolCallModelInput = Callable[
    [int, int, str | list[Content], ToolCallModelInputHints], str | list[Content]
]
"""Determine how tool call results are played back as model input.

The first argument is an index into the total number of tool results
for this tool in the message history, the second is the total number.
"""
