from typing import Any, Literal

from inspect_sentinel import (
    AfterToolCall,
    BeforeToolCall,
    Decision,
    Observation,
    Report,
    Reported,
    Step,
)
from inspect_sentinel._integration import RunnerContext, run_root

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.approval._apply import resolve_tool_call_view
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sentinel import SentinelAction, SentinelEvent, SentinelSuspicion
from inspect_ai.log._samples import sample_active
from inspect_ai.log._transcript import transcript
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import get_model, model_roles
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver._task_state import sample_state
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallViewer
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._limit import suspend_token_limit, suspend_turn_limit
from inspect_ai.util._span import current_agent_span_id
from inspect_ai.util._store import store

from ._context import SentinelFailure, active_sentinel, active_task_metadata

_Kind = Literal["observation", "decision", "cancelled", "bypassed", "superseded"]


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
    try:
        return await _run(step)
    except Exception as ex:
        raise SentinelFailure(ex) from ex


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
        with suspend_token_limit(), suspend_turn_limit():
            return await run_root(root, _context(), step)
    except TimeoutError as ex:
        # the sample runner treats a bare TimeoutError as benign
        raise RuntimeError(
            f"A sentinel timed out at the {_stage(step)} stage: {ex}"
        ) from ex


def _stage(step: Step) -> Literal["tool_call", "tool_result"]:
    return "tool_call" if isinstance(step, BeforeToolCall) else "tool_result"


def _context() -> RunnerContext:
    active = sample_active()
    state = sample_state()
    if state is not None:
        sample_metadata = state.metadata
    elif active is not None:
        sample_metadata = active.sample.metadata or {}
    else:
        sample_metadata = {}
    return RunnerContext(
        task=active.task if active is not None else None,
        task_description=None,
        sample_id=(
            state.sample_id
            if state is not None
            else active.sample.id
            if active is not None
            else None
        ),
        epoch=(
            state.epoch
            if state is not None
            else active.epoch
            if active is not None
            else None
        ),
        sample_description=None,
        input=(
            state.input
            if state is not None
            else active.sample.input
            if active is not None
            else ""
        ),
        metadata={**active_task_metadata(), **sample_metadata},
        path="",
        store=store(),
        host=_Host(),
        recorder=_Recorder(),
        factory="",
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
    index = _assistant_index(call, history)
    if index is None:
        return list(history)
    assistant_id = history[index].id
    for event in reversed(transcript().history.resident_events):
        if (
            isinstance(event, ModelEvent)
            and event.output.choices
            and event.output.choices[0].message.id == assistant_id
        ):
            return list(event.input)
    return history[:index]


class _Host:
    async def generate(
        self,
        input: str | list[ChatMessage],
        *,
        model: str | None = None,
        tools: list[ToolInfo] | None = None,
        config: GenerateConfig | None = None,
    ) -> ModelOutput:
        if model is None:
            resolved = get_model(role="monitor")
        elif model in model_roles():
            resolved = get_model(role=model)
        else:
            resolved = get_model(model)
        return await resolved.generate(
            input, tools=tools or [], config=config or GenerateConfig()
        )


class _Recorder:
    def record(
        self, context: RunnerContext, step: Step, reported: Reported[Report]
    ) -> None:
        report = reported.report
        if isinstance(report, Observation):
            _emit(
                context,
                step,
                "observation",
                function=reported.function,
                suspicion=report.suspicion,
                explanation=report.explanation,
                metadata=report.metadata,
            )
        else:
            _emit_decision(context, step, "decision", reported.function, report)

    def cancelled(self, context: RunnerContext, step: Step, name: str) -> None:
        _emit(context, step, "cancelled")

    def bypassed(self, context: RunnerContext, step: Step, name: str) -> None:
        _emit(context, step, "bypassed")

    def superseded(
        self, context: RunnerContext, step: Step, reported: Reported[Decision]
    ) -> None:
        _emit_decision(context, step, "superseded", reported.function, reported.report)


def _emit_decision(
    context: RunnerContext,
    step: Step,
    kind: _Kind,
    function: str,
    decision: Decision,
) -> None:
    _emit(
        context,
        step,
        kind,
        function=function,
        decision=decision.action,
        audit=decision.audit,
        explanation=decision.explanation,
        metadata=decision.metadata,
    )


def _emit(
    context: RunnerContext,
    step: Step,
    kind: _Kind,
    *,
    function: str | None = None,
    suspicion: SentinelSuspicion | None = None,
    decision: SentinelAction | None = None,
    audit: bool = False,
    explanation: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    transcript()._event(
        SentinelEvent(
            name=context.factory,
            path=context.path,
            function=function,
            step_id=step.call.id,
            conversation=step.conversation,
            stage=_stage(step),
            kind=kind,
            suspicion=suspicion,
            decision=decision,
            audit=audit,
            explanation=explanation,
            metadata=metadata,
        )
    )
