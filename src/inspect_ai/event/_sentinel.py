from typing import Literal, TypeAlias

from pydantic import Field, model_validator
from typing_extensions import Self

from inspect_ai.event._base import BaseEvent
from inspect_ai.scorer._metric import Reference
from inspect_ai.tool._tool_call import ToolCall

# isort: split
# Re-exports of sentinel names defined in inspect_ai.core.
from inspect_ai.core._sentinel import SentinelAction as SentinelAction
from inspect_ai.core._sentinel import SentinelSuspicion as SentinelSuspicion

# End of re-exports.

SentinelStage: TypeAlias = Literal[
    "model_input", "model_output", "tool_call", "tool_result"
]
"""Point in the agent loop a sentinel step belongs to."""

SentinelStatus: TypeAlias = Literal[
    "reported", "cancelled", "bypassed", "superseded", "error"
]
"""What happened to a sentinel report."""


class SentinelEvent(BaseEvent):
    """Report from a sentinel monitor or protocol about one step.

    A report's metadata is recorded in the event's `metadata` field.

    Experimental: not yet a stable API; may change without notice.
    """

    event: Literal["sentinel"] = Field(default="sentinel")
    """Event type"""

    factory: str
    """Registry name of the factory: a monitor or a protocol."""

    path: str
    """Instance path (e.g. "attempt/internet_attempt")."""

    function: str | None = Field(default=None)
    """Name of the function that produced the report, or that raised for an `error` event, which tells apart the functions of an instance whose factory returned several. `None` for `cancelled` and `bypassed` events."""

    step_id: str
    """The step examined: the triggering message id (`model_input`), the assistant message id (`model_output`), or the tool call id (tool stages)."""

    conversation: str
    """The agent conversation this step belongs to."""

    stage: SentinelStage
    """Point in the agent loop the step belongs to."""

    kind: Literal["observation", "decision"]
    """The report family: `observation` from a monitor, `decision` from a protocol."""

    status: SentinelStatus
    """What happened to the report: `reported` carries it; `cancelled` and `bypassed` record no report; `superseded` carries a decision that did not take effect; `error` records a monitor function that raised instead of reporting."""

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
    """Messages and events the report cites, which link cites such as `[M22]` in `explanation`. Empty for `cancelled`, `bypassed` and `error` events."""

    error: str | None = Field(default=None)
    """The exception a monitor function raised, as its type and message, for an `error` event."""

    @model_validator(mode="after")
    def _check_report_fields(self) -> Self:
        if (self.status == "error") != (self.error is not None):
            raise ValueError("error is set on, and only on, an 'error' SentinelEvent.")
        if self.status == "error":
            if self.kind != "observation":
                raise ValueError("Only an 'observation' SentinelEvent can be an error.")
            unexpected = [
                field
                for field in ("suspicion", "action")
                if getattr(self, field) is not None
            ]
            if self.references:
                unexpected.append("references")
            if unexpected:
                raise ValueError(
                    f"An 'error' SentinelEvent records no report, so "
                    f"{', '.join(unexpected)} must be unset."
                )
            if self.function is None:
                raise ValueError("An 'error' SentinelEvent requires function.")
        elif self.status in ("cancelled", "bypassed"):
            unexpected = [
                field
                for field in ("function", "suspicion", "action")
                if getattr(self, field) is not None
            ]
            if self.references:
                unexpected.append("references")
            if unexpected:
                raise ValueError(
                    f"A '{self.status}' SentinelEvent records no report, so "
                    f"{', '.join(unexpected)} must be unset."
                )
        else:
            if self.status == "superseded" and self.kind != "decision":
                raise ValueError("Only a 'decision' SentinelEvent can be superseded.")
            if self.kind == "observation":
                if self.suspicion is None or self.action is not None:
                    raise ValueError(
                        "An 'observation' SentinelEvent requires suspicion and no action."
                    )
            elif self.action is None or self.suspicion is not None:
                raise ValueError(
                    "A 'decision' SentinelEvent requires action and no suspicion."
                )
            if self.function is None:
                raise ValueError(f"A '{self.status}' SentinelEvent requires function.")
        has_decision = self.kind == "decision" and self.status in (
            "reported",
            "superseded",
        )
        is_modify = has_decision and self.action == "modify"
        if is_modify and self.modified is None:
            raise ValueError(
                f"A '{self.status}' modify SentinelEvent requires modified."
            )
        if not is_modify and self.modified is not None:
            raise ValueError(
                "modified is set only on a reported or superseded modify decision."
            )
        if self.message is not None and not (has_decision and self.action == "reject"):
            raise ValueError(
                "message is set only on a reported or superseded reject decision."
            )
        return self
