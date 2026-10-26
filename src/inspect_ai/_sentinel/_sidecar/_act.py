"""Acting on a sidecar's protocol decisions, as Inspect acts on an in-process sentinel's.

A sidecar judges a whole turn before Inspect is handed it. A call it rejected is put back into the model's turn and answered with an approval error when Inspect would run it; a call it changed runs with its new arguments, while the model's turn keeps the call the model made; a `terminate` ends the sample.
"""

from typing import Any, Literal, NamedTuple
from weakref import WeakKeyDictionary

from pydantic import TypeAdapter

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput
from inspect_ai.tool._tool_call import ToolCall

from ._field import SentinelField, WithheldTurn, current_receiving, received_field
from ._lookup import request_result

_ENDED = "A sentinel in the sidecar ended the sample."

_TOOL_CALL = TypeAdapter(ToolCall)


class CallDecision(NamedTuple):
    """What the sidecar decided of one call of the model's turn, for Inspect to act on when it would run the call."""

    action: Literal["reject", "modify"]
    message: str | None = None
    """What the model is told of a rejected call."""
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


async def refused_output(model: str, retryable: bool) -> ModelOutput | None:
    """A refusal of the current agent call, as the model output Inspect acts on, or None if the call wasn't refused by a sidecar's decision.

    A rejected turn is the model's turn, whose calls are answered with approval errors, as in process. A turn refused because the sample ended is the model's turn if the sidecar was handed one, else empty. A refusal that came without the field, which Inspect won't retry, is looked up with `request_result`.

    Args:
        model: The model's name, for the output.
        retryable: Whether Inspect retries the call's error, as it does an ordinary provider or network failure.
    """
    received = current_receiving()
    if received is None:
        return None
    if received.field is None and not retryable:
        received.looked = await request_result(received, replied=False)
        if received.looked.state == "decided":
            received.field = received.looked.field
    field = received_field()
    if field is None or field.outcome == "proceed":
        return None
    if field.withheld is None:
        if field.outcome == "reject":
            return None
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
    """Act on what the sidecar decided of an agent call, and return the output the agent is handed. A `terminate` is acted on by `end_if_terminated`, once the reports are in the transcript."""
    if field.outcome == "terminate":
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

    if decisions:
        from inspect_ai.log._samples import sample_active

        active = sample_active()
        if active is not None:
            _decisions.setdefault(active, {}).update(decisions)
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


def end_if_terminated(field: SentinelField) -> None:
    """End the sample if a sentinel in the sidecar ended it, as an in-process sentinel's `terminate` does.

    Raises:
        TerminateSampleError: If the call's outcome is `terminate`.
    """
    if field.outcome == "terminate":
        raise TerminateSampleError(_explanation(field) or _ENDED)


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
