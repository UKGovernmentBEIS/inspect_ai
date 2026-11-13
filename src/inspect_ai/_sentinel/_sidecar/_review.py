"""A person's review of a tool call that a sentinel in a sidecar asked for.

A person may take days to answer, so the sidecar holds no connection open for one. It answers the model call at once with an error that says the call is waiting, and keeps the call as one model call under the call's `x-irid`. Inspect asks `request_result` after any call that comes back as an error, and acts on what it says of the call:

- A question is open: Inspect shows it in its human approval surfaces, as it shows a question a sentinel in the eval's own process asks, and sends the person's answer.
- The sidecar waits for the request, to send it on to the provider: Inspect sends the same request again, under the same `x-irid`.
- The call is decided with the turn going on, and the sidecar holds the provider's reply: Inspect gets the held reply. It sends the same request again, under the same `x-irid`, to the sidecar's held-reply path, and the sidecar answers with the provider's reply in the provider's place.

Each request is sent with the provider's own client, and what comes back is read by the provider's own code, as any reply is. The provider is not called for a held reply.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import getLogger
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, cast

import anyio
from pydantic import TypeAdapter

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.http import status_code_of
from inspect_ai.approval._approval import ApprovalDecision
from inspect_ai.approval._human.approver import human_approver
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.util._limit import LimitExceededError

from .._person import HUMAN_CHOICES, chosen, escalation_lines, human_view
from ._endpoint import (
    QUESTION_ANSWERED,
    UNAUTHORIZED,
    UNKNOWN_QUESTION,
    SentinelProxyError,
    SidecarCallError,
)
from ._lookup import SAMPLE_FAILURES, Looked, request_result
from ._received import ReceivedCall, note_send

if TYPE_CHECKING:
    from inspect_ai.model._response_headers import ResponseHeaders

logger = getLogger(__name__)

NO_QUESTION_PAUSE = 0.5
"""How long to wait before asking the sidecar again when it says a question is open for the call and lists none, as when the question closed meanwhile, in seconds."""

CANCEL_TIMEOUT = 5.0
"""How long a call Inspect gives up on waits for the sidecar to take its cancellation, in seconds. The sidecar closes the call with its sample otherwise."""

FAILED_TRY = "x-sentinel-failed-try"
"""The header a sidecar adds to a provider's error it serves from its held-reply path: the number of the failed try the error is of. No refusal of the sidecar's own has it."""

MODEL_SENDS = 3
"""How many times one attempt at a call sends its request again for the sidecar to send on to the provider. Past that, the latest error stands, and Inspect retries or fails the call by its own rules, with its own waits: a provider whose exchanges keep being cut off isn't called again at once without end."""

FAILURE_FETCHES = 2
"""How many times the provider's error for one failed try is asked of the sidecar before the call's judgment is taken to be unavailable."""

_OWN_OUTCOMES: tuple[type[Exception], ...] = (
    LimitExceededError,
    TerminateSampleError,
    *SAMPLE_FAILURES,
)
"""The errors of a request sent again that are Inspect's own outcomes, which no sidecar explains."""

_TOOL_CALL = TypeAdapter(ToolCall)

R = TypeVar("R")


@dataclass
class AfterReview(Generic[R]):
    """What an agent call a person was asked about came to, once its request was sent again as the sidecar says."""

    reply: R | None = None
    """What the provider's `generate` returned for a request sent again that brought a reply."""
    raised: Exception | None = None
    """The error the last request sent again raised, where no request brought a reply."""
    handed_back: R | None = None
    """What the provider's `generate` returned for the last request sent again, where it handed back an error it didn't raise."""


