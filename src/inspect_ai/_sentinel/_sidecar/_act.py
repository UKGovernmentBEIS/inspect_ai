"""Acting on a sidecar's protocol decisions, as Inspect acts on an in-process sentinel's.

A sidecar judges a whole turn before Inspect is handed it, and Inspect asks what it decided with `request_result`. A call it rejected is put back into the model's turn, with its id and function only, since an eval is never handed a rejected call's arguments, and answered with an approval error when Inspect would run it; a call it changed is held and runs as changed; a `terminate` ends the sample where an in-process sentinel's would, at the model call or before the turn's calls run.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal, NamedTuple
from weakref import WeakKeyDictionary

import anyio
from pydantic import TypeAdapter

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.tool._tool_call import ToolCall

from ._lookup import (
    Answer,
    fetch_usage,
    lost_sample,
    record_unasked_usage,
    request_result,
    settle_usage,
    unjudged_error,
    unknown_to_required,
)
from ._received import (
    Judgment,
    ReceivedCall,
    WithheldTurn,
    current_receiving,
    record_send,
)

_ENDED = "A sentinel in the sidecar ended the sample."

SendAgainResult = ModelOutput | tuple[ModelOutput | Exception, ModelCall]
"""What a provider's `generate` returns when Inspect sends a call's request again."""

_TOOL_CALL = TypeAdapter(ToolCall)

if TYPE_CHECKING:
    from inspect_ai.model._response_headers import ResponseHeaders


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
    model: str,
    retryable: Callable[[], bool],
    bridged: Callable[[], bool],
    send_again: Callable[[], Awaitable[SendAgainResult]] | None = None,
    response_headers: "ResponseHeaders | None" = None,
) -> ModelOutput | SendAgainResult | None:
    """A refusal of the current agent call, as the model output Inspect acts on, or None if the call wasn't refused by a sidecar's decision.

    A rejected turn is the model's turn, whose calls are answered with approval errors, as in process. A turn refused because the sample ended is the model's turn if the sidecar was handed one, else empty. An error Inspect retries, such as a 503, isn't looked up while it is retried: the sidecar is asked with `request_result` only of an error Inspect won't retry.

    A sidecar that can ask a person through the eval is the exception. For such
    a sidecar, Inspect also looks up an error it will retry, once for each
    attempt, because the error may hide the sidecar's "pending review" answer.
    That lookup waits while the sidecar is still judging the attempt, so the
    retry starts only after the judging has ended.

    If a sentinel in the sidecar asked a person about the call, the sidecar
    paused the call and its request returned an error. `request_result` shows
    the person the question and sends their answer. `finish_paused_call` then
    fetches what the sidecar holds for the call, or resends the request for the
    provider. If that returns a reply, this function returns the reply in place
    of a refusal.

    Args:
        model: The model's name, for the output.
        retryable: Whether Inspect retries the call's error, as it does an ordinary provider or network failure. Asked only of a call that went through a sidecar, since a provider's `should_retry` can log or raise.
        bridged: Whether the call is a bridged agent's, which runs its own tools.
        send_again: Sends the call's model request again, and returns what the
            provider's `generate` returns. Called only for a call that a
            sentinel in a sidecar asked a person about.
        response_headers: The headers of the call's latest response, which its
            HTTP hooks store. They show whether a response is a provider's error
            that Inspect fetched from the sidecar.

    Raises:
        Exception: The error that the last fetch or resend raised, if none
            returned a reply and the sidecar's decision is not a refusal.
    """
    # Nothing else is asked of a call that didn't go through a sidecar, or of
    # an attempt that failed before any request of it was sent, which the
    # sidecar never saw.
    received = current_receiving()
    if received is None or not received.sent:
        return None
    # The attempt's error is final. Either `finish_paused_call` has already
    # asked the sidecar about the attempt and found nothing more to fetch or
    # resend, or the call was stopped, and fails on what stopped it whatever
    # the sidecar decided: `refusal_after_error` cleans up after it.
    if received.error_is_final:
        return None
    # The attempt's first send returned an error. Record that send's time,
    # because a call that turns out to be paused for a person is timed send by
    # send.
    if not received.sends:
        record_send(received)
    # Inspect doesn't look up an error it will retry, with two exceptions: a
    # call that is already paused for a person, whose state only the sidecar
    # knows, and a sidecar that can ask a person through the eval (below).
    will_retry = retryable()
    if (
        received.reviewed_request_id is None
        and will_retry
        and not getattr(received.sidecar, "review", False)
    ):
        return None
    try:
        if received.reviewed_request_id is None and will_retry:
            # The error may hide the sidecar's "pending review" answer, for
            # example when the connection failed before that answer arrived.
            # Inspect's retry gets a new `x-irid`, which the sidecar would
            # judge as a new call, so Inspect asks the sidecar first. If no
            # person was asked about the call, Inspect retries as usual.
            await request_result(received, replied=False)
            if received.reviewed_request_id is None:
                return None
        if received.looked is None:
            await request_result(received, replied=False)
        if send_again is None or received.reviewed_request_id is None:
            return _refusal(received.judgment, model, bridged())
        from ._review import finish_paused_call

        after = await finish_paused_call(
            received, send_again, will_retry, response_headers
        )
    except BaseException:
        # Inspect is giving up on the call. It was cancelled while a person
        # decided, or the review raised an error of Inspect's own, such as a
        # limit, or a sidecar that refuses the person's answer. Inspect
        # cancels the paused call at the sidecar now, so that the sidecar
        # keeps no question that nobody will answer, and so that the
        # question's record reaches the sample's log. Otherwise the sidecar
        # closes the call only when the sample ends, after the log is written.
        # A call that was stopped is cancelled by its own cleanup, in
        # `refusal_after_error`, which also settles what it billed.
        if received.stopped_by is None:
            from ._review import cancel_paused_call

            await cancel_paused_call(received)
        raise
    if after.reply is not None:
        return after.reply
    refusal = _refusal(received.judgment, model, bridged())
    if refusal is not None:
        return refusal
    if after.raised is not None:
        raise after.raised
    return after.returned_error


async def refusal_after_error(
    received: ReceivedCall, model: str, error: BaseException, bridged: bool
) -> ModelOutput | None:
    """A refusal of an agent call that Inspect stopped retrying, as the model output Inspect acts on, or None to let the error stand.

    An error Inspect retries, such as a 503, is not looked up while it is retried; once the retries are spent, the sidecar is asked what it decided.

    An error raised before any request of the attempt was sent stands as it is, and the sidecar is asked nothing of the attempt: it was never sent the call, so it has no judgment of it to be unavailable, and holds nothing new for it. Earlier attempts Inspect retried are still asked about, for their judging usage. A provider allocates the call's request id before it builds the request, so an error in the task's configuration or in writing its input has an id the sidecar never saw.

    Raises:
        SampleRefusedError: If the sidecar couldn't place the sample.
        SidecarNotJudgedError: If the sidecar couldn't judge the call for another reason, or the task requires a sidecar and the call's judgment is unavailable.
        SentinelProxyError: If the call was stopped because the sidecar couldn't take the sample's registration as a request of it was sent.
    """
    if received.stopped_by is not None:
        await _settle_stopped_call(received)
        raise received.stopped_by
    # as in `refused_output`: an attempt that failed unsent is never looked up,
    # though earlier attempts that were sent may still have been judged
    if not received.sent:
        await record_unasked_usage(received)
        return None
    if received.looked is None:
        await request_result(received, replied=False)
    if received.paused:
        # Inspect has stopped retrying a paused call, so nothing will resend
        # it. Cancel it at the sidecar.
        from ._review import cancel_paused_call

        await cancel_paused_call(received)
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


STOPPED_CALL_TIMEOUT = 10.0
"""The longest Inspect spends cleaning up after a stopped call, in seconds: cancelling it at the sidecar, and asking what its requests billed. What it hasn't learned by then is noted as unknown."""


