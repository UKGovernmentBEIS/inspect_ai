from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    # Deferred: `acp.schema` is the single largest cost of `import inspect_ai`.
    from acp.schema import ElicitationSchema

InputOutcome = Literal["accepted", "declined", "cancelled"]
"""Outcome of an `ask_user` interaction.

Possible values:
  "accepted": The user provided an answer.
  "declined": The user explicitly chose not to answer.
  "cancelled": The interaction was aborted (e.g. timeout, sample cancellation).
"""


@dataclass
class InputRequest:
    """A structured question posted to the user via `request_input`.

    The `schema` annotation is a forward reference to
    `acp.schema.ElicitationSchema` that is never resolved at runtime (the
    module is imported only when a question is asked), so
    `typing.get_type_hints(InputRequest)` and pydantic validation or schema
    generation for `InputRequest` are not supported.
    """

    message: str
    """The prompt shown to the user."""

    schema: "ElicitationSchema"
    """Schema describing the answer fields."""


@dataclass
class InputResult:
    """Result returned from an `ask_user` interaction."""

    outcome: InputOutcome
    """How the interaction concluded."""

    content: dict[str, Any] | None = None
    """The user's answer (keyed by `ElicitationSchema` property name) when `outcome == "accepted"`; otherwise `None`."""
