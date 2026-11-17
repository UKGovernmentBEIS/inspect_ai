"""What Inspect keeps of an agent call through a sidecar, and the judgment it asks the sidecar for with `request_result`."""

import hashlib
import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inspect_ai._util.working import sample_clock
from inspect_ai.model._model_output import ModelUsage

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
    """The ids of the questions the step asked a person.

    Each question's record in the eval's log has the same id.
    """


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


@dataclass
class Send:
    """One send of a paused call's request, timed on the sample clock.

    A call that was paused for a person is sent more than once in one attempt.
    """

    start: float
    """When the send's last try went out.

    The earlier tries, which the provider's SDK retried, and the waits before
    them are not the model's time.
    """
    end: float
    """When the send returned."""
    judging: float = 0.0
    """Seconds the sidecar spent judging the call while the proxy held the send."""


class ReceivedCall:
    """What Inspect keeps of the latest attempt at an agent call through a sidecar: the id it was sent under, and what the sidecar said of it."""

    def __init__(
        self,
        sidecar: Any = None,
        registered_beforehand: bool = False,
        mode: "SentinelProxy" = "auto",
        history: "list[ChatMessage] | None" = None,
        timeout: int | None = None,
    ) -> None:
        self.sidecar = sidecar
        """The sidecar the call goes through, which `request_result` asks."""
        self.timeout = timeout
        """The call's `timeout` in seconds, or None for no limit.

        It limits the call's total time, retries included.
        """
        self.began: float | None = None
        """When the call's first attempt began, on the monotonic clock.

        The call's `timeout` runs from this time.
        """
        self.person_time = 0.0
        """Seconds that people took to answer a sentinel's questions about the call.

        It is not the model call's time, so the call's `timeout` doesn't count it.
        """
        self.history: "list[ChatMessage]" = history if history is not None else []
        """The conversation the call is sent with, as Inspect holds it.

        Inspect shows it to a person who is asked about the call. It never leaves
        the eval's process.
        """
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
        self.reviewed_request_id: str | None = None
        """The `x-irid` of the call, once a sentinel has asked a person about it.

        The sidecar keeps a paused call as one model call under this id. So
        Inspect sends every later request of the call under it, including a
        retry. Under a new id, the sidecar would judge the call again and ask the
        person again.
        """
        self.paused = False
        """Whether the call is paused at the sidecar for a person, and has not ended.

        If Inspect gives up on a paused call, it cancels the call at the sidecar.
        """
        self.fetching = False
        """Whether the request now being sent is a fetch.

        A fetch gets the reply, or the provider's error, that the sidecar holds
        for the call. The HTTP hook sends it to the sidecar's judged-reply path,
        not to the model.
        """
        self.fetch_body: bytes | None = None
        """A digest of the body of the fetch request.

        The SDK's retries of the fetch have the same body, so they go to the
        judged-reply path too. A later request that the provider's code makes in
        the same send, such as a continuation, has a different body and goes to
        the model.
        """
        self.reply_fetch_tried = False
        """Whether the latest attempt has tried to fetch the reply the sidecar holds.

        An attempt tries once.
        """
        self.fetch_sent = False
        """Whether the latest attempt sent a fetch to the sidecar's judged-reply path."""
        self.resent = False
        """Whether the latest attempt has resent the request for the provider.

        It is cleared when the sidecar reports that the provider cut off a try
        that the sidecar passed on. If the sidecar still waits for a resend while
        this is set, it did not accept the resend, so Inspect doesn't resend
        again.
        """
        self.resends = 0
        """How many times the latest attempt has resent the request for the provider."""
        self.error_is_final = False
        """Whether the latest attempt's error is final.

        Set once Inspect has asked the sidecar about the attempt's last request
        and has nothing more to fetch or resend.
        """
        self.handled_failures: set[int] = set()
        """The numbers of the failed tries that Inspect has handled.

        The sidecar reports each try that failed at the provider. A try whose
        error the sidecar holds counts as handled once Inspect has fetched that
        error.
        """
        self.question_list_failures = 0
        """How many `list_pending_questions` calls in a row got no answer.

        The call didn't reach the sidecar, or its answer was lost. A
        `request_result` call in between doesn't reset the count.
        """
        self.answer_send_failures = 0
        """How many `answer_question` calls in a row got no answer.

        The call didn't reach the sidecar, or its answer was lost. A
        `list_pending_questions` or `request_result` call in between doesn't
        reset the count.
        """
        self.error_fetches: dict[int, int] = {}
        """The number of fetches of each failed try's provider error, by try number."""
        self.decisions: dict[str, tuple[str, str | None]] = {}
        """The person's choice and reason for each question shown, by question id.

        Inspect keeps them so that it never shows a question twice.
        """
        self.answer_details: dict[str, tuple[str, float]] = {}
        """Details of each question that a person answered here, by question id.

        Each entry is what the question was about, in words for a warning, and
        when the person answered, in seconds since the epoch.
        """
        self.reviews_logged: set[str] = set()
        """The ids of the resolved questions whose records are in the eval's log."""
        self.warned_unknown_answers: set[str] = set()
        """The ids of the answered questions that Inspect has warned about.

        A person answered each here, but the sidecar no longer holds the call's
        records. So Inspect can't tell whether the answer was used, and has
        logged a warning that says so.
        """
        self.settled_questions: set[str] = set()
        """The ids of the questions that need no answer sent.

        The sidecar accepted an answer to each, or no longer holds it.
        """
        self.usage_recorded: dict[str, dict[tuple[str | None, str], ModelUsage]] = {}
        """The judge models' usage already recorded, by request id, then role and model.

        The sidecar reports usage as a running total. Inspect asks about a paused
        call more than once under one id, so it records only what is new.
        """
        self.unasked: list[str] = []
        """The request ids of earlier attempts that were sent and that Inspect retried without asking the sidecar about them. The sidecar may have judged their requests with its own models, and is asked for that usage once the latest attempt is asked about."""
        self.try_sent_at: float | None = None
        """When the latest attempt's latest try went out, on the sample clock."""
        self.sends: list[Send] = []
        """The latest attempt's sends, in order.

        Recording starts when a send returns an error that Inspect asks the
        sidecar about. A paused call is sent more than once in one attempt. Only
        its sends are the model's time: the time between them is the person's
        and the sidecar's.
        """
        self.judging_before_attempt = 0.0
        """The sidecar's judging time for a paused call when the latest attempt began.

        Earlier attempts already counted that time as waiting.
        """
        self.judging_recorded: dict[str, float] = {}
        """The sidecar's judging time as last reported, by request id.

        The sidecar reports a running total for the call. So the amount added
        since the last report is the judging of the send that returned last.
        """


