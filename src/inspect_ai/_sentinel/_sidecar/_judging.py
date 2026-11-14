"""What a sidecar's judging of an agent call cost: the time the call waited on it, and the usage of the models its sentinel called."""

from typing import TYPE_CHECKING

from pydantic import BaseModel

from inspect_ai._util.working import ModelAttempts, add_sample_wait

if TYPE_CHECKING:
    from ._received import JudgingUsage, ReceivedCall


def record_judging_usage(used: "list[JudgingUsage] | None") -> None:
    """Record what the provider billed for the sidecar's judge models in the sample's and the eval's usage.

    Each model's usage is recorded under the model and under the role its sentinel asked for, or under `sentinel` where it named the model, as a sentinel's own model calls are in Inspect's process. The calls were made by the sidecar on its own key, so they count toward no token or cost limit.
    """
    from inspect_ai.model._model import record_sidecar_judging_usage

    for entry in used or []:
        record_sidecar_judging_usage(entry.model, entry.role or "sentinel", entry.usage)


def count_judging_as_waiting(
    received: "ReceivedCall | None",
    attempts: ModelAttempts,
    event: BaseModel | None,
) -> float:
    """Count the time a sidecar spent judging an agent call as waiting, not as the agent's working time, as a sentinel's time is in Inspect's process.

    Called once the call is done, whatever it came to, and before its attempts are committed: committed, the attempts' time would be work that a wait can't take back. The proxy held the call's last attempt while the sidecar judged it, so the time is taken from the end of that attempt, and from the call's `ModelEvent`: its working time and its output's `time`, which then hold the model's own time, as for a call judged in process. Nothing is counted where the sidecar wasn't asked, as for a call cancelled in flight, since waiting for its answer here would hold up the cancellation.

    A call a person was asked about is sent more than once, and the proxy held each send while the sidecar judged it, so each send's judging is taken from its end. The time outside its sends, the person's among it, is counted as waiting too. That includes the time Inspect spent asking the sidecar about a call the provider still had after Inspect's own send timed out. Inspect can't tell the provider's part of that time from the sidecar's judging or a person's, so the call's working time can undercount such a provider's work.

    Args:
        received: What is kept of the call, with the sidecar's answer once it was asked.
        attempts: The call's attempts, not yet committed.
        event: The call's `ModelEvent`, if it has one.

    Returns:
        The judging time taken out, in seconds, for the caller to take out of the `output.time` it returns.
    """
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.log._transcript import transcript

    if received is None or attempts.last_attempt is None:
        return 0.0
    start, end = attempts.last_attempt
    if received.reviewed_id is not None and received.sends:
        # A call a person was asked about: only its sends were the model's
        # time. The time before, between and after them went to the
        # provider SDK's own retries, the person and the sidecar's judging
        # with no send open, whatever the call came to. Each send's
        # judging is taken from its end.
        sends = received.sends
        gaps = [
            (start, sends[0].start),
            *((before.end, after.start) for before, after in zip(sends, sends[1:])),
            (sends[-1].end, end),
        ]
        for gap_start, gap_end in gaps:
            if gap_end > gap_start:
                _waited(attempts, gap_start, gap_end)
        judging = 0.0
        for send in sends:
            judged = min(send.judging, send.end - send.start)
            if judged > 0:
                _waited(attempts, send.end - judged, send.end)
                judging += judged
    else:
        looked = received.looked
        if looked is None or not looked.judging_time:
            return 0.0
        # The sidecar adds the time up over a call a person was asked about,
        # which Inspect may retry under the same id: what earlier attempts
        # were credited with was waiting already. Never more than the
        # attempt the proxy held.
        judging = min(
            max(looked.judging_time - received.judging_before_attempt, 0.0),
            end - start,
        )
        _waited(attempts, end - judging, end)
    if not judging:
        return 0.0
    if isinstance(event, ModelEvent):
        if event.working_time is not None:
            event.working_time = max(event.working_time - judging, 0.0)
        # the event holds a copy of the output
        if event.output.time is not None:
            event.output.time = max(event.output.time - judging, 0.0)
        transcript()._event_updated(event)
    return judging


def _waited(attempts: ModelAttempts, start: float, end: float) -> None:
    # the call waited on something other than the model over [start, end]
    add_sample_wait(start, end, completed=False)
    attempts.exclude(start, end)


def time_of_sends() -> float | None:
    """The time the current agent call spent in its sends, if a person was asked about it, or None for any other call, whose time is that of its successful request.

    The call was sent more than once, or once and then answered from what the sidecar decided. The time outside its sends went to the provider SDK's own retries, the person, the sidecar's judging after the answer, and asking the sidecar what became of the call, and `count_judging_as_waiting` counts it as waiting. Where Inspect's own send timed out while the provider still had the request, the provider's work after that send is outside the sends too, so this time can undercount it.
    """
    from ._received import current_receiving

    received = current_receiving()
    if received is None or received.reviewed_id is None or not received.sends:
        return None
    return sum(send.end - send.start for send in received.sends)
