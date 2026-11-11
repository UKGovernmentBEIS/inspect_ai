"""What Inspect keeps of an agent call through a sidecar, and the judgment it asks the sidecar for with `request_result`."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    """Forget what was learned of an earlier attempt at the current agent call, which a retry supersedes."""
    received = _received.get()
    if received is not None:
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
