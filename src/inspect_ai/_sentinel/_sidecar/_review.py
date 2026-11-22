"""Human review of a tool call, a model's turn or a model's request, asked for by a sentinel in a sidecar.

A person may take days to answer, so the sidecar holds no connection open
while it waits. It answers the model request at once with an error, and keeps
the call's state under the call's `x-irid`. The call is now paused.

Inspect calls the sidecar's `request_result` after an agent call returns an
error, and acts on the state it gets:

- `awaiting_review`: a question is open. Inspect shows it to a person with
  `human_approver`, the same way it shows a question from a sentinel inside
  the eval's own process. It sends the person's answer to the sidecar.
- `awaiting_resend`: the provider still has to be called. Inspect resends the
  request under the same `x-irid`, and the proxy passes it on to the provider.
- `decided`, with the outcome `proceed`: the sidecar holds the provider's
  reply. Inspect fetches it from the sidecar's judged-reply path. The provider
  is not called again.

Inspect makes every fetch and resend with the provider's own client, so the
provider's own code reads the response as it reads any reply.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import getLogger
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, cast

import anyio
from pydantic import BaseModel, TypeAdapter

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.http import status_code_of
from inspect_ai.approval._approval import ApprovalDecision
from inspect_ai.approval._human.approver import human_approver
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.util._limit import LimitExceededError

from .._person import (
    HUMAN_CHOICES,
    approve_with_text_in_view,
    ask_about_request,
    ask_about_turn,
    chosen_decision,
    escalation_lines,
    held_call_view,
    human_view,
)
from ._endpoint import (
    QUESTION_ANSWERED,
    UNKNOWN_QUESTION,
    SentinelProxyError,
    SidecarCallError,
)
from ._lookup import (
    SAMPLE_FAILURES,
    Answer,
    Looked,
    ask_request_result,
    request_result,
)
from ._received import ReceivedCall, record_send

if TYPE_CHECKING:
    from inspect_ai.model._response_headers import ResponseHeaders

logger = getLogger(__name__)

NO_QUESTION_PAUSE = 0.5
"""Seconds to wait before asking again when the sidecar lists no question for the call.

The sidecar said a question was open. So the question closed in between, or the
sidecar is still processing its answer.
"""

CANCEL_TIMEOUT = 5.0
"""Seconds Inspect waits for the sidecar to accept the cancellation of a paused call.

If the sidecar doesn't answer in time, it closes the call later, when the
sample ends.
"""

FAILED_TRY_HEADER = "x-sentinel-failed-try"
"""The header that marks a provider's error fetched from the sidecar.

The sidecar adds it to a provider's error that it returns from its judged-reply
path. Its value is the number of the try that failed. The sidecar's own refusals
never have it.
"""

MAX_RESENDS = 3
"""The most times one attempt at a call resends its request for the provider.

After that, Inspect keeps the latest error, and retries or fails the call by its
usual rules, with its usual waits. Without the limit, Inspect would call a
provider whose replies keep getting cut off again and again, with no wait.
"""

MAX_ERROR_FETCHES = 2
"""The most times Inspect tries to fetch the provider's error for one failed try.

After that, Inspect treats the call's judgment as unavailable.
"""

_INSPECT_OWN_ERRORS: tuple[type[Exception], ...] = (
    LimitExceededError,
    TerminateSampleError,
    *SAMPLE_FAILURES,
)
"""Errors that Inspect itself raises during a fetch or a resend.

