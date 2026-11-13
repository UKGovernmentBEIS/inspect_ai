"""Asking a sidecar what it decided of an agent call, after every call that went through it, reply or error alike."""

import math
import time
from typing import Any, Literal, NamedTuple

import anyio

from inspect_ai._util.exception import SampleRefusedError
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.util._limit import (
    suspend_token_limit,
    suspend_turn_limit,
    suspend_working_limit,
)

from .._config import SentinelProxy
from ._endpoint import UNAUTHORIZED, SentinelProxyError, SidecarCallError
from ._judging import record_judging_usage
from ._received import (
    JudgingUsage,
    Judgment,
    ReceivedCall,
    note_judging_time,
    parse_judging_usage,
    parse_judgment,
    timeout_left,
)

RESULT_WAIT = 30.0
"""How long each `request_result` asks the sidecar to wait while the call is still being judged, in seconds: the longest it waits."""

UNHELD_PAUSE = 0.5
"""How long to wait before asking again when the sidecar answered that it is still judging without holding the answer, in seconds."""

AWAITED_REPLY_PAUSE = 0.5
"""How long to wait before first asking the sidecar again about a call a person was asked about, while a try the sidecar sent on is still with the provider, in seconds. Each later wait is twice the one before, up to `AWAITED_REPLY_PAUSE_MAX`."""

AWAITED_REPLY_PAUSE_MAX = 5.0
"""The longest wait between two such asks, in seconds."""


class SidecarNotJudgedError(RuntimeError):
    """An agent call came back as an error, and the sidecar says it couldn't judge it."""


SAMPLE_FAILURES: tuple[type[Exception], ...] = (
    SampleRefusedError,
    SidecarNotJudgedError,
    SentinelProxyError,
)
"""The errors a call through a sidecar raises to fail its sample, which a sandbox-bridged agent must not be handed as a provider's error to retry."""


class Failure(NamedTuple):
    """A failed exchange with the provider, as the sidecar tells it of a call a person was asked about."""

    try_number: int
    """Which try of the call was sent on to the provider and failed, which tells a failure Inspect has acted on from a new one."""
    status: int | None
    """The status of the provider's error, or None for a reply that was cut off."""


class Looked(NamedTuple):
    """What `request_result` said of the call's latest attempt."""

    state: Literal["decided", "not_judged", "unavailable", "awaiting_request"]
    """`awaiting_request` is of a call a person was asked about, which the sidecar keeps as one model call: it waits for the same request, to send it on to the provider."""
    reason: str | None = None
    """Why the call wasn't judged, or why the judgment is unavailable."""
    judgment: Judgment | None = None
    """What the sidecar decided, once decided."""
    records: str | None = None
    """What the sidecar said of its records of the call, when it said."""
    failure: Failure | None = None
    """The provider's last failed exchange, with `awaiting_request`, where the sidecar waits for the request because that exchange failed."""
    judging_time: float | None = None
    """How long the sidecar spent judging the call's latest attempt, in seconds, while the call waited on the proxy. For a call a person was asked about, it is added up over every try of the call."""
    judging_usage: list[JudgingUsage] | None = None
    """What the provider billed for the models the sidecar's sentinel called while judging every attempt at the call."""


