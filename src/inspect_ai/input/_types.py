from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

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
    """A structured question posted to the user via `request_input`."""

    message: str
    """The prompt shown to the user."""

    schema: ElicitationSchema
    """Schema describing the answer fields."""


@dataclass
class InputResult:
    """Result returned from an `ask_user` interaction."""

    outcome: InputOutcome
    """How the interaction concluded."""

    content: dict[str, Any] | None = None
    """The user's answer (keyed by `ElicitationSchema` property name) when `outcome == "accepted"`; otherwise `None`."""


@dataclass
class InputNotification:
    """Payload delivered to input notifiers when a question is posted."""

    action: Literal["posted", "answered", "cancelled"]
    """Lifecycle action being notified.

    Possible values:
      "posted": The question has just been shown to the user.
      "answered": The user has submitted an answer.
      "cancelled": The question was withdrawn before an answer was provided.
    """

    request: InputRequest
    """The question being notified about."""

    sample_id: str
    """Identifier of the active sample (empty string when called outside an eval scope)."""

    task_name: str
    """Name of the active task (empty string when called outside an eval scope)."""

    metadata: dict[str, Any] | None = None
    """Caller-supplied passthrough for handler↔notifier correlation."""


InputHandler = Callable[[InputRequest], Awaitable[InputResult | None]]
"""Async callable that collects an answer for an `ask_user` interaction.

Receives an `InputRequest` carrying the prompt and answer schema. Returns
an `InputResult` if the handler took responsibility for the question, or
`None` to defer to the built-in handler selection (console / panel / ACP).
"""


InputNotifier = Callable[[InputNotification], Awaitable[None]]
"""Async callable invoked to alert the user that a question is waiting.

Notifiers run in parallel with the handler and are fire-and-forget:
exceptions are logged and swallowed, and per-notifier timeouts apply.
"""