They are a limit, a terminated sample and a failed sample. Inspect re-raises
them at once, because the sidecar has nothing to say about them.
"""

_TOOL_CALL = TypeAdapter(ToolCall)

R = TypeVar("R")


@dataclass
class PausedCallResult(Generic[R]):
    """The result of a model call that was paused for human review."""

    reply: R | None = None
    """The reply, if a fetch or a resend returned one."""
    raised: Exception | None = None
    """The error that the last fetch or resend raised, if none returned a reply."""
    returned_error: R | None = None
    """The error that the last fetch or resend returned without raising it.

    A provider's `generate` can return an error as its output. Set only if no
    fetch or resend returned a reply.
    """


async def finish_paused_call(
    received: ReceivedCall,
    send_again: Callable[[], Awaitable[R]],
    will_retry: bool,
    response_headers: "ResponseHeaders | None" = None,
) -> PausedCallResult[R]:
    """Get the result of a model call that was paused for human review.

    The sidecar holds no connection open while a person decides. So the
    original request returned an error, and the sidecar kept the call's
    state. Inspect has now sent the person's answer to the sidecar. It does
    not yet know what the sentinel decided after that answer, or whether the
    provider has replied.

    So Inspect gets the call's state from the sidecar's `request_result`,
    and acts on it:

    - `decided`, with the outcome `proceed`: the sentinel let the turn go
      ahead, but Inspect has no reply yet. `request_result` returns the
      decision, and the sidecar holds the provider's reply. Inspect fetches
      the reply from the sidecar's judged-reply path (`JUDGED_REPLY_PATH`).
    - `awaiting_resend`, with a provider error in `failure`: the provider
      failed the call, and the sidecar holds its error. Inspect fetches the
      error the same way, then treats it as it treats any provider error.
    - `awaiting_resend` otherwise: the provider still has to be called, and
      only the proxy calls it. Inspect resends the request as an ordinary
      model request, through the proxy. If Inspect is already retrying the
      original error, that retry is the resend.
    - Any other state, such as `decided` with `reject`: Inspect sends
      nothing. The caller acts on the sidecar's decision.

    A fetch and a resend both call `send_again`, which sends the call's
    model request. For a fetch, Inspect's HTTP hook sends that request to
    the judged-reply path, because only the provider's client code can read
    the reply, and that code can only send its model request. The sidecar
    ignores the body, finds the call by its `x-irid`, and returns what it
    holds. The provider is not called.

    A fetch or a resend can fail, and a resend can be paused for another
    question. So if one returns an error, Inspect gets the state again. It
    resends at most `MAX_RESENDS` times, and fetches one error at most
    `MAX_ERROR_FETCHES` times.

    Args:
        received: Inspect's record of the call, including the state that
            `request_result` last returned.
        send_again: Sends the call's model request again, and returns what
            the provider's `generate` returns.
        will_retry: Whether Inspect will retry the error that the original
            request returned.
        response_headers: The headers of the latest response. The sidecar's
            `x-sentinel-failed-try` header marks a provider error that was
            fetched from the sidecar.

    Returns:
        The reply, if a fetch or a resend returned one. Otherwise the last
        error one returned, or nothing if no request was sent.

    Raises:
        SentinelProxyError: If the sidecar refuses Inspect's
            `request_result` call or the person's answer.
    """
    raised: Exception | None = None
    returned_error: R | None = None
    # This function is not given the original request's error. It knows only
    # whether Inspect will retry it.
    latest = _LatestError(will_retry=will_retry)
    while True:
        if received.error_is_final:
            # The fetch or resend just made stopped the call, as when the
            # sidecar wouldn't take the sample's registration again. Nothing
            # more is asked, fetched or resent here, and Inspect cleans up
            # after the call where it stops retrying.
            return PausedCallResult(raised=raised, returned_error=returned_error)
        looked = received.looked
        if looked is None:
            looked = await request_result(received, replied=False)
        step = _next_step(received, looked, latest)
        if step is None:
            received.error_is_final = True
            return PausedCallResult(raised=raised, returned_error=returned_error)
        # the number of the failed try whose error this step fetches, if it
        # fetches one
        error_try = (
            looked.failure.try_number
            if step == "fetch_error" and looked.failure is not None
            else None
        )
        # A fetch or a resend is a new request for the same model call. Reset
        # the per-request state, and clear `request_id` so that the HTTP hook
        # reuses the call's `x-irid`.
        received.fetching = step != "resend"
        received.request_id = None
        received.sent = False
        received.looked = None
        received.judgment = None
        raised, returned_error = None, None
        if response_headers is not None:
            # so that only this request's response headers are read
            response_headers.latest = None
        try:
            result = await send_again()
        except _INSPECT_OWN_ERRORS:
            # raised by Inspect itself, so the sidecar has nothing to say
            raise
        except Exception as ex:
            raised = ex
            if error_try is not None and _failed_try_number(ex) == error_try:
                return _record_fetched_failure(
                    received, error_try, PausedCallResult(raised=ex)
                )
            latest = _LatestError(status=status_code_of(ex), from_later_send=True)
            continue
        finally:
            # Record the request's time however it ended, including when it
            # was cancelled or stopped by a limit.
            record_send(received)
            received.fetching = False
            received.fetch_body = None
            if received.request_id is None:
                # The HTTP hook never ran, so no request was sent. Restore
                # the call's id.
                received.request_id = received.reviewed_request_id
        error = _returned_exception(result)
        if error_try is not None:
            marked = (
                _failed_try_number(error)
                if error is not None
                else _failed_try_number_in(
                    response_headers.latest if response_headers is not None else None
                )
            )
            if marked != error_try:
                # The response is not the provider's error that Inspect tried
                # to fetch, because it lacks the sidecar's header for that
                # try. It is the sidecar's own refusal, which the provider's
                # code may even have read as a reply. Inspect ignores it and
                # gets the state again.
                latest = _LatestError(
                    status=status_code_of(error) if error is not None else None,
                    from_later_send=True,
                )
                continue
            if error is not None:
                return _record_fetched_failure(
                    received, error_try, PausedCallResult(returned_error=result)
                )
            # The fetched provider error is one that the provider's code
            # reads as a reply, as Anthropic's code reads a prompt that is too
            # long. Inspect uses it as the call's result and sends nothing
            # more. The sidecar still waits for a resend, so Inspect cancels
            # the call there.
            received.handled_failures.add(error_try)
            await cancel_paused_call(received)
            return PausedCallResult(reply=result)
        if error is None:
            # A reply. The caller asks the sidecar for its decision on it
            # with `request_result`, as it does after any reply. A fetched
            # reply belongs to a call that has ended at the sidecar, so the
            # call is no longer paused. A reply to a resend may be a provider
            # error that the provider's code read as a reply. The sidecar then
            # still waits for a resend, so the call stays marked as paused
            # until the caller has asked.
            if step != "resend":
                _clear_paused(received)
            return PausedCallResult(reply=result)
        returned_error = result
        latest = _LatestError(status=status_code_of(error), from_later_send=True)


@dataclass
class _LatestError:
    # What Inspect knows about the error from the call's latest request.
    status: int | None = None
    will_retry: bool = False
    """Whether Inspect will retry the error.

    Known only for the original request's error.
    """
    from_later_send: bool = False
    """Whether the error is from a fetch or a resend made here.

    If so, its status is known.
    """


def _returned_exception(result: object) -> Exception | None:
    # A provider's `generate` can return an error as its output without
    # raising it.
    output = result[0] if isinstance(result, tuple) and result else result
    return output if isinstance(output, Exception) else None


def _next_step(
    received: ReceivedCall, looked: Looked, latest: _LatestError
) -> Literal["fetch_reply", "fetch_error", "resend"] | None:
    # The next step for the call's state: `fetch_reply` to fetch the reply
    # the sidecar holds, `fetch_error` to fetch the provider's error it holds,
    # `resend` to resend the request for the provider, or None to send nothing
    # and keep the latest error.
    if looked.state == "awaiting_resend":
        failure = looked.failure
        if looked.reason is not None and failure is not None:
            # The provider failed a request that the sidecar passed on, and
            # the sidecar waits for a resend. If the try's number is in
            # `handled_failures`, Inspect has already handled this failure:
            # it sends nothing, and retries or fails the call by its usual
            # rules.
            if failure.try_number in received.handled_failures:
                return None
            if failure.status is not None:
                # The provider returned an error, and the sidecar holds it.
                # Inspect fetches it and reads it as the provider's own. It
                # doesn't use the error it already holds for the call, because
                # that may be a "pending review" error: the sidecar's answer
                # to one try while another try was with the provider.
                asked = received.error_fetches.get(failure.try_number, 0)
                if asked >= MAX_ERROR_FETCHES:
                    _mark_judgment_unavailable(
                        received,
                        "the sidecar didn't answer with the provider's error it holds for the call",
                    )
                    return None
                received.error_fetches[failure.try_number] = asked + 1
                return "fetch_error"
            # The provider's reply was cut off, so there is no provider error
            # to fetch. The try failed the way a dropped connection does.
            received.handled_failures.add(failure.try_number)
            if latest.will_retry or (latest.from_later_send and latest.status is None):
                # Inspect already holds an error it will retry, or a failed
                # connection from a fetch or a resend. It keeps that error,
                # and its own retry resends under the call's `x-irid`.
                return None
            received.resent = False
        elif latest.will_retry:
            # Inspect is already retrying the original error. That retry is
            # the resend: it goes out under the call's `x-irid`, after
            # Inspect's usual wait.
            return None
        if received.resent:
            # Inspect already resent the request, and the sidecar still waits
            # for a resend. So the sidecar didn't accept that request as the
            # paused call's.
            _mark_judgment_unavailable(
                received,
                "the sidecar didn't accept the resent request as the paused call's",
            )
            return None
        if received.resends >= MAX_RESENDS:
            return None
        received.resends += 1
        received.resent = True
        return "resend"
    if (
        looked.state == "decided"
        and looked.judgment is not None
        and looked.judgment.outcome == "proceed"
        and received.reviewed_request_id is not None
    ):
        if not received.reply_fetch_tried:
            received.reply_fetch_tried = True
            return "fetch_reply"
        # Inspect already tried to fetch the reply, and the fetch returned an
        # error.
        _mark_judgment_unavailable(
            received,
            "the sidecar didn't answer with the provider's reply it holds for the call"
            if received.fetch_sent
            else "this model's client couldn't send a request to the sidecar's judged-reply path",
        )
    return None


def _failed_try_number(error: BaseException) -> int | None:
    # The try's number, if `error` is a provider's error fetched from the
    # sidecar's judged-reply path. The sidecar's `x-sentinel-failed-try` header
    # on the error's response gives the number. None for anything else: the
    # sidecar's own refusal, or an error with no complete response, such as a
    # connection that failed part way.
    return _failed_try_number_in(
        getattr(getattr(error, "response", None), "headers", None)
    )


def _failed_try_number_in(headers: Any) -> int | None:
    # The try's number from the sidecar's `x-sentinel-failed-try` header, or
    # None if the headers lack it. When a provider's code read an error
    # response as a result, there is no error to take headers from. The
    # caller then passes the headers that the HTTP hook stored for the latest
    # response.
    if headers is None:
        return None
    try:
        return int(headers.get(FAILED_TRY_HEADER))
    except (TypeError, ValueError, AttributeError):
        return None


def _record_fetched_failure(
    received: ReceivedCall, try_number: int, after: PausedCallResult[R]
) -> PausedCallResult[R]:
    # Inspect has fetched the provider's error for a failed try. Only now is
    # the failure recorded as handled, so that a fetch that fails can be tried
    # again.
    received.handled_failures.add(try_number)
    received.error_is_final = True
    return after


def _mark_judgment_unavailable(received: ReceivedCall, reason: str) -> None:
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
"""The fields of a `request_result` review record that go into the eval's log."""

