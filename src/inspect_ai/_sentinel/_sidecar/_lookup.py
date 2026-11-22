"""Asking a sidecar what it decided of an agent call, after every call that went through it, reply or error alike."""

import math
import time
from typing import Any, Literal, NamedTuple

import anyio

from inspect_ai._util.exception import SampleRefusedError
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.util._limit import suspend_limits

from .._config import SentinelProxy
from ._endpoint import UNAUTHORIZED, SentinelProxyError, SidecarCallError
from ._judging import record_judging_usage
from ._received import (
    JudgingUsage,
    Judgment,
    ReceivedCall,
    parse_judging_usage,
    parse_judgment,
    record_judging_time,
    timeout_left,
)

RESULT_WAIT = 30.0
"""How long each `request_result` asks the sidecar to wait while the call is still being judged, in seconds: the longest it waits."""

UNHELD_PAUSE = 0.5
"""How long to wait before asking again when the sidecar answered that it is still judging without holding the answer, in seconds."""

AWAITED_REPLY_PAUSE = 0.5
"""The first wait before Inspect asks the sidecar again about a paused call, in seconds.

It applies while the provider still has a request that the sidecar passed on,
which is the state `awaiting_reply`. Each later wait is twice the one before, up
to `AWAITED_REPLY_PAUSE_MAX`.
"""

AWAITED_REPLY_PAUSE_MAX = 5.0
"""The longest of those waits, in seconds."""

LOOKUP_RETRIES = 3
"""How many times in a row Inspect repeats a `request_result` call that got no answer.

It applies to a call that a person was, or may have been, asked about. After
that many, Inspect treats the call's judgment as unavailable.
"""

LOOKUP_RETRY_PAUSE = 0.5
"""The wait before the first of those repeats, in seconds.

Each later wait is twice the one before.
"""


class SidecarNotJudgedError(RuntimeError):
    """An agent call came back as an error, and the sidecar says it couldn't judge it."""


SAMPLE_FAILURES: tuple[type[Exception], ...] = (
    SampleRefusedError,
    SidecarNotJudgedError,
    SentinelProxyError,
)
"""The errors a call through a sidecar raises to fail its sample, which a sandbox-bridged agent must not be handed as a provider's error to retry."""


class ProviderFailure(NamedTuple):
    """A failed provider exchange, as the sidecar reports it for a paused call."""

    try_number: int
    """The number of the failed try, which the sidecar had passed on to the provider.

    Inspect uses it to tell a failure it has already handled from a new one.
    """
    status: int | None
    """The status of the provider's error, or None for a reply that was cut off."""


class Answer(NamedTuple):
    """What a sidecar answered `request_result`, with the run of the sidecar that gave the answer."""

    result: dict[str, Any]
    restarts_found: int
    """The sidecar's `restarts_found` when the lookup began.

    A sidecar's running totals for a request start again when it restarts, and
    a call can carry on under its id through a restart. So a total belongs to
    the restart count it was asked under, taken as the lookup begins: a
    restart found while the answer is on its way doesn't claim it, and neither
    does a later lookup.
    """


class Looked(NamedTuple):
    """What `request_result` said of the call's latest attempt."""

    state: Literal["decided", "not_judged", "unavailable", "awaiting_resend"]
    """The call's state.

    `awaiting_resend` is for a paused call: the provider still has to be called,
    and the sidecar passes the request on only when Inspect resends it.
    """
    reason: str | None = None
    """Why the call wasn't judged, or why the judgment is unavailable."""
    judgment: Judgment | None = None
    """What the sidecar decided, once decided."""
    records: str | None = None
    """What the sidecar said of its records of the call, when it said."""
    failure: ProviderFailure | None = None
    """The provider's last failed exchange for the call.

    Set with `awaiting_resend`, when the call is in that state because the
    exchange failed.
    """
    judging_time: float | None = None
    """How long the sidecar spent judging the call's latest attempt, in seconds, while the call waited on the proxy.

    For a paused call, it is the total over every try of the call.
    """
    judging_usage: list[JudgingUsage] | None = None
    """What the provider billed for the models the sidecar's sentinel called while judging every attempt at the call."""
    restarts_found: int = 0
    """The sidecar's `restarts_found` when the lookup that gave the judging time and usage began, as in `Answer`."""


