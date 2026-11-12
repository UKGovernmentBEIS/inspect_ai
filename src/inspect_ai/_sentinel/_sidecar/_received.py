"""What Inspect keeps of an agent call through a sidecar, and the judgment it asks the sidecar for with `request_result`."""

import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inspect_ai.model._model_output import ModelUsage

if TYPE_CHECKING:
    from .._config import SentinelProxy
    from ._lookup import Looked


class SentinelStep(BaseModel):
    """One step the sidecar judged during the call."""

    model_config = ConfigDict(extra="allow")

    stage: Literal["model_input", "model_output", "tool_call", "tool_result"]
    call: str | None = None
    decision: dict[str, Any]
    recorded: list[dict[str, Any]] | None = None
    models: list[dict[str, Any]] | None = None
    """The models the step's monitors and protocols called, with the role each asked for."""


class WithheldTurn(BaseModel):
    """The model's turn, as the eval holds it: each call a decision acted on redacted, each changed call as it ran, with what the model is told of each call taken out."""

    model_config = ConfigDict(extra="allow")

    message: dict[str, Any]
    results: dict[str, str]
    redacted: list[str] = Field(default_factory=list)
    """The calls a decision acted on, which the turn holds with their id and function only."""


class Judgment(BaseModel):
    """What a sidecar decided during one agent call."""

    model_config = ConfigDict(extra="allow")

    version: int = 1
    outcome: Literal["proceed", "reject", "terminate"]
    trimmed: bool | None = None
    steps: list[SentinelStep] = Field(default_factory=list)
    withheld: WithheldTurn | None = None
    proposed: WithheldTurn | None = None
    usage: dict[str, Any] | None = None
    """What the provider billed for a reply the client was refused."""


class JudgingUsage(BaseModel):
    """What the provider billed for a model the sidecar's sentinel called while judging an agent call, on the sidecar's own key."""

    model_config = ConfigDict(extra="allow")

    role: str | None = None
    """The role the sentinel asked for, or None where it named the model."""
    model: str
    """The model, as Inspect names it."""
    usage: ModelUsage
    """The usage of the model's calls added up, with their cost where the sidecar knows it."""


_COUNTED = ("input_tokens", "output_tokens", "total_tokens")
"""The counts every entry's `usage` gives, as the sidecar writes them."""


def parse_judging_usage(used: Any) -> list[JudgingUsage]:
    """The usage of the sidecar's judge models, as its `request_result` writes it.

    Absent, it is no usage. Anything else must be a list of entries, each read strictly: a named model, and a role if any, with `usage` that gives its token counts as whole numbers, and every count and the cost a finite number of 0 or more. Anything else can't be read, rather than be taken for other usage, or for none.

    Raises:
        ValueError: If the usage isn't one this Inspect can read.
    """
    if used is None:
        return []
    if not isinstance(used, list):
        raise ValueError(f"The sidecar's judging usage can't be read: {used!r}")
    entries: list[JudgingUsage] = []
    for entry in used:
        try:
            read = JudgingUsage.model_validate(entry, strict=True)
        except ValidationError as ex:
            raise ValueError(f"The sidecar's judging usage can't be read: {ex}") from ex
        problem = _unreadable(read, entry)
        if problem is not None:
            raise ValueError(f"The sidecar's judging usage can't be read: {problem}")
        entries.append(read)
    return entries


def _unreadable(read: JudgingUsage, entry: dict[str, Any]) -> str | None:
    # what strict validation lets through that can't be usage
    if not read.model or read.role == "":
        return f"an entry names no model or role: {entry!r}"
    missing = [name for name in _COUNTED if name not in entry["usage"]]
    if missing:
        return f"the usage of {read.model} gives no {', '.join(missing)}"
    for name, value in read.usage.model_dump().items():
        if value is not None and (not math.isfinite(value) or value < 0):
            return f"the {name} of {read.model} is {value!r}"
    return None


class ReceivedCall:
    """What Inspect keeps of the latest attempt at an agent call through a sidecar: the id it was sent under, and what the sidecar said of it."""

    def __init__(
        self,
        sidecar: Any = None,
        registered_beforehand: bool = False,
        mode: "SentinelProxy" = "auto",
    ) -> None:
        self.sidecar = sidecar
        """The sidecar the call goes through, which `request_result` asks."""
        self.registered_beforehand = registered_beforehand
        """Whether the sidecar's admin registered the call's task beforehand, so a sample the sidecar can't place was never accepted, rather than lost."""
        self.mode: "SentinelProxy" = mode
        """Whether the task requires a sidecar, so a call whose judgment is unavailable fails the sample."""
        self.request_id: str | None = None
        self.sent = False
        """Whether a request of the latest attempt was handed to the HTTP client. Until one is, the sidecar can know nothing of the attempt: its request id is allocated before the provider builds the request, which can fail."""
        self.looked: "Looked | None" = None
        """What `request_result` said of the latest attempt, once asked."""
        self.judgment: Judgment | None = None
        """What the sidecar decided of the latest attempt, once `request_result` said."""
        self.unasked: list[str] = []
        """The request ids of earlier attempts that were sent and that Inspect retried without asking the sidecar about them. The sidecar may have judged their requests with its own models, and is asked for that usage once the latest attempt is asked about."""


_received: ContextVar[ReceivedCall | None] = ContextVar(
    "sentinel_sidecar_call", default=None
)


@contextmanager
def receiving_call(
    sidecar: Any = None,
    registered_beforehand: bool = False,
    mode: "SentinelProxy" = "auto",
) -> Iterator[ReceivedCall]:
    """Keep what is learned of an agent call through a sidecar, for the providers to report its request id into."""
    received = ReceivedCall(sidecar, registered_beforehand, mode)
    token = _received.set(received)
    try:
        yield received
    finally:
        _received.reset(token)


def begin_attempt() -> None:
    """Forget what was learned of an earlier attempt at the current agent call, which a retry supersedes, keeping its request id if it was sent and never asked about."""
    received = _received.get()
    if received is not None:
        if (
            received.sent
            and received.request_id is not None
            and received.looked is None
        ):
            received.unasked.append(received.request_id)
        received.request_id = None
        received.sent = False
        received.looked = None
        received.judgment = None


def current_receiving() -> ReceivedCall | None:
    """What is kept of the current agent call through a sidecar, or None for any other call."""
    return _received.get()


def report_request_id(request_id: str) -> None:
    """Report the `x-irid` the current agent call is sent under, by which the sidecar's `request_result` finds it."""
    received = _received.get()
    if received is not None:
        received.request_id = request_id


def report_sent(request_id: str) -> None:
    """Report that a request of the current agent call is being sent under the `x-irid` reported for it, on each try."""
    received = _received.get()
    if received is not None and received.request_id == request_id:
        received.sent = True


def parse_judgment(judgment: dict[str, Any]) -> Judgment:
    """A judgment, as a sidecar's `request_result` writes it.

    Raises:
        ValueError: If the judgment isn't one this Inspect can read.
    """
    try:
        return Judgment.model_validate(judgment)
    except ValidationError as ex:
        raise ValueError(f"The sidecar's judgment can't be read: {ex}") from ex