_received: ContextVar[ReceivedCall | None] = ContextVar(
    "sentinel_sidecar_call", default=None
)


@contextmanager
def receiving_call(
    sidecar: Any = None,
    registered_beforehand: bool = False,
    mode: "SentinelProxy" = "auto",
    history: "list[ChatMessage] | None" = None,
    timeout: int | None = None,
) -> Iterator[ReceivedCall]:
    """Keep what is learned of an agent call through a sidecar, for the providers to report its request id into.

    Args:
        sidecar: The sidecar the call goes through.
        registered_beforehand: Whether the sidecar's admin registered the call's
            task beforehand.
        mode: Whether the task requires a sidecar.
        history: The conversation the call is sent with. Inspect shows it to a
            person who is asked about the call.
        timeout: The call's `timeout`, in seconds, or None for no limit.
    """
    received = ReceivedCall(sidecar, registered_beforehand, mode, history, timeout)
    token = _received.set(received)
    try:
        yield received
    finally:
        _received.reset(token)


def begin_attempt() -> None:
    """Forget what was learned of an earlier attempt at the current agent call, which a retry supersedes, keeping its request id if it was sent and never asked about.

    A paused call keeps its id, its questions and its provider failures, because
    a retry of it is another try of the same model call at the sidecar.
    """
    received = _received.get()
    if received is not None:
        if received.began is None:
            received.began = time.monotonic()
        if (
            received.sent
            and received.request_id is not None
            and received.looked is None
            # A paused call keeps its id on a retry, and Inspect asks for its
            # usage under that id, so the id is not added to `unasked`.
            and received.request_id != received.reviewed_request_id
        ):
            received.unasked.append(received.request_id)
        received.request_id = None
        received.sent = False
        received.looked = None
        received.judgment = None
        received.fetching = False
        received.fetch_body = None
        received.reply_fetch_tried = False
        received.fetch_sent = False
        received.resent = False
        received.resends = 0
        received.error_is_final = False
        received.sends = []
        received.judging_before_attempt = (
            received.judging_recorded.get(received.reviewed_request_id, 0.0)
            if received.reviewed_request_id is not None
            else 0.0
        )