async def request_result(received: ReceivedCall, replied: bool) -> Looked:
    """Ask the sidecar what it decided of the call's latest attempt, and keep the answer, waiting while it is still judging.

    The sidecar holds each answer while the call is still being judged, up to `RESULT_WAIT`, and Inspect asks again while it is. While Inspect waits, the sample's cost, token, turn and working limits are paused, as they are while an in-process sentinel runs; its time limit still applies. A state other than judging, including one this version doesn't know, is an answer.

    The usage of the models the sidecar's sentinel called is recorded in the sample's and the eval's usage: the latest attempt's, which the sidecar adds up over the provider SDK's own retries, and that of each earlier attempt Inspect retried without asking about it, which is asked for without waiting.

    Args:
        received: What is kept of the call, where the answer is kept too.
        replied: Whether the call came back with a reply. The sidecar never received the reply of a call it is still awaiting the reply of, whether the call came back with a reply or as an error.

    Raises:
        SentinelProxyError: If the sidecar refuses the eval's calls, as when it keeps another token for the eval, so it won't say what it decided.
        ValueError: If the sidecar's judgment or judging usage isn't one this Inspect can read.
    """
    looked = await _request_result(received, replied)
    # before anything is kept, so that an earlier attempt's usage that can't
    # be read raises again when the call is asked about again, as a refusal
    # handler does when nothing was kept
    await record_unasked_usage(received)
    received.looked = looked
    received.judgment = looked.judgment
    record_judging_time(received, looked.judging_time, looked.restarts_found)
    record_judging_usage(
        _not_yet_recorded(received, looked.judging_usage, looked.restarts_found)
    )
    return looked


async def ask_request_result(
    received: ReceivedCall, request_id: str, wait: float | None = None
) -> Answer:
    """Ask the call's sidecar what it holds of a request, with `request_result`, noting which run of the sidecar the answer's running totals belong to.

    Every `request_result` goes through here. The sidecar's restart count is taken as the lookup begins, and returned with the answer.

    Args:
        received: What is kept of the call.
        request_id: The request's `x-irid`.
        wait: How long the sidecar holds the answer while it is still judging, in seconds, or None for its default.

    Raises:
        SidecarCallError: If the call failed, or was answered with an error.
    """
    access = getattr(received.sidecar, "access", None)
    restarts_found: int = access.restarts_found if access is not None else 0
    params: dict[str, Any] = {"id": request_id}
    if wait is not None:
        params["wait"] = wait
    result: dict[str, Any] = await received.sidecar.eval_call("request_result", params)
    return Answer(result, restarts_found)


def settle_usage(
    received: ReceivedCall,
    request_id: str,
    answer: Answer | None,
    unanswered: str = "the sidecar didn't answer",
) -> None:
    """Settle what judging a request billed, for a request Inspect has given up on: record what the sidecar says of it, and note what can't be known.

    One rule, however the request was given up, and whether or not Inspect asked about it before:

    - The sidecar reports a total for the id, so an answer adds only what it has over what Inspect recorded for the id before, from the same run of the sidecar. A restarted sidecar's total is counted in full.
    - An answer given while the sidecar is still judging is noted as incomplete: what was billed so far is recorded, and the rest may never be.
    - Where no total can be read, what was recorded before is kept. It is noted as incomplete, as the request may have been judged again since. A request nothing was recorded for is noted as unavailable, so its usage reads as unknown rather than none.

    Args:
        received: What is kept of the call, with the usage recorded for each of its request ids.
        request_id: The request's `x-irid`.
        answer: What the sidecar answered `request_result` for the id, or None if it didn't.
        unanswered: Why there is no answer, for the note.
    """
    if answer is None:
        reason = unanswered
    elif answer.result.get("records") != "held":
        reason = f"the sidecar's records are {answer.result.get('records')}"
    else:
        try:
            used = parse_judging_usage(answer.result.get("judging_usage")) or None
        except ValueError:
            reason = "the sidecar's judging usage can't be read"
        else:
            record_judging_usage(
                _not_yet_recorded(received, used, answer.restarts_found, request_id)
            )
            if answer.result.get("state") == "judging":
                note_usage_incomplete(request_id, STILL_JUDGING)
            return
    if any(recorded == request_id for _, recorded in received.usage_recorded):
        note_usage_incomplete(request_id, reason)
    else:
        note_usage_unavailable(request_id, reason)