async def result_after_review(
    received: ReceivedCall,
    send_again: Callable[[], Awaitable[R]],
    retried: bool,
    response_headers: "ResponseHeaders | None" = None,
) -> AfterReview[R]:
    """Send the request of an agent call a person was asked about again, as the sidecar says, and say what it came to.

    The sidecar has been asked what became of the call, and a person shown its questions. While the sidecar says there is a request to send, it is sent, and the sidecar asked again if it comes back as an error. A request is sent to get the reply the sidecar holds, to get the provider's error the sidecar holds, or for the sidecar to send on to the provider.

    A provider's error got from the sidecar is the call's error from then on: it is raised or handed back as the provider's own client gave it, and Inspect retries or fails the call for it by its own rules.

    Args:
        received: What is kept of the call, with what `request_result` last said of it.
        send_again: Sends the call's request with the provider's client, and returns what the provider's `generate` does.
        retried: Whether Inspect retries the error the call's own request came to.
        response_headers: Where the call's HTTP hooks keep the headers of its latest response. A provider's error the sidecar served is known by its header there, whether the provider's code raised it or read it as a reply.

    Raises:
        SentinelProxyError: If the sidecar won't take the eval's calls or a person's answer.
    """
    raised: Exception | None = None
    handed_back: R | None = None
    # the error the call's own request came to isn't handed here, so it is
    # known only by whether Inspect retries it
    held = _HeldError(retried=retried)
    while True:
        looked = received.looked
        if looked is None:
            looked = await request_result(received, replied=False)
        to_send = _request_to_send(received, looked, held)
        if to_send is None:
            received.error_stands = True
            return AfterReview(raised=raised, handed_back=handed_back)
        # the failed try whose error is asked of the sidecar, if that is what
        # is sent for
        fetching = (
            looked.failure.try_number
            if to_send == "failure" and looked.failure is not None
            else None
        )
        # the request sent again is a new send of the same model call, which
        # the HTTP hooks give the call's id
        received.getting_held_reply = to_send != "model"
        received.request_id = None
        received.sent = False
        received.looked = None
        received.judgment = None
        raised, handed_back = None, None
        if response_headers is not None:
            # so that only this send's response is read
            response_headers.latest = None
        try:
            result = await send_again()
        except _OWN_OUTCOMES:
            # Inspect's own outcomes, which no sidecar explains
            raise
        except Exception as ex:
            raised = ex
            if fetching is not None and _failed_try(ex) == fetching:
                return _provider_failed(received, fetching, AfterReview(raised=ex))
            held = _HeldError(status=status_code_of(ex), sent_again=True)
            continue
        finally:
            # timed however it ended, cancelled or cut short by a limit too
            note_send(received)
            received.getting_held_reply = False
            received.held_reply_body = None
            if received.request_id is None:
                # no request was begun, so the call keeps its id
                received.request_id = received.reviewed_id
        error = _error(result)
        if fetching is not None:
            marked = (
                _failed_try(error)
                if error is not None
                else _failed_try_of(
                    response_headers.latest if response_headers is not None else None
                )
            )
            if marked != fetching:
                # Not the provider's error the sidecar served, whatever the
                # provider's code made of the response: a refusal of the
                # sidecar's own, which that code may even read as a reply.
                # Nothing is taken from it, and the sidecar is asked again.
                held = _HeldError(
                    status=status_code_of(error) if error is not None else None,
                    sent_again=True,
                )
                continue
            if error is not None:
                return _provider_failed(
                    received, fetching, AfterReview(handed_back=result)
                )
            # The provider's error, which its own code reads as a reply, as
            # Anthropic's does a prompt that is too long. Inspect acts on it
            # as the call's result and sends nothing more, so the call is
            # closed at the sidecar, which still waits for its request.
            received.failures.add(fetching)
            await cancel_open_call(received)
            return AfterReview(reply=result)
        if error is None:
            # The call brought a reply, so the sidecar holds nothing open
            # for it. What the sidecar decided of it is asked as it is after
            # any reply.
            _closed(received)
            return AfterReview(reply=result)
        handed_back = result
        held = _HeldError(status=status_code_of(error), sent_again=True)


@dataclass
class _HeldError:
    # what is known of the error Inspect holds for the call's latest request
    status: int | None = None
    retried: bool = False
    """Whether Inspect retries the error. Known only of the error the call's own request came to."""
    sent_again: bool = False
    """Whether the error is one a request sent again here came to, so its status is known."""


def _error(result: object) -> Exception | None:
    # a provider hands back an error it didn't raise as its output
    output = result[0] if isinstance(result, tuple) and result else result
    return output if isinstance(output, Exception) else None