_CAUSES = {
    "replaced_attempt": "a later attempt at the sample had begun",
    "sample_ended": "the sample had ended",
    "run_ended": "a sentinel had ended the run at another call",
    "cancelled": "the call had been cancelled",
    "stopped": "the sidecar had stopped it",
}
"""Why a question was cancelled, worded for the person who answered it."""


def log_reviews(received: ReceivedCall, result: dict[str, Any]) -> None:
    """Log the sidecar's record of each resolved question about the call.

    `request_result` returns a record for each question a sentinel asked a
    person about the call. Once a question is resolved (answered, timed out or
    cancelled), Inspect writes its record to the eval's log with the call's
    `x-irid`. It logs each record once, whether or not the call was judged. If
    the record shows that an answer a person gave here wasn't used, Inspect
    logs a warning that says why.

    Args:
        received: Inspect's record of the call.
        result: The sidecar's answer to `request_result`.
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
                "request": received.reviewed_request_id or received.request_id,
                "review": {
                    name: record[name]
                    for name in _REVIEW_FIELDS
                    if record.get(name) is not None
                },
            },
            source="sentinel sidecar",
        )
        _warn_if_answer_unused(received, record, result)


def warn_reviews_unavailable(received: ReceivedCall, records: str) -> None:
    """Warn that Inspect can't learn whether a person's answers were used.

    The sidecar no longer holds the call's records, so Inspect can't read what
    happened to the questions a person answered here. It warns once for each
    such answer.

    Args:
        received: Inspect's record of the call.
        records: The sidecar's `records` value for the call: `dropped` or
            `unknown`.
    """
    for id, (decision, _) in received.decisions.items():
        if id in received.reviews_logged or id in received.warned_unknown_answers:
            continue
        received.warned_unknown_answers.add(id)
        about, _ = received.answer_details.get(id, (_ABOUT_A_CALL, 0.0))
        logger.warning(
            f"Inspect couldn't learn whether a person's answer ({decision}) to the sentinel sidecar's question about {about} was used: the sidecar's records of the call are {records}."
        )


def _warn_if_answer_unused(
    received: ReceivedCall, record: dict[str, Any], result: dict[str, Any]
) -> None:
    # Warn the person who answered this question here, if the sentinel was not
    # given their answer. The record says what the sentinel was given. That
    # the sidecar accepted the answer doesn't show that it was used.
    id = record["id"]
    chosen = received.decisions.get(id)
    if chosen is None:
        return
    decision = chosen[0]
    resolution = record.get("resolution")
    if resolution == "answered" and record.get("decision") == decision:
        return
    about, answered_at = received.answer_details.get(id, (_ABOUT_A_CALL, 0.0))
    if resolution == "timed_out":
        why = "the question had timed out, where the sidecar's operator set a review timeout, and the sentinel was given the cautious answer"
    elif resolution == "cancelled":
        cause = str(record.get("cause"))
        why = f"the review had been stopped, as {_CAUSES.get(cause, cause)}"
    else:
        why = f"the sentinel was given another answer ({record.get('decision')})"
    logger.warning(
        f"A person's answer ({decision}) to the sentinel sidecar's question about {about} wasn't used: {why}{_time_before_answer_text(record, answered_at)}. {_call_status_text(result)}"
    )


def _time_before_answer_text(record: dict[str, Any], answered_at: float) -> str:
    # Text saying how long before the person's answer the question was
    # resolved. It compares the sidecar's clock with Inspect's. The two are
    # close, because the sidecar refuses a signed call whose timestamp is more
    # than its window (5 minutes by default) from its own clock.
    resolved = record.get("resolved")
    if not isinstance(resolved, (int, float)) or answered_at <= resolved:
        return ""
    minutes = round((answered_at - resolved) / 60)
    if minutes < 1:
        return ", less than a minute before the answer"
    return f", about {minutes} minute{'s' if minutes != 1 else ''} before the answer"


def _call_status_text(result: dict[str, Any]) -> str:
    # A sentence saying where the call stands now, for the person whose
    # answer wasn't used.
    state = result.get("state")
    judgment = result.get("judgment")
    if state == "decided" and isinstance(judgment, dict):
        outcome = judgment.get("outcome")
        return {
            "proceed": "The call went ahead.",
            "reject": "The call was rejected.",
            "terminate": "The sample was ended.",
        }.get(str(outcome), f"The call ended with the outcome {outcome}.")
    if state == "not_judged":
        return f"The call was not judged ({result.get('reason')})."
    if state == "awaiting_review":
        return "Another question is open for the call."
    return "The call has not ended yet."


async def ask_person(received: ReceivedCall) -> None:
    """Show a person each open question for the call, and send their answers.

    Inspect lists the sample's open questions with `list_pending_questions`,
    and shows only those whose `request_id` is this call's `x-irid`. It shows
    each question once. So two samples never show the same question, and one
    sample never shows it twice.

    Raises:
        SentinelProxyError: If the sidecar refuses Inspect's calls, or refuses
            an answer: the person's, or the cautious one Inspect sends when it
            can't show the question.
    """
    sidecar = received.sidecar
    try:
        result = await sidecar.eval_call(
            "list_pending_questions", {"sample_uuid": _sample_uuid()}
        )
    except SidecarCallError as ex:
        if ex.code is not None:
            # The sidecar answered with an error of its own, as it does for a
            # call it can't read or refuses. Asking again would get the same
            # answer, so the review fails here.
            raise _refusal_error(sidecar, ex) from ex
        # The call didn't reach the sidecar, or its answer was lost. Inspect
        # waits and returns, and the caller asks again. Inspect gives up after
        # `LOOKUP_RETRIES` failures in a row, the same limit as for a lost
        # `request_result`. The limit bounds how long Inspect goes on without
        # reaching the sidecar. It doesn't bound how long a person may take.
        from ._lookup import LOOKUP_RETRIES, LOOKUP_RETRY_PAUSE

        received.question_list_failures += 1
        if received.question_list_failures > LOOKUP_RETRIES:
            raise SentinelProxyError(
                f"The sentinel sidecar at {sidecar.origin} couldn't be asked for the questions it holds for a person: {ex}"
            ) from ex
        await anyio.sleep(
            LOOKUP_RETRY_PAUSE * 2 ** (received.question_list_failures - 1)
        )
        return
    received.question_list_failures = 0
    listed = result.get("questions")
    if not isinstance(listed, list) or not all(
        isinstance(question, dict)
        and isinstance(question.get("id"), str)
        and isinstance(question.get("request_id"), str)
        for question in listed
    ):
        # Inspect never treats a list it can't read as an empty list. The
        # sidecar would keep saying a question is open, and Inspect would
        # keep asking with nothing to show a person. The error leaves out
        # the list's contents, because a question holds a call's arguments.
        raise SentinelProxyError(
            f"The sentinel sidecar at {sidecar.origin} listed the questions it holds for a person in a form Inspect can't read."
        )
    questions = [
        question
        for question in listed
        if question["request_id"] == received.request_id
        and question["id"] not in received.settled_questions
    ]
    if not questions:
        # The question closed, or the sidecar is still processing its answer.
        await anyio.sleep(NO_QUESTION_PAUSE)
        return
    for question in questions:
        id = question["id"]
        if id not in received.decisions:
            # The time the person takes to decide is counted apart from
            # the model call's time.
            shown = time.monotonic()
            try:
                received.decisions[id] = await _get_decision(received, question)
            finally:
                received.person_time += time.monotonic() - shown
            received.answer_details[id] = (_asked_about(question), time.time())
        # If the answer doesn't reach the sidecar, Inspect sends the stored
        # answer again later, and doesn't ask the person again. It waits
        # between sends, and gives up after `LOOKUP_RETRIES` failures in a
        # row, as for a lost `request_result`. Meanwhile the sidecar keeps
        # saying the question is open, which doesn't reset the count.
        lost = await _send_answer(sidecar, id, *received.decisions[id])
        if lost is None:
            received.answer_send_failures = 0
            received.settled_questions.add(id)
            continue
        from ._lookup import LOOKUP_RETRIES, LOOKUP_RETRY_PAUSE

        received.answer_send_failures += 1
        if received.answer_send_failures > LOOKUP_RETRIES:
            raise SentinelProxyError(
                f"A person's answer couldn't be sent to the sentinel sidecar at {sidecar.origin}: {lost}"
            ) from lost
        await anyio.sleep(LOOKUP_RETRY_PAUSE * 2 ** (received.answer_send_failures - 1))


async def _get_decision(
    received: ReceivedCall, question: dict[str, Any]
) -> tuple[str, str | None]:
    # Returns the person's choice and their reason. If Inspect can't show
    # the question, it answers with caution: `reject` if offered, otherwise
    # `terminate`.
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
        return await _show_question(question, offered, received.history)
    except Exception as ex:
        # Only the error's type is reported. Its text may contain the
        # question's contents: a validation error quotes the values it
        # couldn't read, and those include the call's arguments. The warning
        # goes into the eval's log, and the reason is shown to the model for
        # the rejected call.
        failed = type(ex).__name__
        logger.warning(
            f"A question from the sentinel sidecar at {received.sidecar.origin} couldn't be shown to a person, so it is answered with caution ({failed})."
        )
        return (
            "reject" if "reject" in offered else "terminate",
            f"Inspect couldn't show the question to a person, so it failed closed ({failed}).",
        )


_ABOUT_A_CALL = "the call to a tool"
"""What a question is about, where Inspect didn't keep the call's name."""


def _asked_about(question: dict[str, Any]) -> str:
    # what the question is about, in words for a warning
    if question.get("stage") == _REQUEST_STAGE:
        return "the model's request"
    if question.get("stage") == _TURN_STAGE:
        return "the model's turn"
    call = question.get("call")
    function = call.get("function") if isinstance(call, dict) else None
    return f"the call to {function}" if function else _ABOUT_A_CALL


_TURN_STAGE = "model_output"
"""The stage of a question about a model's whole turn, asked after a generate."""

