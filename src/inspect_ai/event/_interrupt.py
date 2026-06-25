from typing import Literal

from pydantic import Field

from inspect_ai.event._base import BaseEvent


class InterruptEvent(BaseEvent):
    """Records that an agent's turn or sample was cut short.

    Emitted in three cases:

    - ``source="user_cancel"`` — an ACP client (e.g. an editor or TUI)
      called ``session/cancel`` while a turn was in flight.
    - ``source="limit"`` — a sample-level limit (tokens, time, cost,
      messages) tripped during execution.
    - ``source="system"`` — the eval is shutting down for an external
      reason and is cancelling active samples.

    The ``interrupted`` field records what was running at the moment
    the cancel reached the cancel scope. ``interrupted_tool_call_id``
    and ``interrupted_model_event_id`` give cross-references when
    applicable so downstream consumers can correlate this event with
    the in-flight ``ToolEvent`` or ``ModelEvent``.
    """

    event: Literal["interrupt"] = Field(default="interrupt")
    """Event type."""

    source: Literal["user_cancel", "limit", "system"]
    """What caused the interrupt."""

    interrupted: Literal["generate", "tool_call", "between_turns"]
    """What was running at the moment of the interrupt."""

    interrupted_tool_call_id: str | None = Field(default=None)
    """``ToolEvent.id`` (the underlying ``ToolCall.id``) of the in-flight tool, if any."""

    interrupted_model_event_id: str | None = Field(default=None)
    """``ModelEvent.uuid`` of the in-flight model call, if any."""