def _request_to_send(
    received: ReceivedCall, looked: Looked, held: _HeldError
) -> Literal["held_reply", "failure", "model"] | None:
    # Which request of the call is sent next, for what the sidecar says of
    # the call: `held_reply` to get the reply the sidecar holds, `failure` to
    # get the provider's error it holds, `model` for the sidecar to send on
    # to the provider, or None if nothing is sent and the latest error stands.
    if looked.state == "awaiting_request":
        failure = looked.failure
        if looked.reason is not None and failure is not None:
            # The provider's exchange failed, and the sidecar waits for the
            # request because of it. Inspect retries or fails a call for the
            # provider's error by its own rules.
            if failure.try_number in received.failures:
                return None
            if failure.status is not None:
                # The provider answered the try with an error, which the
                # sidecar holds. It is got from the sidecar and read as the
                # provider's own, whatever error Inspect holds for the call:
                # that one may be the sidecar's word that the call waited, for
                # a try it answered while another was with the provider.
                asked = received.failure_fetches.get(failure.try_number, 0)
                if asked >= FAILURE_FETCHES:
                    _unavailable(
                        received,
                        "the sidecar didn't answer with the provider's error it holds for the call",
                    )
                    return None
                received.failure_fetches[failure.try_number] = asked + 1
                return "failure"
            # The reply was cut off, so there is no error of the provider's
            # to get: the try failed as a connection does.
            received.failures.add(failure.try_number)
            if held.retried or (held.sent_again and held.status is None):
                # Inspect holds a failed connection, or an error it retries
                # anyway: it stands, and a retry is sent under the call's id
                return None
            received.sent_on_model_path = False
        elif held.retried:
            # Inspect sends the call again itself, under the call's id, after
            # its own wait
            return None
        if received.sent_on_model_path:
            # sent again already, and the sidecar still waits for it: it
            # didn't take the request for the same one
            _unavailable(
                received,
                "the sidecar didn't take the request sent again for the call it waits for",
            )
            return None
        if received.model_sends >= MODEL_SENDS:
            return None
        received.model_sends += 1
        received.sent_on_model_path = True
        return "model"
    if (
        looked.state == "decided"
        and looked.judgment is not None
        and looked.judgment.outcome == "proceed"
        and received.reviewed_id is not None
    ):
        if not received.asked_for_held_reply:
            received.asked_for_held_reply = True
            return "held_reply"
        # asked for already, and the request came back as an error
        _unavailable(
            received,
            "the sidecar didn't answer with the provider's reply it holds for the call"
            if received.held_reply_requested
            else "this model's client couldn't send a request to the sidecar's held-reply path",
        )
    return None


def _failed_try(error: BaseException) -> int | None:
    # The number of the failed try that an error is a provider's error of,
    # served by the sidecar's held-reply path, by the sidecar's own header on
    # the response the error was read from. None for anything else: a refusal
    # of the sidecar's own, and an error with no response read whole, as one
    # whose connection failed part way.
    return _failed_try_of(getattr(getattr(error, "response", None), "headers", None))


def _failed_try_of(headers: Any) -> int | None:
    # the number in the sidecar's header, where the headers have it. For a
    # result that a provider's code read from an error response, they are
    # those the call's HTTP hooks kept of its latest response, which was read
    # whole, as the provider's code made a result of it
    if headers is None:
        return None
    try:
        return int(headers.get(FAILED_TRY))
    except (TypeError, ValueError, AttributeError):
        return None


def _provider_failed(
    received: ReceivedCall, try_number: int, after: AfterReview[R]
) -> AfterReview[R]:
    # The provider's error for a failed try has been got from the sidecar,
    # whole. The try is acted on from here, and not before: a request for the
    # error that fails leaves it to be asked for again.
    received.failures.add(try_number)
    received.error_stands = True
    return after


def _unavailable(received: ReceivedCall, reason: str) -> None:
    received.looked = Looked("unavailable", reason)
    received.judgment = None


_REVIEW_FIELDS = (
    "id",
    "try_number",
    "stage",
    "call",
    "asked",
    "decision",
    "reason",
    "answered",
    "resolution",
    "cause",
    "resolved",
)
"""What a review record in the eval's log holds, as the sidecar's `request_result` gives it."""