_CALL_STAGE = "tool_call"
"""The stage of a question about a call that has not run. The sidecar holds the reply that makes it."""

_REQUEST_STAGE = "model_input"
"""The stage of a question about the request a model is about to be sent, asked before a generate."""


class _MessageShown(BaseModel):
    # one message of a request that the model has not been sent before
    position: int
    message: ChatMessage


class _RequestShown(BaseModel):
    # the request that a question before a generate is about, as the sidecar
    # writes it
    model: str
    messages: int
    new: list[_MessageShown]
    tools: list[str]
    tool_choice: Literal["auto", "any", "none", "function"]
    tool_function: str | None = None

    def choice(self) -> ToolChoice:
        if self.tool_choice != "function":
            return self.tool_choice
        if self.tool_function is None:
            raise ValueError("The request names no function the model must call.")
        return ToolFunction(name=self.tool_function)


_REQUEST = TypeAdapter(_RequestShown)


async def _show_question(
    question: dict[str, Any],
    offered: list[ApprovalDecision],
    history: list[ChatMessage],
) -> tuple[ApprovalDecision, str | None]:
    # Shows the question with Inspect's `human_approver`, the same way a
    # sentinel inside the eval's own process asks one.
    escalations = [
        (str(escalation.get("name")), escalation.get("explanation"))
        for escalation in question.get("escalations") or []
        if isinstance(escalation, dict)
    ]
    approve = human_approver(choices=offered)
    if question.get("stage") == _REQUEST_STAGE:
        request = _REQUEST.validate_python(question.get("request"))
        approval = await ask_about_request(
            approve,
            request.model,
            request.messages,
            [(shown.position, shown.message) for shown in request.new],
            request.tools,
            request.choice(),
            escalations,
            offered,
            # Inspect's own copy of the conversation, as below
            history,
        )
        return chosen_decision(approval, offered)
    if question.get("stage") == _TURN_STAGE:
        turn = question.get("turn")
        approval = await ask_about_turn(
            approve,
            ChatMessageAssistant.model_validate(turn) if turn is not None else None,
            escalations,
            offered,
            # Inspect's own copy of the conversation, as below
            history,
            # The sidecar holds the reply, so Inspect has streamed none of the
            # turn to the person.
            content_in_view=True,
        )
        return chosen_decision(approval, offered)
    call = _TOOL_CALL.validate_python(question.get("call"))
    view = ToolCallView.model_validate(question.get("view") or {})
    result = question.get("result")
    said = str(question.get("message") or "")
    escalated = escalation_lines(escalations) if escalations else None
    if question.get("stage") == _CALL_STAGE:
        # The sidecar holds the reply here too, so the view shows what the
        # turn holds besides its calls.
        turn = question.get("turn")
        approval = await approve_with_text_in_view(
            approve,
            said,
            call,
            held_call_view(
                view,
                call,
                escalated,
                ChatMessageAssistant.model_validate(turn)
                if turn is not None
                else ChatMessageAssistant(content=said),
            ),
            # Inspect's own copy of the conversation, as below
            history,
        )
        return chosen_decision(approval, offered)
    approval = await approve(
        said,
        call,
        human_view(
            view,
            escalated,
            ChatMessageTool.model_validate(result) if result is not None else None,
        ),
        # Inspect's own copy of the conversation, not the sidecar's. Each
        # rejected call in it is redacted, as the sidecar returned it.
        history,
    )
    return chosen_decision(approval, offered)


