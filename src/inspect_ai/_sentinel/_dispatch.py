from collections.abc import Sequence
from copy import copy
from logging import getLogger
from typing import Any, Literal, cast
from weakref import WeakKeyDictionary

from inspect_sentinel import (
    AfterToolCall,
    BeforeToolCall,
    Context,
    Decision,
    EvalContext,
    Failed,
    HumanAnswer,
    Observation,
    Report,
    Reported,
    Step,
)
from inspect_sentinel._integration import HostContext, run_sentinel

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.logger import warn_once
from inspect_ai._util.registry import registry_lookup
from inspect_ai.approval._approval import ApprovalDecision
from inspect_ai.approval._human.approver import human_approver
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sentinel import (
    SentinelAction,
    SentinelEvent,
    SentinelStatus,
    SentinelSuspicion,
)
from inspect_ai.log._samples import sample_active
from inspect_ai.log._transcript import Transcript, transcript
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import Model, active_model, get_model, model_roles
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.review._human import (
    escape_placeholders,
    fenced,
    view_with_result,
)
from inspect_ai.scorer._metric import Reference
from inspect_ai.solver._task_state import sample_state
from inspect_ai.tool._tool import ToolApprovalError, ToolResult
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallContent,
    ToolCallView,
    ToolCallViewer,
    resolve_tool_call_view,
)
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._limit import suspend_token_limit, suspend_turn_limit
from inspect_ai.util._span import current_agent_span_id, span
from inspect_ai.util._store import store

from ._context import (
    SentinelFailure,
    active_sentinel,
    active_task_description,
    active_task_metadata,
)

logger = getLogger(__name__)

_Kind = Literal["observation", "decision"]


async def sentinel_before_tool_call(
    message: str,
    call: ToolCall,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage],
) -> Decision | None:
    step = BeforeToolCall(
        conversation=_conversation(),
        message=message,
        call=call,
        view=resolve_tool_call_view(call, viewer),
        input=_model_input(call, history),
        history=history,
    )
    return await _run(step)


def apply_sentinel_decision(decision: Decision | None, call: ToolCall) -> ToolCall:
    if decision is None:
        return call
    if decision.action == "reject":
        raise ToolApprovalError(decision.message)
    elif decision.action == "terminate":
        raise TerminateSampleError(
            decision.explanation or "Sentinel requested termination."
        )
    elif decision.action == "modify":
        if decision.modified is None:
            raise SentinelFailure(
                RuntimeError("A sentinel modify decision has no modified call.")
            )
        return decision.modified
    return call


async def sentinel_after_tool_call(
    message: str,
    call: ToolCall,
    result: ChatMessageTool,
    output: ToolResult,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage],
) -> None:
    step = AfterToolCall(
        conversation=_conversation(),
        message=message,
        call=call,
        result=result,
        output=output,
        view=resolve_tool_call_view(call, viewer),
        input=_model_input(call, history),
        history=history,
    )
    decision = await _run(step)
    if decision is not None and decision.action == "terminate":
        raise TerminateSampleError(
            decision.explanation or "Sentinel requested termination."
        )


async def _run(step: Step) -> Decision | None:
    root = active_sentinel()
    if root is None:
        return None
    try:
        try:
            async with span(name="sentinel", type="sentinel"):
                with suspend_token_limit(), suspend_turn_limit():
                    decision = await run_sentinel(root, _host_context(), step)
        except TimeoutError as ex:
            # the sample runner treats a bare TimeoutError as benign
            raise RuntimeError(
                f"A sentinel timed out at the {_stage(step)} stage: {ex}"
            ) from ex
    except Exception as ex:
        raise SentinelFailure(ex) from ex
    if decision is not None and decision.action == "escalate":
        # recorded as the root's decision; with nobody above to take it, the call proceeds
        warn_once(
            logger,
            "A sentinel escalated a tool call with nothing to escalate to, so it proceeded; "
            "add sequential([..., human()]) to send escalations to a person.",
        )
        return Decision.proceed()
    return decision


def _stage(step: Step) -> Literal["tool_call", "tool_result"]:
    return "tool_call" if isinstance(step, BeforeToolCall) else "tool_result"


def _host_context() -> HostContext:
    return HostContext(
        context=Context(path="", host=_Host(), eval=_eval_context()),
        recorder=_Recorder(),
        store=store(),
    )


def _eval_context() -> EvalContext | None:
    active = sample_active()
    state = sample_state()
    if active is None or state is None:
        return None
    return EvalContext(
        task=active.task,
        task_description=active_task_description(),
        sample_id=state.sample_id,
        epoch=state.epoch,
        sample_description=active.sample.description,
        sample_input=state.input,
        metadata={**active_task_metadata(), **state.metadata},
    )


