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

    A call that was paused for a person is sent more than once. The proxy held
    each send while the sidecar judged it, so each send's judging time is taken
    from the end of that send. The time outside the sends, which includes the
    person's time, is counted as waiting too. So is the time Inspect spent
    asking the sidecar about a call that the provider still had after Inspect's
    own send timed out. Inspect can't separate the provider's part of that time
    from the sidecar's judging or the person's time, so the call's working time
    can undercount the provider's work in that case.

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
    if received.reviewed_request_id is not None and received.sends:
        # A call that was paused for a person. Only its sends are the model's
        # time. The time before, between and after the sends went to the
        # provider SDK's own retries, to the person, and to judging that the
        # sidecar did between sends. Count those gaps as waiting. Then take
        # each send's judging time from the end of that send.
        sends = received.sends
        gaps = [
            (start, sends[0].start),
            *((before.end, after.start) for before, after in zip(sends, sends[1:])),
            (sends[-1].end, end),
        ]
        for gap_start, gap_end in gaps:
            if gap_end > gap_start:
                _count_as_waiting(attempts, gap_start, gap_end)
        judging = 0.0
        for send in sends:
            judged = min(send.judging, send.end - send.start)
            if judged > 0:
                _count_as_waiting(attempts, send.end - judged, send.end)
                judging += judged
    else:
        looked = received.looked
        if looked is None or not looked.judging_time:
            return 0.0
        # For a paused call, the sidecar's `judging_time` is the total over
        # every try, and Inspect may retry such a call under the same id. So
        # subtract what earlier attempts already counted as waiting. The
        # result is never more than the attempt that the proxy held.
        judging = min(
            max(looked.judging_time - received.judging_before_attempt, 0.0),
            end - start,
        )
        _count_as_waiting(attempts, end - judging, end)
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


def _count_as_waiting(attempts: ModelAttempts, start: float, end: float) -> None:
    # count [start, end] as waiting: the call was not waiting on the model
    add_sample_wait(start, end, completed=False)
    attempts.exclude(start, end)


def time_of_sends() -> float | None:
    """The time the current agent call spent in its sends, if it was paused.

    Returns None for a call that was not paused for a person. Such a call's time
    is that of its successful request.

    A paused call is sent more than once, or sent once and then answered from
    the sidecar's decision. The time outside its sends went to the provider
    SDK's own retries, to the person, to the sidecar's judging after the answer,
    and to Inspect asking the sidecar for the call's state.
    `count_judging_as_waiting` counts that time as waiting. If Inspect's own
    send timed out while the provider still had the request, the provider's
    work after that send is outside the sends too, so this time can undercount
    it.
    """
    from ._received import current_receiving

    received = current_receiving()
    if received is None or received.reviewed_request_id is None or not received.sends:
        return None
    return sum(send.end - send.start for send in received.sends)
