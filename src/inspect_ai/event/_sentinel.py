from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    Field,
    FiniteFloat,
    field_serializer,
    field_validator,
    model_validator,
)
from typing_extensions import Self

from inspect_ai._util.dateutil import UtcDatetime, datetime_to_iso_format_safe
from inspect_ai.event._base import BaseEvent
from inspect_ai.scorer._metric import Reference
from inspect_ai.tool._tool_call import ToolCall

SentinelAction: TypeAlias = Literal[
    "proceed", "modify", "reject", "terminate", "escalate"
]
"""What a sentinel protocol can decide about the step it examined.

Experimental: not yet a stable API; may change without notice.
"""

SentinelStage: TypeAlias = Literal[
    "model_input", "model_output", "tool_call", "tool_result"
]
"""Point in the agent loop a sentinel step belongs to."""

SentinelStatus: TypeAlias = Literal[
    "reported", "cancelled", "bypassed", "superseded", "error", "unjudged"
]
"""What happened to a sentinel report. `SentinelEvent.status` also takes other strings, so that a status added later reads as recording no report."""

SentinelSuspicion: TypeAlias = (
    FiniteFloat | Annotated[dict[str, FiniteFloat], Field(min_length=1)]
)
"""How suspicious a step is: one finite score, or a non-empty dict of scores for several dimensions.

Experimental: not yet a stable API; may change without notice.
"""


class SentinelRemoteModel(BaseModel):
    """A model a remote sentinel's monitors and protocols called while judging a step.

    Experimental: not yet a stable API; may change without notice.
    """

    role: str | None = Field(default=None)
    """The model role the call asked for, or `None` where it named its model without one."""

    model: str
    """The model the call went to."""


class SentinelRemoteHumanReview(BaseModel):
    """A question a remote sentinel's `human()` asked a person about a step, and how it ended.

    Experimental: not yet a stable API; may change without notice.
    """

    id: str
    """The question's id."""

    asked: UtcDatetime | None = Field(default=None)
    """When the question was asked."""

    answered: UtcDatetime | None = Field(default=None)
    """When the remote sentinel took an answer, if it took one."""

    decision: str | None = Field(default=None)
    """The answer the remote sentinel took, one of the question's choices."""

    resolution: Literal["answered", "timed_out", "cancelled"] | str | None = Field(
        default=None
    )
    """How the question ended, or `None` while it is open."""

    reason: str | None = Field(default=None)
    """Why a `cancelled` question was cancelled."""

    @field_serializer("asked", "answered")
    def _serialize_time(self, dt: datetime | None) -> str | None:
        return None if dt is None else datetime_to_iso_format_safe(dt)


