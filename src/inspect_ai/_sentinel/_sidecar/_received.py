"""What Inspect keeps of an agent call through a sidecar, and the judgment it asks the sidecar for with `request_result`."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from inspect_ai.model._chat_message import ChatMessage

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
    reviews: list[str] | None = None
    """The ids of the questions the step asked a person, which the review records in the eval's log are found by."""


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
        history: "list[ChatMessage] | None" = None,
    ) -> None:
        self.sidecar = sidecar
        """The sidecar the call goes through, which `request_result` asks."""
        self.history: "list[ChatMessage]" = history if history is not None else []
        """The conversation the call is sent with, as Inspect holds it, for a person who is asked about the call to be shown. It never leaves the eval's process."""
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
        self.reviewed_id: str | None = None
        """The `x-irid` of a call a sentinel asked a person about. The sidecar keeps such a call as one model call under that id, so every later request of the call is sent under it, a retry's included: a new id would be judged afresh, and the person asked again."""
        self.open = False
        """Whether the sidecar holds the call open: a person was asked about it, and it has not ended. A call left open when Inspect gives up on it is cancelled at the sidecar."""
        self.getting_held_reply = False
        """Whether the request now being sent is the one that gets the reply the sidecar holds for the call, so it goes to the sidecar's held-reply path and not to the model."""
        self.held_reply_body: bytes | None = None
        """A digest of the body of the request sent to get the held reply. The SDK's retries of that request have the same body and go to the same path; a later request of the provider's, such as a continuation, has another and goes to the model."""
        self.asked_for_held_reply = False
        """Whether the latest attempt sent a request to get the reply the sidecar holds for the call. It is sent once for an attempt."""
        self.held_reply_requested = False
        """Whether a request of the latest attempt went to the sidecar's held-reply path."""
        self.sent_on_model_path = False
        self.model_sends = 0
        """How many times the latest attempt sent the call's request again for the sidecar to send on to the provider."""
        """Whether the call's request was sent again for the provider since the sidecar last said it waits for it."""
        self.error_stands = False
        """Whether the sidecar was asked what became of the latest attempt after its last request, and nothing more is to be sent: the error that request came to stands."""
        self.failures: set[int] = set()
        """The tries the sidecar said failed at the provider that Inspect has acted on, by number. A try whose error the sidecar holds is acted on once that error has been got from it."""
        self.failure_fetches: dict[int, int] = {}
        """How many times the provider's error for a failed try was asked of the sidecar, by the try's number."""
        self.decisions: dict[str, tuple[str, str | None]] = {}
        """What a person chose for each of the sidecar's questions they were shown for the call, by the question's id, with their reason. None is shown twice."""
        self.asked_about: dict[str, tuple[str, float]] = {}
        """For each question a person here answered, by the question's id: the function of the call it was about, and when they answered, in seconds since the epoch."""
        self.reviews_logged: set[str] = set()
        """The ids of the questions whose records, once ended, are in the eval's log."""
        self.answers_unknown: set[str] = set()
        """The ids of the questions a person here answered that the sidecar's records could say nothing of, and of which they have been told."""
        self.answered: set[str] = set()
        """The ids of the questions whose answers the sidecar took, or which it holds no longer."""


_received: ContextVar[ReceivedCall | None] = ContextVar(
    "sentinel_sidecar_call", default=None
)


@contextmanager
def receiving_call(
    sidecar: Any = None,
    registered_beforehand: bool = False,
    mode: "SentinelProxy" = "auto",
    history: "list[ChatMessage] | None" = None,
) -> Iterator[ReceivedCall]:
    """Keep what is learned of an agent call through a sidecar, for the providers to report its request id into.

    Args:
        sidecar: The sidecar the call goes through.
        registered_beforehand: Whether the sidecar's admin registered the call's task beforehand.
        mode: Whether the task requires a sidecar.
        history: The conversation the call is sent with, which a person asked about the call is shown.
    """
    received = ReceivedCall(sidecar, registered_beforehand, mode, history)
    token = _received.set(received)
    try:
        yield received
    finally:
        _received.reset(token)


def begin_attempt() -> None:
    """Forget what was learned of an earlier attempt at the current agent call, which a retry supersedes.

    A call a person was asked about keeps its id, and what is known of the questions and the provider's failures for it: its retry is a try of the same model call at the sidecar.
    """
    received = _received.get()
    if received is not None:
        received.request_id = None
        received.sent = False
        received.looked = None
        received.judgment = None
        received.getting_held_reply = False
        received.held_reply_body = None
        received.asked_for_held_reply = False
        received.held_reply_requested = False
        received.sent_on_model_path = False
        received.model_sends = 0
        received.error_stands = False


HELD_REPLY_PATH = "/sentinel/v1/held-reply"
"""Where a sidecar answers a model request with the provider's reply it holds for the call, after a person approved the call."""


def request_id_to_reuse() -> str | None:
    """The `x-irid` the current agent call's next request is sent under, in place of a new one, or None for a new one.

    None for every call but an agent call through a sidecar that a sentinel asked a person about. The sidecar keeps such a call as one model call under its `x-irid`, so the call's later requests are sent under it: the one that gets the reply the sidecar holds, the one the sidecar waits to send on to the provider, and a retry of the call. It is given once for each send, to the first request the send begins.
    """
    received = _received.get()
    if received is None or received.request_id is not None:
        return None
    return received.reviewed_id


def use_held_reply_path(request: Any) -> None:
    """Send a model request to the sidecar's held-reply path, if it is the request that gets the reply the sidecar holds for the current agent call.

    Every other request is left as it is: one of a call no sidecar judges, one of a call no person was asked about, and one sent for the provider. The SDK's retries of the request go to the same path. A later request the provider makes in the same send, such as a continuation, has another body, and goes to the model.

    Args:
        request: The request about to be sent, as the SDK's HTTP client built it. Its path is replaced, and its origin and query are kept.
    """
    received = _received.get()
    if received is None or not received.getting_held_reply:
        return
    from inspect_ai.model._providers.util.hooks import HttpHooks

    if received.reviewed_id is None or (
        request.headers.get(HttpHooks.REQUEST_ID_HEADER) != received.reviewed_id
    ):
        return
    body = _body_digest(request)
    if received.held_reply_body is None:
        received.held_reply_body = body
    elif received.held_reply_body != body:
        return
    request.url = request.url.copy_with(path=HELD_REPLY_PATH)
    received.held_reply_requested = True


def _body_digest(request: Any) -> bytes:
    # a body that can't be read here, as one still to be streamed, is taken
    # for the same as any other that can't
    try:
        content = request.content
    except Exception:
        content = b""
    return hashlib.sha256(content).digest()


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
