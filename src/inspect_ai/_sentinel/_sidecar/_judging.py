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

    Args:
        received: What is kept of the call, with the sidecar's answer once it was asked.
        attempts: The call's attempts, not yet committed.
        event: The call's `ModelEvent`, if it has one.

    Returns:
        The judging time taken out, in seconds, for the caller to take out of the `output.time` it returns.
    """
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.log._transcript import transcript

    looked = received.looked if received is not None else None
    if looked is None or not looked.judging_time or attempts.last_attempt is None:
        return 0.0
    start, end = attempts.last_attempt
    # never more than the attempt the proxy held
    judging = min(looked.judging_time, end - start)
    add_sample_wait(end - judging, end, completed=False)
    attempts.exclude(end - judging, end)
    if isinstance(event, ModelEvent):
        if event.working_time is not None:
            event.working_time = max(event.working_time - judging, 0.0)
        # the event holds a copy of the output
        if event.output.time is not None:
            event.output.time = max(event.output.time - judging, 0.0)
        transcript()._event_updated(event)
    return judging
