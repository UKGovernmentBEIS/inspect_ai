"""Acting on a sidecar's protocol decisions, as Inspect acts on an in-process sentinel's.

A sidecar judges a whole turn before Inspect is handed it, and Inspect asks what it decided with `request_result`. A call it rejected is put back into the model's turn, with its id and function only, since an eval is never handed a rejected call's arguments, and answered with an approval error when Inspect would run it; a call it changed is held and runs as changed; a `terminate` ends the sample where an in-process sentinel's would, at the model call or before the turn's calls run.
"""

from collections.abc import Callable
from typing import Any, Literal, NamedTuple
from weakref import WeakKeyDictionary

from pydantic import TypeAdapter

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.tool._tool_call import ToolCall

from ._lookup import (
    lost_sample,
    request_result,
    unjudged_error,
    unknown_to_required,
)
from ._received import Judgment, ReceivedCall, WithheldTurn, current_receiving

_ENDED = "A sentinel in the sidecar ended the sample."

_TOOL_CALL = TypeAdapter(ToolCall)


class CallDecision(NamedTuple):
    """What the sidecar decided of one call of the model's turn, for Inspect to act on when it would run the call."""

    action: Literal["reject", "modify", "terminate"]
    message: str | None = None
    """What the model is told of a rejected call, or why a sentinel ended the sample."""
    modified: ToolCall | None = None
    """The call to run in place of the model's."""


# by sample, so a call's decision reaches the tool call, which runs in
# another task than the model call that brought it
_decisions: "WeakKeyDictionary[Any, dict[str, CallDecision]]" = WeakKeyDictionary()


def take_call_decision(call_id: str) -> CallDecision | None:
    """The sidecar's decision of a call the sample's agent is about to run, if it rejected or changed it."""
    from inspect_ai.log._samples import sample_active

    active = sample_active()
    if active is None:
        return None
    decisions = _decisions.get(active)
    return decisions.pop(call_id, None) if decisions is not None else None


async def refused_output(
    model: str, retryable: Callable[[], bool], bridged: Callable[[], bool]
) -> ModelOutput | None:
    """A refusal of the current agent call, as the model output Inspect acts on, or None if the call wasn't refused by a sidecar's decision.

    A rejected turn is the model's turn, whose calls are answered with approval errors, as in process. A turn refused because the sample ended is the model's turn if the sidecar was handed one, else empty. An error Inspect retries, such as a 503, isn't looked up while it is retried: the sidecar is asked with `request_result` only of an error Inspect won't retry.

    Args:
        model: The model's name, for the output.
        retryable: Whether Inspect retries the call's error, as it does an ordinary provider or network failure. Asked only of a call that went through a sidecar, since a provider's `should_retry` can log or raise.
        bridged: Whether the call is a bridged agent's, which runs its own tools.
    """
    # Nothing else is asked of a call that didn't go through a sidecar, or of
    # an attempt that failed before any request of it was sent, which the
    # sidecar never saw.
    received = current_receiving()
    if received is None or not received.sent or retryable():
        return None
    if received.looked is None:
        await request_result(received, replied=False)
    return _refusal(received.judgment, model, bridged())


async def refusal_after_error(
    received: ReceivedCall, model: str, error: BaseException, bridged: bool
) -> ModelOutput | None:
    """A refusal of an agent call that Inspect stopped retrying, as the model output Inspect acts on, or None to let the error stand.

    An error Inspect retries, such as a 503, is not looked up while it is retried; once the retries are spent, the sidecar is asked what it decided.

    An error raised before any request of the attempt was sent stands as it is, and the sidecar is asked nothing: it was never sent the call, so it has no judgment of it to be unavailable, and holds nothing new for the attempt. A provider allocates the call's request id before it builds the request, so an error in the task's configuration or in writing its input has an id the sidecar never saw.

    Raises:
        SampleRefusedError: If the sidecar couldn't place the sample.
        SidecarNotJudgedError: If the sidecar couldn't judge the call for another reason, or the task requires a sidecar and the call's judgment is unavailable.
    """
    # as in `refused_output`: an attempt that failed unsent is never looked up
    if not received.sent:
        return None
    if received.looked is None:
        await request_result(received, replied=False)
    # A sidecar the task requires that keeps no record of the call may have
    # lost the eval in a restart, and what it holds for the attempt may have
    # begun afresh since, so it is never copied, as for a lost sample.
    if lost_sample(
        received.looked, received.registered_beforehand
    ) or unknown_to_required(received.looked, received.mode):
        _note_lost(received)
    unjudged_error(
        received.looked, error, received.registered_beforehand, received.mode
    )
    return _refusal(received.judgment, model, bridged)


def _note_lost(received: ReceivedCall) -> None:
    # the sidecar lost the sample, so whatever it holds for this attempt now
    # started afresh partway through: the attempt's monitor state is lost
    from inspect_ai.log._samples import sample_active

    from ._task import attempt_number, task_sidecars

    sidecars = task_sidecars()
    active = sample_active()
    if sidecars is not None and active is not None:
        sidecars.lost_monitor_state(active.sample_uuid, attempt_number(active))