def _conversation() -> str:
    agent_span_id = current_agent_span_id()
    if agent_span_id is not None:
        return agent_span_id
    active = sample_active()
    return active.sample_uuid if active is not None else ""


def _assistant_index(call: ToolCall, history: list[ChatMessage]) -> int | None:
    for index in range(len(history) - 1, -1, -1):
        message = history[index]
        if isinstance(message, ChatMessageAssistant) and any(
            tool_call.id == call.id for tool_call in message.tool_calls or []
        ):
            return index
    return None


def _model_input(call: ToolCall, history: list[ChatMessage]) -> list[ChatMessage]:
    current = transcript()
    inputs = _sample_inputs(current)
    index = _assistant_index(call, history)
    if index is None:
        inputs.warn(
            "no_assistant",
            f"No assistant message with tool call {call.id} is in the conversation, "
            "so the sentinel step's input is the whole conversation.",
        )
        return list(history)
    assistant_id = history[index].id
    found = inputs.find(current, assistant_id) if assistant_id is not None else None
    if found is None:
        inputs.warn(
            "no_model_event",
            f"No ModelEvent was found for assistant message {assistant_id}, so the "
            "sentinel step's input is the conversation before it.",
        )
        return history[:index]
    return list(found)


class _SampleInputs:
    def __init__(self) -> None:
        self._inputs: dict[str, ModelEvent] = {}
        self._pending: list[ModelEvent] = []
        self._last: Event | None = None
        self._warned: set[str] = set()

    def find(self, current: Transcript, assistant_id: str) -> list[ChatMessage] | None:
        if assistant_id not in self._inputs:
            self._scan(current)
        event = self._inputs.get(assistant_id)
        return event.input if event is not None else None

    def warn(self, reason: str, message: str) -> None:
        if reason not in self._warned:
            self._warned.add(reason)
            logger.warning(message)

    def _scan(self, current: Transcript) -> None:
        self._inputs = {
            message_id: event
            for message_id, event in self._inputs.items()
            if current._is_resident(event)
        }
        resident = current.history.resident_events
        new: list[ModelEvent] = []
        for event in reversed(resident):
            if event is self._last:
                break
            if isinstance(event, ModelEvent) and event.role != "monitor":
                new.append(event)
        if resident:
            self._last = resident[-1]
        pending: list[ModelEvent] = []
        for event in [*self._pending, *new]:
            if event.pending:
                pending.append(event)
            elif event.output.choices:
                message_id = event.output.choices[0].message.id
                if message_id is not None:
                    self._inputs.setdefault(message_id, event)
        self._pending = pending


_inputs_by_transcript: "WeakKeyDictionary[Transcript, _SampleInputs]" = (
    WeakKeyDictionary()
)


def _sample_inputs(current: Transcript) -> _SampleInputs:
    inputs = _inputs_by_transcript.get(current)
    if inputs is None:
        inputs = _SampleInputs()
        _inputs_by_transcript[current] = inputs
    return inputs


class _Host:
    async def generate(
        self,
        input: str | list[ChatMessage],
        *,
        model: str | None = None,
        role: str | None = None,
        tools: list[ToolInfo] | None = None,
        tool_choice: ToolChoice | None = None,
        config: GenerateConfig | None = None,
    ) -> ModelOutput:
        if isinstance(cast(object, model), Model):
            raise TypeError(
                "Host.generate() takes a model name, not a Model. "
                "Configure the Model for a role with Task(model_roles={'<role>': model}) "
                "or --model-role, and pass role='<role>'."
            )
        if model == "":
            raise ValueError(
                "Host.generate() model must be a model name, not an empty string. "
                "Pass None to use a role."
            )
        if role == "":
            raise ValueError(
                "Host.generate() role must be a model role, not an empty string. "
                "Pass None for the 'monitor' role."
            )
        if model is not None and role is None:
            resolved = copy(get_model(model))
            resolved._set_role("sentinel")
        else:
            role = role or "monitor"
            if model is None and role not in model_roles():
                warn_once(
                    logger,
                    f"No model is configured for the sentinel role '{role}', so monitor calls use the agent's own model. "
                    f"Set one with Task(model_roles={{'{role}': ...}}) or --model-role {role}=<model>.",
                )
            resolved = get_model(model, role=role, default=active_model())
        return await resolved.generate(
            input,
            tools=tools or [],
            tool_choice=tool_choice,
            config=config or GenerateConfig(),
        )

    async def ask_human(self, step: Step, choices: Sequence[str]) -> HumanAnswer:
        if "modify" in choices:
            raise NotImplementedError(
                "human() cannot offer 'modify' in inspect_ai, since its human "
                "approval surfaces cannot edit a tool call yet."
            )
        offered: list[ApprovalDecision] = []
        for choice in choices:
            if choice not in _HUMAN_CHOICES:
                raise ValueError(
                    f"human() cannot offer {choice!r}; the choices are "
                    f"{', '.join(repr(c) for c in _HUMAN_CHOICES)}."
                )
            offered.append(cast(ApprovalDecision, choice))
        approval = await human_approver(choices=offered)(
            step.message, step.call, _human_view(step), step.history
        )
        if approval.decision in offered:
            return HumanAnswer(decision=approval.decision, reason=approval.explanation)
        return HumanAnswer(
            decision="reject" if "reject" in offered else "terminate",
            reason=(
                "Human review ended without one of the offered choices "
                f"({approval.decision}: {approval.explanation})."
            ),
        )


