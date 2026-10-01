from typing import Annotated, Literal, TypeAlias

from pydantic import Field, FiniteFloat, model_validator
from typing_extensions import Self

from inspect_ai.event._base import BaseEvent
from inspect_ai.scorer._metric import Reference
from inspect_ai.tool._tool_call import ToolCall

SentinelAction: TypeAlias = Literal[
    "continue", "modify", "reject", "terminate", "escalate"
]
"""What a sentinel protocol can decide about the step it examined."""

SentinelStage: TypeAlias = Literal[
    "model_input", "model_output", "tool_call", "tool_result"
]
"""Point in the agent loop a sentinel step belongs to."""


SentinelSuspicion: TypeAlias = (
    FiniteFloat | Annotated[dict[str, FiniteFloat], Field(min_length=1)]
)
"""How suspicious a step is: one finite score, or a non-empty dict of scores for several dimensions."""


class SentinelEvent(BaseEvent):
    """Report from a sentinel monitor or protocol about one step."""

    event: Literal["sentinel"] = Field(default="sentinel")
    """Event type"""

    factory: str
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

    suspicion: SentinelSuspicion | None = Field(default=None)
    """How suspicious the step is: one score, or scores for several dimensions."""

    action: SentinelAction | None = Field(default=None)
    """What this layer decided."""

    audit: bool = Field(default=False)
    """Whether the report requested that oversight budget be spent on this step."""

    modified: ToolCall | None = Field(default=None)
    """The replacement call, for a `modify` decision."""

    message: str | None = Field(default=None)
    """What the agent was told, for a `reject` decision."""

    explanation: str | None = Field(default=None)
    """Explanation for the report, recorded in the log only (the agent never sees it)."""

    references: list[Reference] = Field(default_factory=list)
    """Messages and events the report cites, which link cites such as `[M22]` in `explanation`. Empty for `cancelled` and `bypassed` events."""

    @model_validator(mode="after")
    def _check_kind_fields(self) -> Self:
        if self.kind in ("cancelled", "bypassed"):
            unexpected = [
                field
                for field in ("function", "suspicion", "action")
                if getattr(self, field) is not None
            ]
            if self.references:
                unexpected.append("references")
            if unexpected:
                raise ValueError(
                    f"A '{self.kind}' SentinelEvent records no report, so "
                    f"{', '.join(unexpected)} must be unset."
                )
        elif self.kind == "observation":
            if self.suspicion is None or self.action is not None:
                raise ValueError(
                    "An 'observation' SentinelEvent requires suspicion and no action."
                )
        elif self.action is None or self.suspicion is not None:
            raise ValueError(
                f"A '{self.kind}' SentinelEvent requires action and no suspicion."
            )
        is_decision = self.kind in ("decision", "superseded")
        is_modify = is_decision and self.action == "modify"
        if is_modify and self.modified is None:
            raise ValueError(f"A '{self.kind}' modify SentinelEvent requires modified.")
        if not is_modify and self.modified is not None:
            raise ValueError(
                "modified is set only on a 'decision' or 'superseded' modify SentinelEvent."
            )
        if self.message is not None and not (is_decision and self.action == "reject"):
            raise ValueError(
                "message is set only on a 'decision' or 'superseded' reject SentinelEvent."
            )
        if self.kind not in ("cancelled", "bypassed") and self.function is None:
            raise ValueError(f"A '{self.kind}' SentinelEvent requires function.")
        return self