_CAUSES = {
    "replaced_attempt": "a later attempt at the sample had begun",
    "sample_ended": "the sample had ended",
    "run_ended": "a sentinel had ended the run at another call",
    "cancelled": "the call had been cancelled",
    "stopped": "the sidecar had stopped it",
}
"""Why a question's wait was stopped, in words for the person who answered it."""


def note_reviews(received: ReceivedCall, result: dict[str, Any]) -> None:
    """Keep what the sidecar says became of each question a sentinel asked a person about the call.

    Each question's record goes into the eval's log once the question has ended, whether or not a step was judged with it, with the call's `x-irid` and the number of the try it was asked at. A person here whose answer the record shows wasn't used is told so, with why.

    Args:
        received: What is kept of the call.
        result: The sidecar's answer to `request_result`, with its records held.
    """
    from inspect_ai.log._transcript import transcript

    listed = result.get("reviews")
    for record in listed if isinstance(listed, list) else []:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            continue
        id = record["id"]
        if record.get("resolution") is None or id in received.reviews_logged:
            # still open, or in the log already
            continue
        received.reviews_logged.add(id)
        transcript().info(
            {
                "request": received.reviewed_id or received.request_id,
                "review": {
                    name: record[name]
                    for name in _REVIEW_FIELDS
                    if record.get(name) is not None
                },
            },
            source="sentinel sidecar",
        )
        _tell_if_unused(received, record, result)


def reviews_unavailable(received: ReceivedCall, records: str) -> None:
    """Tell a person here whose answer's fate can't be learned, as the sidecar no longer holds the call's records.

    Args:
        received: What is kept of the call.
        records: What the sidecar said of its records of the call: `dropped` or `unknown`.
    """
    for id, (decision, _) in received.decisions.items():
        if id in received.reviews_logged or id in received.answers_unknown:
            continue
        received.answers_unknown.add(id)
        function, _ = received.asked_about.get(id, ("a tool", 0.0))
        logger.warning(
            f"Inspect couldn't learn whether a person's answer ({decision}) to the sentinel sidecar's question about the call to {function} was used: the sidecar's records of the call are {records}."
        )


def _tell_if_unused(
    received: ReceivedCall, record: dict[str, Any], result: dict[str, Any]
) -> None:
    # A person here answered the question, and its record says what the
    # sentinel was given. An answer the sidecar took is not thereby one that
    # was used: the record says, and not whether the answer could be sent.
    id = record["id"]
    chosen = received.decisions.get(id)
    if chosen is None:
        return
    decision = chosen[0]
    resolution = record.get("resolution")
    if resolution == "answered" and record.get("decision") == decision:
        return
    function, answered_at = received.asked_about.get(id, ("a tool", 0.0))
    if resolution == "timed_out":
        why = "the question had timed out, where the sidecar's operator set a review timeout, and the sentinel was given the cautious answer"
    elif resolution == "cancelled":
        cause = str(record.get("cause"))
        why = f"the review had been stopped, as {_CAUSES.get(cause, cause)}"
    else:
        why = f"the sentinel was given another answer ({record.get('decision')})"
    logger.warning(
        f"A person's answer ({decision}) to the sentinel sidecar's question about the call to {function} wasn't used: {why}{_how_long_before(record, answered_at)}. {_came_to(result)}"
    )


def _how_long_before(record: dict[str, Any], answered_at: float) -> str:
    # how long before the person answered the question had ended, by the
    # sidecar's clock and Inspect's, which a signed call keeps close
    resolved = record.get("resolved")
    if not isinstance(resolved, (int, float)) or answered_at <= resolved:
        return ""
    minutes = round((answered_at - resolved) / 60)
    if minutes < 1:
        return ", less than a minute before the answer"
    return f", about {minutes} minute{'s' if minutes != 1 else ''} before the answer"


