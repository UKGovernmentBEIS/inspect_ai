"""Acting on a sidecar's protocol decisions, as Inspect acts on an in-process sentinel's.

A sidecar judges a whole turn before Inspect is handed it. A call it rejected is put back into the model's turn and answered with an approval error when Inspect would run it; a call it changed runs with its new arguments, while the model's turn keeps the call the model made; a `terminate` ends the sample where an in-process sentinel's would, at the model call or before the turn's calls run.
"""

from typing import Any, Literal, NamedTuple
from weakref import WeakKeyDictionary

from pydantic import TypeAdapter

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput
from inspect_ai.tool._tool_call import ToolCall

from ._field import (
    ReceivedField,
    SentinelField,
    WithheldTurn,
    current_receiving,
    parse_field,
    received_field,
)
from ._lookup import request_result, unjudged_error

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
    model: str, retryable: bool, bridged: bool
) -> ModelOutput | None:
    """A refusal of the current agent call, as the model output Inspect acts on, or None if the call wasn't refused by a sidecar's decision.

    A rejected turn is the model's turn, whose calls are answered with approval errors, as in process. A turn refused because the sample ended is the model's turn if the sidecar was handed one, else empty. A refusal that came without the field, which Inspect won't retry, is looked up with `request_result`.

    Args:
        model: The model's name, for the output.
        retryable: Whether Inspect retries the call's error, as it does an ordinary provider or network failure.
        bridged: Whether the call is a bridged agent's, which runs its own tools.
    """
    received = current_receiving()
    if received is None:
        return None
    if received.field is None and not retryable:
        received.looked = await request_result(received, replied=False)
        if received.looked.state == "decided":
            received.field = received.looked.field
    return _refusal(received_field(), model, bridged)


async def refusal_after_error(
    received: ReceivedField, model: str, error: BaseException, bridged: bool
) -> ModelOutput | None:
    """A refusal of an agent call that Inspect stopped retrying, as the model output Inspect acts on, or None to let the error stand.

    An error Inspect retries, such as a 503, is not looked up while it is retried; once the retries are spent, the sidecar is asked what it decided.

    Raises:
        SampleRefusedError: If the sidecar couldn't place the sample.
        SidecarNotJudgedError: If the sidecar couldn't judge the call for another reason.
    """
    if received.field is None and received.looked is None:
        received.looked = await request_result(received, replied=False)
        if received.looked.state == "decided":
            received.field = received.looked.field
    unjudged_error(received.looked, error)
    field = parse_field(received.field) if received.field is not None else None
    return _refusal(field, model, bridged)


def _refusal(
    field: SentinelField | None, model: str, bridged: bool
) -> ModelOutput | None:
    if field is None or field.outcome == "proceed":
        return None
    # A bridged agent runs its own tools, so a rejected turn handed to it would
    # run: its refusal stands, as the provider's error, and the sidecar adds
    # the rejection to the conversation's later requests.
    if field.outcome == "reject" and (bridged or field.withheld is None):
        return None
    if field.withheld is None or bridged:
        return ModelOutput(model=model, choices=[])
    return ModelOutput(
        model=model,
        choices=[
            ChatCompletionChoice(
                message=_message(field.withheld), stop_reason="tool_calls"
            )
        ],
    )


def act_on_field(
    field: SentinelField, output: ModelOutput, bridged: bool
) -> ModelOutput:
    """Act on what the sidecar decided of an agent call, and return the output the agent is handed. A `terminate` is acted on by `end_if_terminated`, once the reports are in the transcript, unless it ends the sample at the turn's calls."""
    if field.outcome == "terminate":
        if _ends_at_calls(field, output, bridged):
            # every call of the turn ends the sample, so whichever Inspect
            # would run first ends it before any runs
            ended = CallDecision("terminate", message=_explanation(field) or _ENDED)
            _decide({call.id: ended for call in output.message.tool_calls or []})
        return output
    # A bridged agent runs its own tools, so it is handed the turn as the
    # sidecar left it: a call put back would run.
    if bridged:
        return output

    decisions: dict[str, CallDecision] = {}
    turn = field.withheld if field.outcome == "reject" else field.proposed
    if turn is not None:
        for id, told in turn.results.items():
            decisions[id] = CallDecision("reject", message=told)
    originals: dict[str, ToolCall] = {}
    for step in field.steps:
        if step.stage != "tool_call" or step.call is None:
            continue
        if step.decision.get("action") == "modify" and step.decision.get("modified"):
            modified = _TOOL_CALL.validate_python(step.decision["modified"])
            decisions[step.call] = CallDecision("modify", modified=modified)
            if step.original is not None:
                originals[step.call] = _TOOL_CALL.validate_python(step.original)

    _decide(decisions)
    if field.outcome == "proceed" and output.choices:
        # the model's own turn, as it made it
        message = (
            _message(turn)
            if turn is not None
            else _with_originals(output.choices[0].message, originals)
        )
        output.choices[0].message = message
        if message.tool_calls:
            output.choices[0].stop_reason = "tool_calls"
    return output


def end_if_terminated(field: SentinelField, output: ModelOutput, bridged: bool) -> None:
    """End the sample if a sentinel in the sidecar ended it, as an in-process sentinel's `terminate` does.

    A sentinel that ended the sample at a call of the model's turn ends it when Inspect would run the turn's calls, as in process, so the turn is the agent's, as an in-process sentinel leaves it.

    Raises:
        TerminateSampleError: If the call's outcome is `terminate`, and it doesn't end the sample at the turn's calls.
    """
    if field.outcome == "terminate" and not _ends_at_calls(field, output, bridged):
        raise TerminateSampleError(_explanation(field) or _ENDED)


def _ends_at_calls(field: SentinelField, output: ModelOutput, bridged: bool) -> bool:
    # A bridged agent runs its own tools, out of Inspect's sight, so its
    # sample ends at the model call, even for a reply whose calls came back
    # with it, when `request_result` says the run ended at one. A sidecar that
    # ended the run for a reason of its own, with no sentinel's terminate at a
    # call, ends it there too.
    if bridged or not output.choices or not output.message.tool_calls:
        return False
    ended = next(
        (s for s in reversed(field.steps) if s.decision.get("action") == "terminate"),
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


def _with_originals(
    message: ChatMessageAssistant, originals: dict[str, ToolCall]
) -> ChatMessageAssistant:
    if not originals or not message.tool_calls:
        return message
    calls = [originals.get(call.id, call) for call in message.tool_calls]
    return message.model_copy(update={"tool_calls": calls})


def _explanation(field: SentinelField) -> str | None:
    for step in reversed(field.steps):
        explanation = step.decision.get("explanation")
        if step.decision.get("action") == "terminate" and isinstance(explanation, str):
            return explanation
    return None