async def request_result(received: ReceivedCall, replied: bool) -> Looked:
    """Ask the sidecar what it decided of the call's latest attempt, and keep the answer, waiting while it is still judging.

    The sidecar holds each answer while the call is still being judged, up to `RESULT_WAIT`, and Inspect asks again while it is. While Inspect waits, the sample's token, turn and working limits are paused, as they are while an in-process sentinel runs; its time limit still applies. A state other than judging, including one this version doesn't know, is an answer.

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
    note_judging_time(received, looked.judging_time)
    record_judging_usage(_not_yet_recorded(received, looked.judging_usage))
    return looked


def _not_yet_recorded(
    received: ReceivedCall, used: list[JudgingUsage] | None
) -> list[JudgingUsage] | None:
    # The usage the sidecar gives for the call's request id is added up over
    # every attempt under it, and a call a person was asked about is asked
    # about more than once under one id. So only what was billed since the
    # last time is recorded.
    if not used or received.request_id is None:
        return used
    recorded = received.usage_recorded.setdefault(received.request_id, {})
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
    # what was added since `before`, field by field, or None for nothing
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
    from inspect_ai.log._transcript import transcript

    sidecar = received.sidecar
    if sidecar is None:
        received.unasked.clear()
        return
    if not received.unasked:
        return
    with suspend_token_limit(), suspend_turn_limit(), suspend_working_limit():
        while received.unasked:
            request_id = received.unasked[0]
            try:
                result = await sidecar.eval_call("request_result", {"id": request_id})
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
                        transcript().info(
                            {
                                "request": request_id,
                                "judging_usage": "incomplete",
                                "reason": "the sidecar was still judging the attempt",
                            },
                            source="sentinel sidecar",
                        )
                    continue
                reason = f"the sidecar's records are {records}"
            transcript().info(
                {
                    "request": request_id,
                    "judging_usage": "unavailable",
                    "reason": reason,
                },
                source="sentinel sidecar",
            )
            received.unasked.pop(0)


async def _request_result(received: ReceivedCall, replied: bool) -> Looked:
    sidecar = received.sidecar
    if sidecar is None or received.request_id is None:
        return Looked("unavailable", "the call's request id is not known")
    # a sidecar that puts no question to the eval is read as before it could
    reviews = bool(getattr(sidecar, "review", False)) and not replied
    awaited_pause = AWAITED_REPLY_PAUSE
    # Whether the sidecar last said the provider still has the request of a
    # call a person was asked about. From then the call's `timeout` bounds
    # the waiting: no lookup begins once it has passed, and one under way
    # when it passes is given up. An answer that comes before then is taken.
    following = False
    result: dict[str, Any] = {}
    with suspend_token_limit(), suspend_turn_limit(), suspend_working_limit():
        while True:
            left = timeout_left(received) if following else None
            if left is not None and left <= 0:
                return await _out_of_time(received, result)
            asked = time.monotonic()
            with anyio.move_on_after(left) as within:
                try:
                    result = await sidecar.eval_call(
                        "request_result",
                        {
                            "id": received.request_id,
                            # the sidecar holds an answer only while it
                            # judges, and a call that is followed is asked
                            # about without waiting, so that judging which
                            # has begun is learned of at once
                            "wait": 0 if following else RESULT_WAIT,
                        },
                    )
                except SidecarCallError as ex:
                    if ex.code == UNAUTHORIZED:
                        raise SentinelProxyError(
                            f"The sentinel sidecar at {sidecar.origin} won't take the eval's calls, so it won't say what it decided of them: {ex}"
                        ) from ex
                    return Looked("unavailable", str(ex))
            if within.cancelled_caught:
                return await _out_of_time(received, result)
            records = result.get("records")
            if records != "held":
                from ._review import reviews_unavailable

                reviews_unavailable(received, str(records))
                return Looked(
                    "unavailable",
                    f"the sidecar's records are {records}",
                    records=str(records),
                )
            # what became of each question asked about the call, for the log
            # and for a person whose answer wasn't used
            from ._review import note_reviews

            note_reviews(received, result)
            state = result.get("state")
            if state == "decided":
                listed = result.get("reviews")
                if reviews and isinstance(listed, list) and listed:
                    # A person was asked about the call, though every
                    # question had closed before Inspect asked: the sidecar
                    # keeps it as one model call all the same, with the reply
                    # it holds for it.
                    received.reviewed_id = received.request_id
                _ended(received)
                judgment = result.get("judgment")
                if not isinstance(judgment, dict):
                    return _judging(
                        Looked("unavailable", "the sidecar gave no decision"), result
                    )
                # a judgment this Inspect can't read is never taken for none
                return _judging(
                    Looked("decided", judgment=parse_judgment(judgment)), result
                )
            if state == "not_judged":
                _ended(received)
                return _judging(Looked("not_judged", str(result.get("reason"))), result)
            if reviews and state == "awaiting_review":
                # A sentinel asked a person about the call. The sidecar keeps
                # the call as one model call from here, and no connection
                # waits: the person is shown the question, and the sidecar is
                # asked again once they have answered.
                from ._review import ask_person, opened

                opened(received)
                await ask_person(received)
                continue
            if reviews and state == "awaiting_request":
                from ._review import opened

                opened(received)
                reason = result.get("reason")
                return _judging(
                    Looked(
                        "awaiting_request",
                        str(reason) if reason is not None else None,
                        failure=_failure(result.get("failure")),
                    ),
                    result,
                )
            # the proxy hands a reply to the sidecar before passing it on, and
            # the sidecar is judging it from then: a call that came back with
            # a reply the sidecar still awaits got past the sidecar
            if state == "awaiting_reply":
                if reviews and received.reviewed_id is not None:
                    # A call a person was asked about, whose try came back as
                    # an error while a try the sidecar sent on is still with
                    # the provider, or the provider's answer to it is still
                    # passing. Inspect's own try may have timed out, which
                    # doesn't say the provider stopped: the sidecar holds the
                    # call, and the reply once it comes. So the call is
                    # followed until it comes to something, and nothing more
                    # is sent to the provider meanwhile. The call's `timeout`
                    # bounds the wait, as it bounds the call's retries, and
                    # the sample's time limit and its cancellation end it too.
                    following = True
                    left = timeout_left(received)
                    if left is not None and left <= 0:
                        return await _out_of_time(received, result)
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
                    result,
                )
            # waiting has no deadline of its own, as for a sentinel inside
            # Inspect; the sidecar's time limit bounds its judging, and it
            # holds each answer while it judges
            if state != "judging":
                return _judging(
                    Looked("unavailable", f"the sidecar's state is {state!r}"), result
                )
            # the provider has answered, and its reply is judged with no
            # deadline, as any reply is
            following = False
            # a sidecar that answered at once didn't hold the answer, and
            # isn't asked again at once
            if time.monotonic() - asked < UNHELD_PAUSE:
                await anyio.sleep(UNHELD_PAUSE)


async def _out_of_time(received: ReceivedCall, result: dict[str, Any]) -> Looked:
    # The call's `timeout` passed while the provider still had the request
    # of a call a person was asked about. The sidecar is told the call is
    # given up, so it holds nothing for it any longer. `result` is the last
    # answer the sidecar gave about the call.
    from ._review import cancel_open_call

    await cancel_open_call(received)
    return _judging(
        Looked(
            "unavailable",
            "the call's timeout passed while the provider still had its request",
        ),
        result,
    )


def _ended(received: ReceivedCall) -> None:
    # a call a person was asked about is held open at the sidecar no longer
    if received.open:
        from ._review import ended

        ended(received)


def _failure(failure: object) -> Failure | None:
    if not isinstance(failure, dict):
        return None
    number = failure.get("try_number")
    if not isinstance(number, int):
        return None
    reply = failure.get("reply")
    status = reply.get("status") if isinstance(reply, dict) else None
    return Failure(number, status if isinstance(status, int) else None)


def _judging(looked: Looked, result: dict[str, Any]) -> Looked:
    # What the sidecar's judging took, on any answer about records it holds:
    # a call it didn't finish judging was still waited on and billed. A time
    # longer than the call is kept as sent: it is capped at the call's length
    # where it is counted, as the two processes' clocks can differ.
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