async def _send_answer(
    sidecar: Any, id: str, decision: str, reason: str | None
) -> SidecarCallError | None:
    # Returns None if the sidecar accepted the answer, or no longer holds the
    # question. Otherwise returns the error that kept the answer from
    # reaching the sidecar.
    try:
        await sidecar.answer_question(id, decision, reason)
    except SidecarCallError as ex:
        if ex.code in (UNKNOWN_QUESTION, QUESTION_ANSWERED):
            # The question closed while the person decided, for example
            # because it expired or its call ended. The next `request_result`
            # returns its record, and `log_reviews` then warns the person
            # that their answer wasn't used.
            logger.debug(
                f"The sentinel sidecar at {sidecar.origin} no longer held a question when a person answered it: {ex}"
            )
            return None
        if ex.code is None:
            # The call didn't reach the sidecar, or its answer was lost.
            logger.debug(
                f"A person's answer couldn't be sent to the sentinel sidecar at {sidecar.origin}: {ex}"
            )
            return ex
        raise _refusal_error(sidecar, ex) from ex
    return None


def _refusal_error(sidecar: Any, ex: SidecarCallError) -> SentinelProxyError:
    return SentinelProxyError(
        f"The sentinel sidecar at {sidecar.origin} won't take the eval's calls about a person's review: {ex}"
    )