JUDGED_REPLY_PATH = "/sentinel/v1/judged-reply"
"""The path where a sidecar returns what it holds for a paused call.

Inspect fetches the provider's reply from it once the turn may go ahead, or the
provider's error once the provider has failed the call.
"""


def request_id_to_reuse() -> str | None:
    """The `x-irid` to reuse for the current agent call's next request, or None.

    Returns None unless a sentinel in a sidecar asked a person about the call.
    The sidecar keeps a paused call as one model call under its `x-irid`. So
    Inspect sends the call's later requests under that id: a fetch, a resend,
    and a retry of the call. Each send gets the id once, for the first request
    that the send begins.
    """
    received = _received.get()
    if received is None or received.request_id is not None:
        return None
    return received.reviewed_request_id


def route_fetch_to_sidecar(request: Any) -> None:
    """Send a fetch to the sidecar's judged-reply path, not to the model.

    A fetch is the model request that gets what the sidecar holds for the current
    paused call. Every other request is left unchanged: a request of a call that
    no sidecar judges, a request of a call that is not paused, and a resend for
    the provider. The SDK's retries of the fetch go to the same path. A later
    request that the provider's code makes in the same send, such as a
    continuation, has a different body and goes to the model.

    Args:
        request: The request about to be sent, as the SDK's HTTP client built it.
            Its path is replaced. Its origin and query are kept.
    """
    received = _received.get()
    if received is None or not received.fetching:
        return
    from inspect_ai.model._providers.util.hooks import HttpHooks

    if received.reviewed_request_id is None or (
        request.headers.get(HttpHooks.REQUEST_ID_HEADER) != received.reviewed_request_id
    ):
        return
    body = _body_digest(request)
    if received.fetch_body is None:
        received.fetch_body = body
    elif received.fetch_body != body:
        return
    request.url = request.url.copy_with(path=JUDGED_REPLY_PATH)
    received.fetch_sent = True


def _body_digest(request: Any) -> bytes:
    # A body that can't be read here, such as one that is still to be
    # streamed, is hashed as empty. So every unreadable body has the same
    # digest.
    try:
        content = request.content
    except Exception:
        content = b""
    return hashlib.sha256(content).digest()


def time_with_a_person() -> float:
    """Seconds that people took to answer questions about the current agent call.

    The call's `timeout` doesn't count this time. It is zero for a call that
    nobody was asked about.
    """
    received = _received.get()
    return received.person_time if received is not None else 0.0


def timeout_left(received: ReceivedCall) -> float | None:
    """How much of the call's `timeout` is left, in seconds, or None if it has none.

    It uses the same time that Inspect's retry loop compares with `timeout` when
    it decides whether to retry: the time since the call's first attempt began,
    less the time people took to answer. A `timeout` changed while the eval runs
    applies here, as it does there.
    """
    from inspect_ai.model._generate_overrides import generate_config_override

    timeout = generate_config_override("timeout", received.timeout)
    if timeout is None or received.began is None:
        return None
    return timeout - (time.monotonic() - received.began - received.person_time)


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
        received.try_sent_at = sample_clock()


def record_send(received: ReceivedCall) -> None:
    """Record a send of the latest attempt's request that has returned.

    Records nothing if no try of the request went out.
    """
    if received.sent and received.try_sent_at is not None:
        received.sends.append(Send(received.try_sent_at, sample_clock()))


def record_judging_time(received: ReceivedCall, judging_time: float | None) -> None:
    """Add the growth in the sidecar's judging time to the call's latest send.

    The sidecar reports its judging time for the call as a running total. It
    judges a send's request and reply before the send returns. It times a step
    that asked a person once the person has answered, before Inspect sends the
    call again. So the total grows only by the judging of the latest send.
    """
    if judging_time is None or received.request_id is None:
        return
    before = received.judging_recorded.get(received.request_id, 0.0)
    received.judging_recorded[received.request_id] = max(before, judging_time)
    if judging_time > before and received.sends:
        received.sends[-1].judging += judging_time - before


def parse_judgment(judgment: dict[str, Any]) -> Judgment:
    """A judgment, as a sidecar's `request_result` writes it.

    Raises:
        ValueError: If the judgment isn't one this Inspect can read.
    """
    try:
        return Judgment.model_validate(judgment)
    except ValidationError as ex:
        raise ValueError(f"The sidecar's judgment can't be read: {ex}") from ex
