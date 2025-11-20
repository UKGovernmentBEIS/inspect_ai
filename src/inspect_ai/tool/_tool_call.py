from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, TypedDict

from pydantic import BaseModel, Field, field_validator
from pydantic.dataclasses import dataclass as pydantic_dataclass

from inspect_ai._util.content import Content


class ToolCallContent(BaseModel):
    """Content to include in tool call view."""

    title: str | None = Field(default=None)
    """Optional (plain text) title for tool call content."""

    format: Literal["text", "markdown"]
    """Format (text or markdown)."""

    content: str = Field(default_factory=str)
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


@pydantic_dataclass
class ToolCall:
    id: str
    """Unique identifier for tool call."""

    function: str
    """Function called."""

    arguments: dict[str, Any]
    """Arguments to function."""

    parse_error: str | None = field(default=None)
    """Error which occurred parsing tool call."""

    view: ToolCallContent | None = field(default=None)
    """Custom view of tool call input."""

    type: Literal["function", "custom", "apply_patch"] = field(default="function")
    """Type of tool call."""

    @field_validator("type", mode="before")
    @classmethod
    def migrate_type(cls, v: Any) -> Any:
        """Migrate None values from deprecated type field to 'function'."""
        if v is None:
            return "function"
        return v


ApplyPatchOperationType = Literal["create_file", "update_file", "delete_file"]
"""Valid operation types for apply_patch calls."""


APPLY_PATCH_ARGUMENT_KEY = "operation"
"""Dictionary key used to store apply_patch operations in ToolCall.arguments."""


@dataclass
class ApplyPatchOperation:
    """Operation payload for an apply_patch tool call."""

    type: ApplyPatchOperationType
    """Operation type (create_file, update_file, delete_file)."""

    path: str
    """Target filesystem path for the operation."""

    diff: str | None = None
    """Unified diff payload for create/update operations."""

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise ValueError("ApplyPatchOperation requires a non-empty string path.")
        if self.type in ("create_file", "update_file"):
            if not isinstance(self.diff, str) or self.diff == "":
                raise ValueError(
                    f"ApplyPatchOperation '{self.type}' requires a non-empty diff."
                )
        else:
            if self.diff not in (None, ""):
                raise ValueError("ApplyPatchOperation 'delete_file' must not include a diff.")
            self.diff = None

    def as_arguments(self) -> dict[str, Any]:
        """Return operation payload formatted for ToolCall.arguments."""
        payload: dict[str, Any] = {"type": self.type, "path": self.path}
        if self.diff is not None:
            payload["diff"] = self.diff
        return {APPLY_PATCH_ARGUMENT_KEY: payload}


def validate_apply_patch_operation(operation: Mapping[str, Any]) -> ApplyPatchOperation:
    """Validate and normalise an apply_patch operation mapping."""
    if not isinstance(operation, Mapping):
        raise ValueError("ApplyPatch operation payload must be a mapping.")

    try:
        op_type = operation["type"]
        path = operation["path"]
    except KeyError as ex:
        raise ValueError(f"Missing field '{ex.args[0]}' in apply_patch operation.") from ex

    if op_type not in {"create_file", "update_file", "delete_file"}:
        raise ValueError(f"Unsupported apply_patch operation type '{op_type}'.")

    diff_value: str | None = operation.get("diff")
    if diff_value is not None and not isinstance(diff_value, str):
        raise ValueError("ApplyPatchOperation diff must be a string when provided.")

    return ApplyPatchOperation(
        type=op_type, path=path, diff=diff_value if diff_value is not None else None
    )


def parse_apply_patch_arguments(arguments: Mapping[str, Any]) -> ApplyPatchOperation:
    """Extract and validate an apply_patch operation from tool call arguments."""
    if not isinstance(arguments, Mapping):
        raise ValueError("ToolCall arguments must be a mapping.")
    try:
        operation = arguments[APPLY_PATCH_ARGUMENT_KEY]
    except KeyError as ex:
        raise ValueError(
            "apply_patch ToolCall arguments must include an 'operation' payload."
        ) from ex
    if not isinstance(operation, Mapping):
        raise ValueError("apply_patch operation payload must be a mapping.")
    return validate_apply_patch_operation(operation)


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