def _sample_uuid() -> str | None:
    from inspect_ai.log._samples import sample_active

    active = sample_active()
    return active.sample_uuid if active is not None else None


_paused_calls: dict[str, dict[str, ReceivedCall]] = {}
"""The paused calls of each running sample.

Keyed by the sample's uuid, then by the call's `x-irid`. Each value is Inspect's
record of the call.
"""


def mark_paused(received: ReceivedCall) -> None:
    """Record that the sidecar has paused the call for a person's review.

    Inspect stores the call's `x-irid`, so that every later request for the call
    reuses it.
    """
    received.reviewed_request_id = received.request_id
    received.paused = True
    sample_uuid = _sample_uuid()
    if sample_uuid is not None and received.reviewed_request_id is not None:
        _paused_calls.setdefault(sample_uuid, {})[received.reviewed_request_id] = (
            received
        )


def _clear_paused(received: ReceivedCall) -> None:
    received.paused = False
    sample_uuid = _sample_uuid()
    calls = _paused_calls.get(sample_uuid) if sample_uuid is not None else None
    if calls is not None and received.reviewed_request_id is not None:
        calls.pop(received.reviewed_request_id, None)
        if not calls:
            _paused_calls.pop(cast(str, sample_uuid), None)


def mark_ended(received: ReceivedCall) -> None:
    """Record that the call has ended at the sidecar, so it is no longer paused."""
    if received.paused:
        _clear_paused(received)