async def fetch_usage(received: ReceivedCall, request_id: str) -> Answer | None:
    """Ask the sidecar once, without waiting, what it holds of a request, for what judging it billed, or None if the sidecar doesn't answer."""
    sidecar = received.sidecar
    if sidecar is None:
        return None
    with suspend_limits():
        try:
            return await ask_request_result(received, request_id, wait=0)
        except SidecarCallError:
            return None


STILL_JUDGING = "the sidecar was still judging the attempt"
"""Why usage is incomplete for a request Inspect gave up on while the sidecar judged it."""


def note_usage_incomplete(request_id: str, reason: str) -> None:
    """Note in the transcript that what was recorded of a request's judging usage may not be all of it."""
    from inspect_ai.log._transcript import transcript

    transcript().info(
        {
            "request": request_id,
            "judging_usage": "incomplete",
            "reason": reason,
        },
        source="sentinel sidecar",
    )


def note_usage_unavailable(request_id: str, reason: str) -> None:
    """Note in the transcript that what judging a request billed couldn't be had, so it reads as unknown rather than none."""
    from inspect_ai.log._transcript import transcript

    transcript().info(
        {
            "request": request_id,
            "judging_usage": "unavailable",
            "reason": reason,
        },
        source="sentinel sidecar",
    )


def _not_yet_recorded(
    received: ReceivedCall,
    used: list[JudgingUsage] | None,
    restarts_found: int,
    request_id: str | None = None,
) -> list[JudgingUsage] | None:
    # The sidecar reports usage for a request id as a total over every attempt
    # under that id. Inspect asks about a paused call more than once under one
    # id, so it records only the usage added since it last asked. A sidecar's
    # totals start again when it restarts, so each restart count has a series
    # of its own.
    request_id = request_id or received.request_id
    if not used or request_id is None:
        return used
    recorded = received.usage_recorded.setdefault((restarts_found, request_id), {})
    new: list[JudgingUsage] = []
    for entry in used:
        key = (entry.role, entry.model)
        before = recorded.get(key)
        recorded[key] = entry.usage
        if before is None:
            new.append(entry)
            continue
        since = _usage_since(entry.usage, before)
        if since is not None:
            new.append(entry.model_copy(update={"usage": since}))
    return new


