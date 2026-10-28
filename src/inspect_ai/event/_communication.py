from typing import Literal, TypeAlias

from pydantic import BaseModel, Field, JsonValue, model_validator
from typing_extensions import Self

from inspect_ai.event._base import BaseEvent

CommunicationKind: TypeAlias = Literal["sent", "delivered", "read", "waited"]
"""What a `CommunicationEvent` records.

Experimental: not yet a stable API.
"""


class CommunicationRecord(BaseModel):
    """For `sent`, what one agent communicated: a message, or a change to state other agents read."""

    id: str | None = Field(default=None)
    """For `sent`, the producer's id for the record, if it has one."""

    kind: str
    """For `sent`, what the record does in its channel, in the channel's terms (`"message"`, `"create"`, `"append"`)."""

    sender: str
    """For `sent`, the name of the agent that sent it."""

    to: list[str] = Field(default_factory=list)
    """For `sent`, the addresses as written. Empty for an unaddressed record, such as a write to shared state."""

    recipients: list[str] = Field(default_factory=list)
    """For `sent`, the agents the addresses resolved to."""

    content: str | None = Field(default=None)
    """For `sent`, the text it carries, or `None` when the producer cannot see it (such as encrypted content)."""

    reply_to: str | None = Field(default=None)
    """For `sent`, the id of a record this one answers."""


class CommunicationRejection(BaseModel):
    """For `sent`, why a record that was sent was not delivered."""

    control: str
    """For `sent`, the control that refused it, in the producer's terms (`"rate"`, `"admit"`)."""

    reason: str
    """For `sent`, the reason the sender was given."""


class CommunicationSend(BaseModel):
    """For `sent`, the record an agent sent, and why it was refused if it was."""

    record: CommunicationRecord
    """For `sent`, the record."""

    rejected: CommunicationRejection | None = Field(default=None)
    """For `sent`, why the record was refused; `None` when it was delivered."""


class CommunicationDelivery(BaseModel):
    """For `delivered`, whom a record reached and in what order."""

    recipients: list[str] = Field(default_factory=list)
    """For `delivered`, the agents it reached."""

    seq: int | None = Field(default=None)
    """For `delivered`, the delivery's position in the order the producer delivered records, across its channels."""


class CommunicationWait(BaseModel):
    """For `waited`, an agent waiting for other agents."""

    id: str | None = Field(default=None)
    """For `waited`, the producer's id for the wait."""

    channels: list[str] = Field(default_factory=list)
    """For `waited`, the channels it waited on."""

    outcome: str
    """For `waited`, what ended it, in the producer's terms (`"news"`, `"timeout"`, `"cancelled"`)."""

    duration: float
    """For `waited`, seconds from the start of the wait until it ended."""


class CommunicationEvent(BaseEvent):
    """Communication between agents: a record sent or delivered, a read of what others communicated, or a wait for others.

    Experimental: not yet a stable API.
    """

    event: Literal["communication"] = Field(default="communication")
    """Event type."""

    kind: CommunicationKind
    """`sent`: an agent sent a record, which was delivered or refused (`send`). `delivered`: a record reached its channel and recipients (`delivery`). `read`: an agent read what others communicated, or a listing of it. `waited`: an agent waited for others (`wait`)."""

    source: str
    """What produced the event (`"inspect_swarm"`). It names the owner of `data`."""

    agent: str
    """The name of the agent that acted: the sender (`sent`, `delivered`), the reader (`read`) or the waiter (`waited`)."""

    agent_span_id: str | None = Field(default=None)
    """The span of the agent that acted."""

    loop_span_id: str | None = Field(default=None)
    """The agent span of the loop that acted: the agent's own loop, or a subagent acting for it."""

    nested: bool = Field(default=False)
    """The loop that acted is not the agent's own, such as one of its subagents."""

    channel: str | None = Field(default=None)
    """The channel the communication went through. `None` for a wait, whose channels are in `wait`."""

    record_ids: list[str] = Field(default_factory=list)
    """The ids of the records the event concerns: the record sent or delivered, or, for `read`, the producer's records for what was read (for the shared memory, each file's last write at the version read). They identify state, not text: a listing or a partial view names a record whose content it did not show."""

    send: CommunicationSend | None = Field(default=None)
    """For `sent`, the record and its refusal."""

    delivery: CommunicationDelivery | None = Field(default=None)
    """For `delivered`, the recipients and the delivery's order."""

    wait: CommunicationWait | None = Field(default=None)
    """For `waited`, the wait."""

    data: dict[str, JsonValue] = Field(default_factory=dict)
    """Further details in the format `source` defines, such as a channel's operation or the versions of files read."""

    @model_validator(mode="after")
    def _check_kind_fields(self) -> Self:
        # refuse the shapes no producer writes, so a bug fails at the writer
        # rather than in a reader (log reads run this too)
        for field, kind in (
            ("send", "sent"),
            ("delivery", "delivered"),
            ("wait", "waited"),
        ):
            if (getattr(self, field) is not None) != (self.kind == kind):
                raise ValueError(
                    f"{field} is set on, and only on, a '{kind}' CommunicationEvent."
                )
        if (self.channel is None) != (self.kind == "waited"):
            raise ValueError(
                "channel is set on every CommunicationEvent except a 'waited' one."
            )
        if (
            self.send is not None
            and self.send.record.id is not None
            and self.record_ids != [self.send.record.id]
        ):
            raise ValueError(
                "A 'sent' CommunicationEvent whose record has an id requires "
                "record_ids == [send.record.id]."
            )
        return self