def _came_to(result: dict[str, Any]) -> str:
    # where the call stands, for the person whose answer wasn't used
    state = result.get("state")
    judgment = result.get("judgment")
    if state == "decided" and isinstance(judgment, dict):
        outcome = judgment.get("outcome")
        return {
            "proceed": "The call went on.",
            "reject": "The call was rejected.",
            "terminate": "The sample was ended.",
        }.get(str(outcome), f"The call came to {outcome}.")
    if state == "not_judged":
        return f"The call was not judged ({result.get('reason')})."
    if state == "awaiting_review":
        return "Another question is open for the call."
    return "The call has not ended yet."


async def ask_person(received: ReceivedCall) -> None:
    """Show a person each question the sidecar holds for the call, and send it their answers.

    Only the call's own questions are shown, by the call's `x-irid`, and each once, so no question is shown by two samples or twice by one.

    Raises:
        SentinelProxyError: If the sidecar won't take the eval's calls, or won't take the answer a person gave or the one that fails closed.
    """
    sidecar = received.sidecar
    try:
        result = await sidecar.eval_call(
            "pending_questions", {"sample_uuid": _sample_uuid()}
        )
    except SidecarCallError as ex:
        if ex.code == UNAUTHORIZED:
            raise _refused(sidecar, ex) from ex
        # asked again, with the call's state, after a pause
        await anyio.sleep(NO_QUESTION_PAUSE)
        return
    listed = result.get("questions")
    questions = [
        question
        for question in (listed if isinstance(listed, list) else [])
        if isinstance(question, dict)
        and question.get("request_id") == received.request_id
        and isinstance(question.get("id"), str)
        and question["id"] not in received.answered
    ]
    if not questions:
        # the question closed, or its answer is being taken
        await anyio.sleep(NO_QUESTION_PAUSE)
        return
    for question in questions:
        id = question["id"]
        if id not in received.decisions:
            received.decisions[id] = await _decision(received, question)
            call = question.get("call")
            function = call.get("function") if isinstance(call, dict) else None
            received.asked_about[id] = (str(function or "a tool"), time.time())
        # an answer the sidecar couldn't be sent is sent again, and the
        # person isn't asked again
        if await _answer(sidecar, id, *received.decisions[id]):
            received.answered.add(id)
        else:
            await anyio.sleep(NO_QUESTION_PAUSE)


async def _decision(
    received: ReceivedCall, question: dict[str, Any]
) -> tuple[str, str | None]:
    # what the person chose; a question Inspect can't show them fails closed
    choices = question.get("choices")
    offered: list[ApprovalDecision] = [
        cast(ApprovalDecision, choice)
        for choice in (choices if isinstance(choices, list) else [])
        if choice in HUMAN_CHOICES
    ]
    if not offered:
        raise SentinelProxyError(
            f"The sentinel sidecar at {received.sidecar.origin} asked a person a question with no choice Inspect can offer: {choices}."
        )
    try:
        return await _ask(question, offered, received.history)
    except Exception as ex:
        logger.warning(
            f"A question from the sentinel sidecar at {received.sidecar.origin} couldn't be shown to a person, so it is answered with caution: {ex}"
        )
        return (
            "reject" if "reject" in offered else "terminate",
            f"Inspect couldn't show the question to a person, so it failed closed ({ex}).",
        )


async def _ask(
    question: dict[str, Any],
    offered: list[ApprovalDecision],
    history: list[ChatMessage],
) -> tuple[ApprovalDecision, str | None]:
    # the question, in Inspect's human approval surfaces, as a sentinel in
    # the eval's own process asks one
    call = _TOOL_CALL.validate_python(question.get("call"))
    view = ToolCallView.model_validate(question.get("view") or {})
    escalations = [
        (str(escalation.get("name")), escalation.get("explanation"))
        for escalation in question.get("escalations") or []
        if isinstance(escalation, dict)
    ]
    result = question.get("result")
    approve = human_approver(choices=offered)
    approval = await approve(
        str(question.get("message") or ""),
        call,
        human_view(
            view,
            escalation_lines(escalations) if escalations else None,
            ChatMessageTool.model_validate(result) if result is not None else None,
        ),
        # the conversation as Inspect holds it, with each rejected call
        # redacted as the sidecar gave it, and not the sidecar's copy
        history,
    )
    return chosen(approval, offered)