async def cancel_paused_call(received: ReceivedCall | None) -> Answer | None:
    """Tell the sidecar to cancel a paused call that Inspect has given up on.

    When Inspect cancels or fails a call that is paused, the sidecar is left
    with a question nobody will answer, and may still pass a request for the
    call on to the provider. So Inspect calls `cancel_paused_request`, and the
    sidecar closes the call with nothing decided.

    Inspect waits at most `CANCEL_TIMEOUT` seconds for the sidecar, because the
    teardown of a cancelled sample can't be interrupted. If the sidecar doesn't
    answer, it closes the call when the sample ends, or when the run expires.

    Returns:
        What the sidecar then said of the call with `request_result`, or None if nothing was cancelled or it didn't say.
    """
    if received is None or not received.paused or received.reviewed_request_id is None:
        return None
    _clear_paused(received)
    return await _cancel(received, received.reviewed_request_id)


async def cancel_call_by_id(
    received: ReceivedCall,
) -> Answer | None:
    """Tell the sidecar to cancel a call Inspect has given up on, where Inspect couldn't learn whether the sidecar paused it.

    The sidecar may hold a question about the call that nobody will be asked, or a request it would still pass on. Cancelling a call that isn't paused, or has ended, changes nothing at the sidecar. Nothing is sent to a sidecar that asks no person through the eval, which pauses no call.

    Returns:
        What the sidecar then said of the call with `request_result`, or None if it was sent nothing or didn't say.
    """
    if received.request_id is None or not getattr(received.sidecar, "review", False):
        return None
    return await _cancel(received, received.request_id)