async def _settle_stopped_call(received: ReceivedCall) -> None:
    # The call was stopped, as when the sidecar couldn't take the sample's
    # registration while a request of it was sent, and fails on what stopped
    # it. This cleans up after it, whichever of its requests were sent,
    # paused, retried or asked about before, and changes nothing of how the
    # call ends. It raises nothing of its own, waits on no judging and asks
    # no person. All of it has one deadline, `STOPPED_CALL_TIMEOUT`, and is
    # shielded for that long, so a limit of the sample's that runs out
    # meanwhile doesn't end the sample in the stopped call's place.
    from ._review import cancel_call_by_id, cancel_paused_call

    # The request the sidecar may still hold: one it paused for a person, or
    # the latest attempt's, if it was sent.
    paused = received.paused
    held = (
        received.reviewed_request_id
        if paused
        else (received.request_id if received.sent else None)
    )
    # Each request the sidecar may have judged: the attempts Inspect retried
    # without asking about them, and the one it may still hold.
    owed = list(dict.fromkeys([*received.unasked, *([held] if held else [])]))
    received.unasked.clear()
    unanswered = "the sidecar didn't answer"
    with anyio.move_on_after(STOPPED_CALL_TIMEOUT, shield=True) as within:
        try:
            answers: dict[str, Answer] = {}
            if held is not None:
                # Nothing will resend a paused call, so it is cancelled at
                # the sidecar. A call Inspect doesn't know to be paused is
                # cancelled by its id, as the sidecar may have paused it and
                # the answer saying so been lost. The sidecar then says what
                # it holds.
                answer = (
                    await cancel_paused_call(received)
                    if paused
                    else await cancel_call_by_id(received)
                )
                if answer is not None:
                    answers[held] = answer
            while owed:
                request_id = owed[0]
                answer = answers.get(request_id)
                if answer is None:
                    # asked once, without waiting
                    answer = await fetch_usage(received, request_id)
                settle_usage(received, request_id, answer)
                owed.pop(0)
        except Exception as ex:
            unanswered = f"the sidecar couldn't be asked: {ex}"
    if within.cancelled_caught:
        unanswered = "the sidecar didn't answer in time"
    for request_id in owed:
        settle_usage(received, request_id, None, unanswered)


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