class SentinelRemote(BaseModel):
    """Where a report from a sentinel running outside the eval came from: the model's proxy Inspect reached it through, and the agent's model call it judged.

    Experimental: not yet a stable API; may change without notice.
    """

    proxy_url: str
    """The address of the model's proxy, through which Inspect reached the remote sentinel, without any credentials it held."""

    request_id: str | None = Field(default=None)
    """The `x-irid` of the agent's model call the report came back with."""

    request_received: UtcDatetime | None = Field(default=None)
    """When the proxy handed the remote sentinel the call's request."""

    reply_received: UtcDatetime | None = Field(default=None)
    """When the proxy handed the remote sentinel the call's reply."""

    trimmed: bool = Field(default=False)
    """Whether the remote sentinel sent only what Inspect acts on, so the event records the step's decision without the monitor or protocol that made it, its function, explanation, references or metadata."""

    human_reviews: list[SentinelRemoteHumanReview] | None = Field(default=None)
    """The questions the step asked a person, on one event of the step: its root's, or, without one, its last.

    Only reviews a sentinel's `human()` asked for. Approvals by `inspect_ai.approval` approvers and reviews by `inspect_ai.review` reviewers are not counted here.
    """

    models: list[SentinelRemoteModel] | None = Field(default=None)
    """The models the remote sentinel's monitors and protocols called while judging the step, each once. It takes a role's model from its own configuration, not from the eval's model roles."""

    @field_serializer("request_received", "reply_received")
    def _serialize_time(self, dt: datetime | None) -> str | None:
        return None if dt is None else datetime_to_iso_format_safe(dt)


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
    """Name of the function that produced the report, or that raised for an `error` event, which tells apart the functions of an instance whose factory returned several; for the root's `error` event, the root's function, whichever layer below it raised. `None` for `cancelled`, `bypassed` and `unjudged` events. Empty for a remote sentinel's report of a step it sent without its records, as a trimmed one is (see `SentinelRemote.trimmed`)."""

    step_id: str
    """The step examined: at the generate stages (`model_input`, `model_output`) the generate's id, the `uuid` of its first `ModelEvent`, shared by both stages and by the generate's retried attempts; at the tool stages the tool call id."""

    execution_id: str | None = Field(default=None)
    """At the tool stages, the execution of the call this step judged: the `execution_id` of the `ToolEvent` that ran it, if one did.

    Set for a native tool call. In an agent bridge, a `tool_call` step names the
    handout it reviewed, and a `tool_result` step the handout whose result the
    scaffold reported (a host tool's result too), with the bridged tool the
    step judged, as a host `ToolEvent` records it; or `None` when the bridge
    can't tell which handout that is: a call id handed out more than once or
    shared by calls of one response, or one the bridge never handed out.
    `None` at the generate stages, and in logs written before this field.

    Experimental: not yet a stable API; may change without notice.
    """

    conversation: str
    """The agent conversation this step belongs to."""

    stage: SentinelStage
    """Point in the agent loop the step belongs to."""

    kind: Literal["observation", "decision"]
    """The report family: `observation` from a monitor, `decision` from a protocol. An `error` event is an `observation`, the root's included."""

    status: SentinelStatus | str
    """What happened to the report: `reported` carries it; `cancelled` and `bypassed` record no report; `unjudged`, at the empty path, records that the step's judging didn't finish, and why, in `reason`; `superseded` carries a decision that did not take effect; `error` records a monitor function that raised instead of reporting, or, at the empty path, that the step's sentinel raised (a protocol failed, or a limit or termination passed through it), so the step's `human()` decisions do not reach later steps. Any other status records no report, as `cancelled` does: a status a later Inspect adds reads that way."""

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
    """Messages and events the report cites, which link cites such as `[M22]` in `explanation`. Empty for `cancelled`, `bypassed`, `unjudged` and `error` events."""

    error: str | None = Field(default=None)
    """The exception a monitor function raised, or the root raised for the root's `error` event, as its type and message."""

    completed: UtcDatetime | None = Field(default=None)
    """Time the monitor or protocol reported. Where it is set, `timestamp` is when it started on the step; where it isn't, as in logs written before this field, `timestamp` is when the report was written, so a duration means something only where `completed` is set.

    Experimental: not yet a stable API; may change without notice.
    """

    working_time: float | None = Field(default=None)
    """Working time for the monitor or protocol on the step (clock time minus the sample's waiting time). For a remote sentinel's report, the time it measured.

    Experimental: not yet a stable API; may change without notice.
    """

    reason: str | None = Field(default=None)
    """Why the step wasn't judged, for an `unjudged` event.

    Experimental: not yet a stable API; may change without notice.
    """

    remote: SentinelRemote | None = Field(default=None)
    """Where the report came from, when a sentinel running outside the eval made it; `None` when the sentinel ran inside Inspect.

    Experimental: not yet a stable API; may change without notice.
    """

    @field_serializer("completed")
    def _serialize_completed(self, dt: datetime | None) -> str | None:
        return None if dt is None else datetime_to_iso_format_safe(dt)

    @field_validator("action", mode="before")
    @classmethod
    def _read_continue_as_proceed(cls, action: Any) -> Any:
        # logs written before the "continue" action was renamed "proceed"
        return "proceed" if action == "continue" else action

    @model_validator(mode="after")
    def _check_report_fields(self) -> Self:
        if (self.status == "error") != (self.error is not None):
            raise ValueError("error is set on, and only on, an 'error' SentinelEvent.")
        if (self.status == "unjudged") != (self.reason is not None):
            raise ValueError(
                "reason is set on, and only on, an 'unjudged' SentinelEvent."
            )
        if self.status == "unjudged" and self.path != "":
            raise ValueError(
                "An 'unjudged' SentinelEvent is the step's root, at the empty path."
            )
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
        elif self.status not in ("reported", "superseded"):
            unexpected = [
                field
                for field in ("function", "suspicion", "action")
                if getattr(self, field) is not None
            ]
            if self.references:
                unexpected.append("references")
            if self.status == "unjudged":
                if self.explanation is not None:
                    unexpected.append("explanation")
                if self.audit:
                    unexpected.append("audit")
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