def _usage_since(now: ModelUsage, before: ModelUsage) -> ModelUsage | None:
    # the usage added since `before`, field by field, or None if nothing was
    # added
    added: dict[str, Any] = {}
    for name in ModelUsage.model_fields:
        value, earlier = getattr(now, name), getattr(before, name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            difference = value - (earlier or 0)
            added[name] = max(difference, 0)
        else:
            added[name] = value
    since = ModelUsage(**added)
    counted = [
        getattr(since, name)
        for name in ModelUsage.model_fields
        if isinstance(getattr(since, name), int | float)
    ]
    return since if any(counted) else None


async def record_unasked_usage(received: ReceivedCall) -> None:
    """Record the judging usage of each earlier attempt at the call that Inspect retried without asking the sidecar about it.

    Each was sent under its own request id, and the sidecar may have judged its request with its own models before the provider failed. Only the usage is asked for, without waiting: the attempt's outcome was the error Inspect retried. An answer that can't be had is noted in the transcript, as the usage is then unknown rather than none, and so is an attempt the sidecar is still judging, whose usage so far is recorded and may be incomplete. Each id is dropped once its usage is recorded or noted, and not before, so an answer that can't be read raises again when asked again, and nothing is recorded twice.

    Raises:
        ValueError: If an attempt's judging usage isn't one this Inspect can read.
    """
    sidecar = received.sidecar
    if sidecar is None:
        received.unasked.clear()
        return
    if not received.unasked:
        return
    with suspend_limits():
        while received.unasked:
            request_id = received.unasked[0]
            try:
                result = (await ask_request_result(received, request_id)).result
            except SidecarCallError as ex:
                reason = str(ex)
            else:
                records = result.get("records")
                if records == "held":
                    record_judging_usage(
                        parse_judging_usage(result.get("judging_usage")) or None
                    )
                    received.unasked.pop(0)
                    # the sidecar is still judging an attempt Inspect gave up
                    # on, and isn't waited for: what was billed so far is
                    # recorded, and the rest may never be
                    if result.get("state") == "judging":
                        note_usage_incomplete(request_id, STILL_JUDGING)
                    continue
                reason = f"the sidecar's records are {records}"
            note_usage_unavailable(request_id, reason)
            received.unasked.pop(0)


async def _request_result(received: ReceivedCall, replied: bool) -> Looked:
    sidecar = received.sidecar
    if sidecar is None or received.request_id is None:
        return Looked("unavailable", "the call's request id is not known")
    # Whether to handle the states that human review added. Inspect doesn't
    # for a sidecar that asks no person through the eval, or for a call that
    # returned a reply.
    handles_reviews = bool(getattr(sidecar, "review", False)) and not replied
    awaited_pause = AWAITED_REPLY_PAUSE
    # Whether the sidecar's last answer was `awaiting_reply` for a paused
    # call, which means the provider still has the request. While this is
    # set, the call's `timeout` limits the waiting. Inspect starts no lookup
    # after the timeout has passed, and abandons a lookup that is in progress
    # when it passes. An answer that arrives before then is used.
    provider_has_request = False
    # Whether to repeat a lookup that got no answer. Inspect repeats it when
    # a person was, or may have been, asked about the call, because the
    # person's decision is held only at the sidecar. Inspect doesn't repeat
    # any other lookup.
    repeats_lost_lookup = handles_reviews or received.reviewed_request_id is not None
    lost_lookups = 0
    answer = Answer({}, 0)
    with suspend_limits():
        while True:
            left = timeout_left(received) if provider_has_request else None
            if left is not None and left <= 0:
                return await _cancel_timed_out_call(received, answer)
            asked = time.monotonic()
            with anyio.move_on_after(left) as within:
                try:
                    answer = await ask_request_result(
                        received,
                        received.request_id,
                        # The sidecar holds its answer only while it is
                        # judging. While the provider has the request,
                        # Inspect asks with no wait. So it learns at once
                        # when the judging has begun, which means the
                        # provider has replied.
                        wait=0 if provider_has_request else RESULT_WAIT,
                    )
                except SidecarCallError as ex:
                    if ex.code == UNAUTHORIZED:
                        raise SentinelProxyError(
                            f"The sentinel sidecar at {sidecar.origin} won't take the eval's calls, so it won't say what it decided of them: {ex}"
                        ) from ex
                    if (
                        ex.code is None
                        and repeats_lost_lookup
                        and lost_lookups < LOOKUP_RETRIES
                    ):
                        # The lookup didn't reach the sidecar, or its answer
                        # was lost, for example because the proxy failed for
                        # a moment. Repeating it is safe: it asks the person
                        # nothing and sends the provider nothing. Inspect
                        # repeats it at most `LOOKUP_RETRIES` times in a
                        # row, and never repeats a lookup that the sidecar
                        # answered with an error.
                        lost_lookups += 1
                        await anyio.sleep(LOOKUP_RETRY_PAUSE * 2 ** (lost_lookups - 1))
                        continue
                    return Looked("unavailable", str(ex))
            if within.cancelled_caught:
                return await _cancel_timed_out_call(received, answer)
            lost_lookups = 0
            result = answer.result
            records = result.get("records")
            if records != "held":
                from ._review import warn_reviews_unavailable

                warn_reviews_unavailable(received, str(records))
                return Looked(
                    "unavailable",
                    f"the sidecar's records are {records}",
                    records=str(records),
                )
            # Log how each question about the call was resolved, and warn if
            # an answer that a person gave here was not used.
            from ._review import log_reviews

            log_reviews(received, result)
            _record_totals_so_far(received, answer)
            state = result.get("state")
            if state == "decided":
                listed = result.get("reviews")
                if handles_reviews and isinstance(listed, list) and listed:
                    # A person was asked about the call, but every question
                    # had closed before Inspect asked. The sidecar still
                    # treats the call as paused and holds any reply for it.
                    # So Inspect records the id, under which it fetches that
                    # reply.
                    received.reviewed_request_id = received.request_id
                _mark_ended(received)
                judgment = result.get("judgment")
                if not isinstance(judgment, dict):
                    return _judging(
                        Looked("unavailable", "the sidecar gave no decision"), answer
                    )
                # a judgment this Inspect can't read is never taken for none
                return _judging(
                    Looked("decided", judgment=parse_judgment(judgment)), answer
                )
            if state == "not_judged":
                _mark_ended(received)
                return _judging(Looked("not_judged", str(result.get("reason"))), answer)
            if handles_reviews and state == "awaiting_review":
                # A sentinel asked a person about the call, and the sidecar
                # has paused it. No connection waits for the person. Inspect
                # shows the person the question, sends their answer, and then
                # asks the sidecar for the call's state again.
                from ._review import ask_person, mark_paused

                # If the provider had the request, a question means that
                # the provider has replied. Inspect may never have seen the
                # `judging` state in between, because it asks with no wait
                # while the provider has the request. So the flag is
                # cleared, and the call's `timeout` no longer limits the
                # wait.
                provider_has_request = False
                mark_paused(received)
                await ask_person(received)
                continue
            if (
                replied
                and state == "awaiting_resend"
                and received.reviewed_request_id is not None
            ):
                failure = _parse_failure(result.get("failure"))
                if failure is not None and failure.status is not None:
                    # The provider answered the request that the sidecar
                    # passed on with an error, and the proxy returned that
                    # error to Inspect. The provider's client code read it
                    # as a reply, as Anthropic's does for a prompt that is
                    # too long. So Inspect has a reply, while the sidecar
                    # waits for a resend. Inspect uses the reply as the
                    # call's result and sends nothing more, so it cancels
                    # the paused call at the sidecar. The call is reported
                    # as not judged, like any call whose provider answered
                    # with an error.
                    from ._review import cancel_paused_call

                    received.handled_failures.add(failure.try_number)
                    await cancel_paused_call(received)
                    return _judging(Looked("not_judged", "provider_error"), answer)
            if handles_reviews and state == "awaiting_resend":
                from ._review import mark_paused

                mark_paused(received)
                reason = result.get("reason")
                return _judging(
                    Looked(
                        "awaiting_resend",
                        str(reason) if reason is not None else None,
                        failure=_parse_failure(result.get("failure")),
                    ),
                    answer,
                )
            # the proxy hands a reply to the sidecar before passing it on, and
            # the sidecar is judging it from then: a call that came back with
            # a reply the sidecar still awaits got past the sidecar
            if state == "awaiting_reply":
                if handles_reviews and received.reviewed_request_id is not None:
                    # A paused call whose request returned an error to
                    # Inspect, while the provider still has a request that
                    # the sidecar passed on, or its reply is still on the
                    # way through the proxy. Inspect's own request may have
                    # timed out, which doesn't mean the provider stopped.
                    # The sidecar keeps the call, and will hold the reply
                    # when it arrives. So Inspect waits for that reply: it
                    # asks the sidecar again after a pause, and sends the
                    # provider nothing more. The call's `timeout` limits
                    # the wait, as it limits the call's retries. The
                    # sample's time limit and its cancellation end the wait
                    # too.
                    provider_has_request = True
                    left = timeout_left(received)
                    if left is not None and left <= 0:
                        return await _cancel_timed_out_call(received, answer)
                    await anyio.sleep(
                        awaited_pause if left is None else min(awaited_pause, left)
                    )
                    awaited_pause = min(awaited_pause * 2, AWAITED_REPLY_PAUSE_MAX)
                    continue
                return _judging(
                    Looked(
                        "unavailable",
                        "the reply was passed on without the sidecar"
                        if replied
                        else "the sidecar never saw a reply",
                    ),
                    answer,
                )
            # waiting has no deadline of its own, as for a sentinel inside
            # Inspect; the sidecar's time limit bounds its judging, and it
            # holds each answer while it judges
            if state != "judging":
                return _judging(
                    Looked("unavailable", f"the sidecar's state is {state!r}"), answer
                )
            # The state is `judging`, so the provider has replied. The
            # flag is cleared, because a reply is judged with no deadline.
            provider_has_request = False
            # a sidecar that answered at once didn't hold the answer, and
            # isn't asked again at once
            if time.monotonic() - asked < UNHELD_PAUSE:
                await anyio.sleep(UNHELD_PAUSE)


def _record_totals_so_far(received: ReceivedCall, answer: Answer) -> None:
    # The running totals of an answer, recorded as it arrives, under the run
    # of the sidecar that gave it. Inspect may go on asking from here, as
    # while a person decides, and the next answer may come from a restarted
    # sidecar, whose totals start again: what this run billed is then kept.
    # Recording a total again adds nothing. Totals that can't be read are
    # left for the answer Inspect acts on, which raises.
    try:
        totals = _judging(Looked("unavailable"), answer)
    except ValueError:
        return
    record_judging_time(received, totals.judging_time, totals.restarts_found)
    record_judging_usage(
        _not_yet_recorded(received, totals.judging_usage, totals.restarts_found)
    )


async def _cancel_timed_out_call(received: ReceivedCall, answer: Answer) -> Looked:
    # The call's `timeout` passed while the provider still had the request of
    # a paused call. Inspect cancels the call at the sidecar, so that the
    # sidecar keeps nothing for it. `answer` is the sidecar's last answer
    # about the call.
    from ._review import cancel_paused_call

    await cancel_paused_call(received)
    return _judging(
        Looked(
            "unavailable",
            "the call's timeout passed while the provider still had its request",
        ),
        answer,
    )


def _mark_ended(received: ReceivedCall) -> None:
    # the sidecar says the call has ended, so it is no longer paused there
    if received.paused:
        from ._review import mark_ended

        mark_ended(received)


def _parse_failure(failure: object) -> ProviderFailure | None:
    if not isinstance(failure, dict):
        return None
    number = failure.get("try_number")
    if not isinstance(number, int):
        return None
    reply = failure.get("reply")
    status = reply.get("status") if isinstance(reply, dict) else None
    return ProviderFailure(number, status if isinstance(status, int) else None)


def _judging(looked: Looked, answer: Answer) -> Looked:
    # What the sidecar's judging took, on any answer about records it holds:
    # a call it didn't finish judging was still waited on and billed. A time
    # longer than the call is kept as sent: it is capped at the call's length
    # where it is counted, as the two processes' clocks can differ.
    result = answer.result
    judging_time = result.get("judging_time")
    if judging_time is not None and (
        isinstance(judging_time, bool)
        or not isinstance(judging_time, int | float)
        or not math.isfinite(judging_time)
        or judging_time < 0
    ):
        raise ValueError(f"The sidecar's judging time can't be read: {judging_time!r}")
    return looked._replace(
        judging_time=float(judging_time) if judging_time is not None else None,
        judging_usage=parse_judging_usage(result.get("judging_usage")) or None,
        restarts_found=answer.restarts_found,
    )


def unjudged_reply(looked: Looked, mode: SentinelProxy, request_id: str | None) -> None:
    """Record why a reply the agent is handed wasn't judged, or that its judgment is unavailable, as the reply is used as it would be with no sidecar.

    Raises:
        SidecarNotJudgedError: If the judgment is unavailable and the task requires a sidecar.
    """
    from inspect_ai.log._transcript import transcript

    if looked.state == "unavailable" and mode == "required":
        raise SidecarNotJudgedError(
            f"The sentinel sidecar's judgment of the call {request_id} is unavailable ({looked.reason}), and a sidecar is required."
        )
    transcript().info(
        {
            "request": request_id,
            "judgment": "not judged" if looked.state == "not_judged" else "unavailable",
            "reason": looked.reason,
        },
        source="sentinel sidecar",
    )


def lost_sample(looked: Looked | None, registered_beforehand: bool) -> bool:
    """Whether the sidecar says it can't place a sample it had accepted: the eval registered the task, so the sidecar has lost the sample since, as on a restart."""
    return (
        looked is not None
        and looked.state == "not_judged"
        and looked.reason == "unregistered"
        and not registered_beforehand
    )


def unknown_to_required(looked: Looked | None, mode: SentinelProxy) -> bool:
    """Whether a sidecar the task requires keeps no record of a call that came back as an error, as when it refused the call for an eval whose token it lost in a restart: it can't say what it holds for the attempt."""
    return (
        mode == "required"
        and looked is not None
        and looked.state == "unavailable"
        and looked.records == "unknown"
    )


def unjudged_error(
    looked: Looked | None,
    error: BaseException,
    registered_beforehand: bool = False,
    mode: SentinelProxy = "auto",
) -> None:
    """Fail the sample for an agent call that came back as an error the sidecar says it couldn't judge, or whose judgment is unavailable when the task requires a sidecar.

    A sample the sidecar can't place was never accepted when its task is one the sidecar's admin registered beforehand, whose samples the sidecar takes only as its tasks folder holds them: a retry would be refused the same way. A task the eval registered was accepted when the sample's registration completed, so the sidecar has lost it since, as on a restart, and a retry registers it again.

    A sidecar that lost the eval's token in a restart refuses the call without keeping it, so its judgment is unavailable, not `unregistered`. With `auto`, the call's error stands, as it would with no sidecar: a sandbox-bridged agent is handed it, and may go on once the eval registers again, with monitor state that began after the restart.

    Args:
        looked: What `request_result` said of the call.
        error: The call's error.
        registered_beforehand: Whether the sidecar's admin registered the task beforehand.
        mode: Whether the task requires a sidecar.

    Raises:
        SampleRefusedError: If the sidecar never accepted the sample, so it can't run there.
        SidecarNotJudgedError: If the sidecar couldn't judge the call for another reason, including a sample it has lost, which Inspect retries as it does other errors; or if the call's judgment is unavailable and the task requires a sidecar.
    """
    if looked is not None and looked.state == "unavailable" and mode == "required":
        raise SidecarNotJudgedError(
            f"The sentinel sidecar's judgment of the call is unavailable ({looked.reason}), and a sidecar is required: {error}"
        ) from error
    if looked is None or looked.state != "not_judged":
        return
    if looked.reason == "unregistered":
        if registered_beforehand:
            raise SampleRefusedError(
                f"The sentinel sidecar refused the sample, which its tasks folder doesn't hold: {error}"
            ) from error
        raise SidecarNotJudgedError(
            f"The sentinel sidecar no longer holds the sample's registration, as after a restart, so it couldn't judge the call; a retry registers the sample again: {error}"
        ) from error
    raise SidecarNotJudgedError(
        f"The sentinel sidecar couldn't judge the call ({looked.reason}): {error}"
    ) from error
