"""Asking a sidecar what it decided of an agent call, after every call that went through it, reply or error alike."""

import time
from typing import Literal, NamedTuple

import anyio

from inspect_ai._util.exception import SampleRefusedError
from inspect_ai.util._limit import (
    suspend_token_limit,
    suspend_turn_limit,
    suspend_working_limit,
)

from .._config import SentinelProxy
from ._endpoint import UNAUTHORIZED, SentinelProxyError, SidecarCallError
from ._received import Judgment, ReceivedCall, parse_judgment

RESULT_WAIT = 30.0
"""How long each `request_result` asks the sidecar to wait while the call is still being judged, in seconds: the longest it waits."""

UNHELD_PAUSE = 0.5
"""How long to wait before asking again when the sidecar answered that it is still judging without holding the answer, in seconds."""

AWAITED_REPLY_ASKS = 10
"""How many times the sidecar is asked again, `UNHELD_PAUSE` apart, about a call a person was asked about whose try came back as an error while the sidecar still awaits the provider's reply. The sidecar says the provider failed only once the error's whole body has arrived, which takes a moment."""


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


async def request_result(received: ReceivedCall, replied: bool) -> Looked:
    """Ask the sidecar what it decided of the call's latest attempt, and keep the answer, waiting while it is still judging.

    The sidecar holds each answer while the call is still being judged, up to `RESULT_WAIT`, and Inspect asks again while it is. While Inspect waits, the sample's token, turn and working limits are paused, as they are while an in-process sentinel runs; its time limit still applies. A state other than judging, including one this version doesn't know, is an answer.

    Args:
        received: What is kept of the call, where the answer is kept too.
        replied: Whether the call came back with a reply. The sidecar never received the reply of a call it is still awaiting the reply of, whether the call came back with a reply or as an error.

    Raises:
        SentinelProxyError: If the sidecar refuses the eval's calls, as when it keeps another token for the eval, so it won't say what it decided.
        ValueError: If the sidecar's judgment isn't one this Inspect can read.
    """
    looked = await _request_result(received, replied)
    received.looked = looked
    received.judgment = looked.judgment
    return looked


async def _request_result(received: ReceivedCall, replied: bool) -> Looked:
    sidecar = received.sidecar
    if sidecar is None or received.request_id is None:
        return Looked("unavailable", "the call's request id is not known")
    # a sidecar that puts no question to the eval is read as before it could
    reviews = bool(getattr(sidecar, "review", False)) and not replied
    awaited = 0
    with suspend_token_limit(), suspend_turn_limit(), suspend_working_limit():
        while True:
            asked = time.monotonic()
            try:
                result = await sidecar.eval_call(
                    "request_result",
                    {"id": received.request_id, "wait": RESULT_WAIT},
                )
            except SidecarCallError as ex:
                if ex.code == UNAUTHORIZED:
                    raise SentinelProxyError(
                        f"The sentinel sidecar at {sidecar.origin} won't take the eval's calls, so it won't say what it decided of them: {ex}"
                    ) from ex
                return Looked("unavailable", str(ex))
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
                _ended(received)
                judgment = result.get("judgment")
                if not isinstance(judgment, dict):
                    return Looked("unavailable", "the sidecar gave no decision")
                # a judgment this Inspect can't read is never taken for none
                return Looked("decided", judgment=parse_judgment(judgment))
            if state == "not_judged":
                _ended(received)
                return Looked("not_judged", str(result.get("reason")))
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
                return Looked(
                    "awaiting_request",
                    str(reason) if reason is not None else None,
                    failure=_failure(result.get("failure")),
                )
            # the proxy hands a reply to the sidecar before passing it on, and
            # the sidecar is judging it from then: a call that came back with
            # a reply the sidecar still awaits got past the sidecar
            if state == "awaiting_reply":
                if (
                    reviews
                    and received.reviewed_id is not None
                    and awaited < AWAITED_REPLY_ASKS
                ):
                    # A call a person was asked about, whose try came back as
                    # an error while the provider's answer to a try the
                    # sidecar sent on is still passing: the body of its
                    # error, which the sidecar tells of only once it is
                    # whole. It is asked again shortly, a bounded number of
                    # times.
                    awaited += 1
                    await anyio.sleep(UNHELD_PAUSE)
                    continue
                return Looked(
                    "unavailable",
                    "the reply was passed on without the sidecar"
                    if replied
                    else "the sidecar never saw a reply",
                )
            # waiting has no deadline of its own, as for a sentinel inside
            # Inspect; the sidecar's time limit bounds its judging, and it
            # holds each answer while it judges
            if state != "judging":
                return Looked("unavailable", f"the sidecar's state is {state!r}")
            # a sidecar that answered at once didn't hold the answer, and
            # isn't asked again at once
            if time.monotonic() - asked < UNHELD_PAUSE:
                await anyio.sleep(UNHELD_PAUSE)


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