_HUMAN_CHOICES = ("approve", "reject", "terminate")


def _human_view(step: Step) -> ToolCallView:
    view = step.view
    if step.escalations:
        lines = escape_placeholders(
            "\n".join(
                f"- {e.name}: {e.report.explanation}"
                if e.report.explanation
                else f"- {e.name}"
                for e in step.escalations
            )
        )
        escalated = f"**Escalated by**\n\n{fenced(lines)}"
        if view.call is None:
            call = ToolCallContent(format="markdown", content=escalated)
        elif view.call.format == "markdown":
            call = ToolCallContent(
                title=view.call.title,
                format="markdown",
                content=f"{escalated}\n\n{view.call.content}",
            )
        else:
            call = ToolCallContent(
                title=view.call.title,
                format="text",
                content=f"Escalated by\n\n{lines}\n\n{view.call.content}",
            )
        view = ToolCallView(context=view.context, call=call)
    if isinstance(step, AfterToolCall):
        view = view_with_result(view, step.result)
    return view


class _Recorder:
    def record(
        self, context: Context, factory: str, step: Step, reported: Reported[Report]
    ) -> None:
        report = reported.report
        if isinstance(report, Observation):
            _emit(
                context,
                factory,
                step,
                "observation",
                "reported",
                function=reported.function,
                suspicion=report.suspicion,
                explanation=report.explanation,
                references=report.references,
                metadata=report.metadata,
            )
        else:
            _emit_decision(
                context, factory, step, "reported", reported.function, report
            )

    def failed(
        self, context: Context, factory: str, step: Step, failed: Failed
    ) -> None:
        _emit(
            context,
            factory,
            step,
            "observation",
            "error",
            function=failed.function,
            error=f"{type(failed.error).__name__}: {failed.error}",
        )

    def cancelled(self, context: Context, factory: str, step: Step, name: str) -> None:
        _emit(context, factory, step, _factory_kind(factory), "cancelled")

    def bypassed(self, context: Context, factory: str, step: Step, name: str) -> None:
        _emit(context, factory, step, "decision", "bypassed")

    def superseded(
        self,
        context: Context,
        factory: str,
        step: Step,
        reported: Reported[Decision],
    ) -> None:
        _emit_decision(
            context, factory, step, "superseded", reported.function, reported.report
        )


def _factory_kind(factory: str) -> _Kind:
    if registry_lookup("protocol", factory) is not None:
        return "decision"
    return "observation"


def _emit_decision(
    context: Context,
    factory: str,
    step: Step,
    status: SentinelStatus,
    function: str,
    decision: Decision,
) -> None:
    _emit(
        context,
        factory,
        step,
        "decision",
        status,
        function=function,
        action=decision.action,
        audit=decision.audit,
        message=decision.message,
        explanation=decision.explanation,
        references=decision.references,
        metadata=decision.metadata,
        modified=decision.modified,
    )


def _emit(
    context: Context,
    factory: str,
    step: Step,
    kind: _Kind,
    status: SentinelStatus,
    *,
    function: str | None = None,
    suspicion: SentinelSuspicion | None = None,
    action: SentinelAction | None = None,
    audit: bool = False,
    message: str | None = None,
    explanation: str | None = None,
    references: Sequence[Reference] = (),
    metadata: dict[str, Any] | None = None,
    modified: ToolCall | None = None,
    error: str | None = None,
) -> None:
    transcript()._event(
        SentinelEvent(
            factory=factory,
            path=context.path,
            function=function,
            step_id=step.call.id,
            conversation=step.conversation,
            stage=_stage(step),
            kind=kind,
            status=status,
            suspicion=suspicion,
            action=action,
            audit=audit,
            message=message,
            explanation=explanation,
            references=list(references),
            metadata=metadata,
            modified=modified,
            error=error,
        )
    )
