"""Asking a sidecar what it decided of an agent call whose reply or refusal came back without the `sentinel` field."""

from typing import Any, Literal, NamedTuple

import anyio

from inspect_ai._util.exception import SampleRefusedError
from inspect_ai.util._limit import (
    suspend_token_limit,
    suspend_turn_limit,
    suspend_working_limit,
)

from .._config import SentinelProxy
from ._endpoint import SidecarCallError
from ._field import ReceivedField

FIRST_WAIT = 0.5
LONGEST_WAIT = 10.0


class SidecarNotJudgedError(RuntimeError):
    """An agent call came back as an error, and the sidecar says it couldn't judge it."""


class Looked(NamedTuple):
    """What `request_result` said of the call's latest attempt."""

    state: Literal["decided", "not_judged", "unavailable"]
    reason: str | None = None
    """Why the call wasn't judged, or why the judgment is unavailable."""
    field: dict[str, Any] | None = None
    """The `sentinel` field the reply or refusal carried, once decided."""


async def request_result(received: ReceivedField, replied: bool) -> Looked:
    """Ask the sidecar what it decided of the call's latest attempt, waiting while it is still judging.

    While Inspect waits, the sample's token, turn and working limits are paused, as they are while an in-process sentinel runs; its time limit still applies.

    Args:
        received: What was collected of the call.
        replied: Whether the call came back with a reply. A call that came back as an error and that the sidecar is still awaiting the reply of never reached it: its error is the provider's.
    """
    sidecar = received.sidecar
    if sidecar is None or received.request_id is None:
        return Looked("unavailable", "the call's request id is not known")
    wait = FIRST_WAIT
    with suspend_token_limit(), suspend_turn_limit(), suspend_working_limit():
        while True:
            try:
                result = await sidecar.call(
                    "request_result", {"id": received.request_id}
                )
            except SidecarCallError as ex:
                return Looked("unavailable", str(ex))
            records = result.get("records")
            if records != "held":
                return Looked("unavailable", f"the sidecar's records are {records}")
            state = result.get("state")
            if state == "decided":
                field = result.get("sentinel")
                if not isinstance(field, dict):
                    return Looked("unavailable", "the sidecar gave no decision")
                return Looked("decided", field=field)
            if state == "not_judged":
                return Looked("not_judged", str(result.get("reason")))
            if state == "awaiting_reply" and not replied:
                return Looked("unavailable", "the sidecar never saw a reply")
            await anyio.sleep(wait)
            wait = min(wait * 2, LONGEST_WAIT)


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


def unjudged_error(looked: Looked | None, error: BaseException) -> None:
    """Fail the sample for an agent call that came back as an error the sidecar says it couldn't judge.

    Raises:
        SampleRefusedError: If the sidecar couldn't place the sample, so it can't run there.
        SidecarNotJudgedError: If the sidecar couldn't judge the call for another reason.
    """
    if looked is None or looked.state != "not_judged":
        return
    if looked.reason == "unregistered":
        raise SampleRefusedError(
            f"The sentinel sidecar refused the sample, which it isn't registered to judge: {error}"
        ) from error
    raise SidecarNotJudgedError(
        f"The sentinel sidecar couldn't judge the call ({looked.reason}): {error}"
    ) from error
