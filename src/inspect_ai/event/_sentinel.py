from typing import Annotated, Literal, TypeAlias

from pydantic import Field, FiniteFloat

from inspect_ai.event._base import BaseEvent

SentinelAction: TypeAlias = Literal[
    "continue", "modify", "reject", "terminate", "escalate"
]
"""What a sentinel protocol can decide about the step it examined."""

SentinelStage: TypeAlias = Literal[
    "model_input", "model_output", "tool_call", "tool_result"
]
"""Point in the agent loop a sentinel step belongs to."""


class SentinelEvent(BaseEvent):
    """Report from a sentinel monitor or protocol about one step."""

    event: Literal["sentinel"] = Field(default="sentinel")
    """Event type"""

    name: str
    """Registry name of the factory: a monitor or a protocol."""

    path: str
    """Instance path (e.g. "attempt/internet_attempt")."""

    function: str | None = Field(default=None)
    """Name of the function that produced the report, which tells apart the functions of an instance whose factory returned several. `None` for `cancelled` and `bypassed` events."""

    step_id: str
    """The step examined: the triggering message id (`model_input`), the assistant message id (`model_output`), or the tool call id (tool stages)."""

    conversation: str
    """The agent conversation this step belongs to."""

    stage: SentinelStage
    """Point in the agent loop the step belongs to."""

    kind: Literal["observation", "decision", "cancelled", "bypassed", "superseded"]
    """`observation` from a monitor, `decision` from a protocol; `cancelled` and `bypassed` record no report; `superseded` carries a decision that did not take effect."""

    suspicion: (
        FiniteFloat | Annotated[dict[str, FiniteFloat], Field(min_length=1)] | None
    ) = Field(default=None)
    """How suspicious the step is: one score, or scores for several dimensions."""

    decision: SentinelAction | None = Field(default=None)
    """What this layer decided."""

    audit: bool = Field(default=False)
    """Whether the report requested that oversight budget be spent on this step."""

    outcome: SentinelAction | None = Field(default=None)
    """What the layer above did with this layer's decision."""

    explanation: str | None = Field(default=None)
    """Explanation for the report."""
