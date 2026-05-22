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


InputEvent = Literal["posted", "answered", "cancelled"]
"""Lifecycle event reported to input notifiers.

Possible values:
  "posted": The question has just been shown to the user.
  "answered": The user has submitted an answer.
  "cancelled": The question was withdrawn before an answer was provided.
"""


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

    event: InputEvent
    """Lifecycle event being notified."""

    message: str
    """The prompt that was shown to the user."""

    schema: ElicitationSchema
    """Schema describing the answer fields."""

    sample_id: str
    """Identifier of the active sample (empty string when called outside an eval scope)."""

    task_name: str
    """Name of the active task (empty string when called outside an eval scope)."""

    metadata: dict[str, Any] | None = None
    """Caller-supplied passthrough for handler↔notifier correlation."""


InputHandler = Callable[[str, ElicitationSchema], Awaitable[InputResult | None]]
"""Async callable that collects an answer for an `ask_user` interaction.

Receives the prompt message and an `ElicitationSchema` describing the
expected answer fields. Returns an `InputResult` if the handler took
responsibility for the question, or `None` to defer to the built-in
handler selection (console / panel / ACP).
"""


InputNotifier = Callable[[InputNotification], Awaitable[None]]
"""Async callable invoked to alert the user that a question is waiting.

Notifiers run in parallel with the handler and are fire-and-forget:
exceptions are logged and swallowed, and per-notifier timeouts apply.
"""