def _refusal(
    judgment: Judgment | None, model: str, bridged: bool
) -> ModelOutput | None:
    if judgment is None or judgment.outcome == "proceed":
        return None
    # A bridged agent runs its own tools, so a rejected turn handed to it would
    # run: its refusal stands, as the provider's error, and the sidecar adds
    # the rejection to the conversation's later requests.
    if judgment.outcome == "reject" and (bridged or judgment.withheld is None):
        return None
    # the reply the sidecar refused was billed, and counts as the call's usage
    if judgment.withheld is None or bridged:
        return ModelOutput(model=model, choices=[], usage=_usage(judgment))
    return ModelOutput(
        model=model,
        choices=[
            ChatCompletionChoice(
                message=_message(judgment.withheld), stop_reason="tool_calls"
            )
        ],
        usage=_usage(judgment),
    )


def refused_usage(received: ReceivedCall) -> ModelUsage | None:
    """What the provider billed for a reply the sidecar refused, which Inspect counts as it counts any model call's usage."""
    return _usage(received.judgment)


def _usage(judgment: Judgment | None) -> ModelUsage | None:
    if judgment is None or judgment.usage is None:
        return None
    return ModelUsage.model_validate(judgment.usage)


def act_on_judgment(
    judgment: Judgment, output: ModelOutput, bridged: bool
) -> ModelOutput:
    """Act on what the sidecar decided of an agent call, and return the output the agent is handed. A `terminate` is acted on by `end_if_terminated`, once the reports are in the transcript, unless it ends the sample at the turn's calls."""
    if judgment.outcome == "terminate":
        if _ends_at_calls(judgment, output, bridged):
            # every call of the turn ends the sample, so whichever Inspect
            # would run first ends it before any runs
            ended = CallDecision("terminate", message=_explanation(judgment) or _ENDED)
            _decide({call.id: ended for call in output.message.tool_calls or []})
        return output
    # A bridged agent runs its own tools, so it is handed the turn as the
    # sidecar left it: a call put back would run.
    if bridged:
        return output

    # The calls the agent was handed, as its provider read them. A provider
    # may read a call under another name and arguments than the sidecar
    # writes, as the Responses converter does for the planning tools, and the
    # task's tool goes by the provider's.
    handed = (
        {call.id: call for call in output.choices[0].message.tool_calls or []}
        if output.choices
        else {}
    )
    decisions: dict[str, CallDecision] = {}
    turn = judgment.withheld if judgment.outcome == "reject" else judgment.proposed
    if turn is not None:
        for id, told in turn.results.items():
            decisions[id] = CallDecision("reject", message=told)
    # A turn refused whole ran nothing, whatever each call's step decided: a
    # call a step changed is among those the sidecar says didn't run, when it
    # couldn't write the change and refused the turn instead. Only a turn the
    # agent was handed runs its changed calls.
    if judgment.outcome == "proceed":
        for step in judgment.steps:
            if step.stage != "tool_call" or step.call is None:
                continue
            if step.decision.get("action") == "modify" and step.decision.get(
                "modified"
            ):
                # the sidecar wrote the change into the reply, so the call
                # the agent was handed is the changed call as the provider
                # read it, which is what runs
                modified = _TOOL_CALL.validate_python(step.decision["modified"])
                decisions[step.call] = CallDecision(
                    "modify", modified=handed.get(step.call, modified)
                )

    _decide(decisions)
    if judgment.outcome == "proceed" and output.choices and turn is not None:
        # the model's turn as the eval holds it: each call taken out put back
        # with its id and function only, and each changed call as it ran,
        # with the calls the agent was handed as its provider read them
        own = output.choices[0].message
        calls = [handed.get(call.id, call) for call in _message(turn).tool_calls or []]
        output.choices[0].message = own.model_copy(update={"tool_calls": calls})
        if calls:
            output.choices[0].stop_reason = "tool_calls"
    return output


def end_if_terminated(judgment: Judgment, output: ModelOutput, bridged: bool) -> None:
    """End the sample if a sentinel in the sidecar ended it, as an in-process sentinel's `terminate` does.

    A sentinel that ended the sample at a call of the model's turn ends it when Inspect would run the turn's calls, as in process, so the turn is the agent's, as an in-process sentinel leaves it.

    Raises:
        TerminateSampleError: If the call's outcome is `terminate`, and it doesn't end the sample at the turn's calls.
    """
    if judgment.outcome == "terminate" and not _ends_at_calls(
        judgment, output, bridged
    ):
        raise TerminateSampleError(_explanation(judgment) or _ENDED)


def _ends_at_calls(judgment: Judgment, output: ModelOutput, bridged: bool) -> bool:
    # A bridged agent runs its own tools, out of Inspect's sight, so its
    # sample ends at the model call, even for a reply whose calls came back
    # with it, when `request_result` says the run ended at one. A sidecar that
    # ended the run for a reason of its own, with no sentinel's terminate at a
    # call, ends it there too.
    if bridged or not output.choices or not output.message.tool_calls:
        return False
    ended = next(
        (
            s
            for s in reversed(judgment.steps)
            if s.decision.get("action") == "terminate"
        ),
        None,
    )
    return ended is not None and ended.stage == "tool_call"


def _decide(decisions: dict[str, CallDecision]) -> None:
    if not decisions:
        return
    from inspect_ai.log._samples import sample_active

    active = sample_active()
    if active is not None:
        _decisions.setdefault(active, {}).update(decisions)


def _message(turn: WithheldTurn) -> ChatMessageAssistant:
    return ChatMessageAssistant.model_validate(turn.message)


def _explanation(judgment: Judgment) -> str | None:
    for step in reversed(judgment.steps):
        explanation = step.decision.get("explanation")
        if step.decision.get("action") == "terminate" and isinstance(explanation, str):
            return explanation
    return None