async def cancel_paused_calls(sample_uuid: str) -> None:
    """Tell the sidecars to cancel the calls a sample leaves paused when it ends.

    A call is left paused when nothing finished or cancelled it, for example
    when the sample was cancelled while Inspect waited to retry the call.
    """
    for request_id, received in _paused_calls.pop(sample_uuid, {}).items():
        await _cancel(received, request_id)


async def _cancel(received: ReceivedCall, request_id: str) -> Answer | None:
    # Inspect calls `cancel_paused_request`, then calls `request_result` once,
    # so that the record of a question the cancellation closed goes into the
    # eval's log. Leaving the sidecar to close the call when the sample ends
    # would be too late, because the sample's log is written first. Both calls
    # share one `CANCEL_TIMEOUT`, so they don't hold up the sample for long.
    sidecar = received.sidecar
    with anyio.CancelScope(shield=True), anyio.move_on_after(CANCEL_TIMEOUT):
        try:
            await sidecar.eval_call("cancel_paused_request", {"id": request_id})
            answer = await ask_request_result(received, request_id, wait=0)
            if answer.result.get("records") == "held":
                log_reviews(received, answer.result)
            return answer
        except Exception as ex:
            logger.debug(
                f"The sentinel sidecar at {sidecar.origin} couldn't be told a call was given up: {ex}"
            )
    return None