async def _answer(sidecar: Any, id: str, decision: str, reason: str | None) -> bool:
    # whether the sidecar took the answer, or holds the question no longer
    try:
        await sidecar.answer_question(id, decision, reason)
    except SidecarCallError as ex:
        if ex.code in (UNKNOWN_QUESTION, QUESTION_ANSWERED):
            # The question closed while the person decided, as when it
            # expired or its call ended. What became of it is asked next, and
            # the person is told then that their answer wasn't used
            # (`note_reviews`).
            logger.debug(
                f"The sentinel sidecar at {sidecar.origin} no longer held a question when a person answered it: {ex}"
            )
            return True
        if ex.code is None:
            # the call didn't reach the sidecar, or its answer didn't come back
            logger.debug(
                f"A person's answer couldn't be sent to the sentinel sidecar at {sidecar.origin}: {ex}"
            )
            return False
        raise _refused(sidecar, ex) from ex
    return True


def _refused(sidecar: Any, ex: SidecarCallError) -> SentinelProxyError:
    return SentinelProxyError(
        f"The sentinel sidecar at {sidecar.origin} won't take the eval's calls about a person's review: {ex}"
    )


def _sample_uuid() -> str | None:
    from inspect_ai.log._samples import sample_active

    active = sample_active()
    return active.sample_uuid if active is not None else None


_open_calls: dict[str, dict[str, ReceivedCall]] = {}
"""The calls the sidecars hold open for each running sample, by the sample's uuid: each call's `x-irid`, with what is kept of the call."""


def opened(received: ReceivedCall) -> None:
    """Note that the sidecar holds the call open: a person was asked about it, and it has not ended."""
    received.reviewed_id = received.request_id
    received.open = True
    sample_uuid = _sample_uuid()
    if sample_uuid is not None and received.reviewed_id is not None:
        _open_calls.setdefault(sample_uuid, {})[received.reviewed_id] = received


def _closed(received: ReceivedCall) -> None:
    received.open = False
    sample_uuid = _sample_uuid()
    calls = _open_calls.get(sample_uuid) if sample_uuid is not None else None
    if calls is not None and received.reviewed_id is not None:
        calls.pop(received.reviewed_id, None)
        if not calls:
            _open_calls.pop(cast(str, sample_uuid), None)


def ended(received: ReceivedCall) -> None:
    """Note that the sidecar says the call has ended, so it holds it open no longer."""
    if received.open:
        _closed(received)


async def cancel_open_call(received: ReceivedCall | None) -> None:
    """Cancel, at the sidecar, a call a person was asked about that Inspect gives up on while the sidecar still holds it open.

    A call that is cancelled, or fails, while it waits for a person leaves a question nobody will answer, and a request the sidecar may still send on. The sidecar is told, so it closes the call with nothing decided. It doesn't wait long on a sidecar that doesn't answer, as a cancelled sample's teardown can't be interrupted: the sidecar closes the call when the sample ends, or at its run expiry.
    """
    if received is None or not received.open or received.reviewed_id is None:
        return
    _closed(received)
    await _cancel(received, received.reviewed_id)


async def cancel_open_calls(sample_uuid: str) -> None:
    """Cancel, at their sidecars, the calls a sample leaves open when it ends: those a person was asked about that nothing closed, as when the sample was cancelled while Inspect waited to retry one."""
    for request_id, received in _open_calls.pop(sample_uuid, {}).items():
        await _cancel(received, request_id)


async def _cancel(received: ReceivedCall, request_id: str) -> None:
    # The sidecar is told the call is given up, and is then asked once what
    # became of it, so that the record of a question the cancellation closed
    # is in the eval's log. A call closed only when its sample ends is too
    # late for that: the sample's log is written first. Neither holds up the
    # sample for long.
    sidecar = received.sidecar
    with anyio.CancelScope(shield=True), anyio.move_on_after(CANCEL_TIMEOUT):
        try:
            await sidecar.eval_call("cancel_request", {"id": request_id})
            result = await sidecar.eval_call(
                "request_result", {"id": request_id, "wait": 0}
            )
            if result.get("records") == "held":
                note_reviews(received, result)
        except Exception as ex:
            logger.debug(
                f"The sentinel sidecar at {sidecar.origin} couldn't be told a call was given up: {ex}"
            )
