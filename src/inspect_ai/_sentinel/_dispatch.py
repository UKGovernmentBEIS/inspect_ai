from collections.abc import Sequence
from copy import copy
from dataclasses import fields
from logging import getLogger
from typing import Any, Literal, cast
from weakref import WeakKeyDictionary

from inspect_sentinel import (
    AfterGenerate,
    AfterToolCall,
    BeforeGenerate,
    BeforeToolCall,
    Context,
    Decision,
    Escalations,
    EvalContext,
    Failed,
    HumanAnswer,
    HumanDecision,
    Observation,
    Report,
    Reported,
    Step,
    Truncation,
)
from inspect_sentinel._integration import (
    HostContext,
    kept_human_decision,
    run_sentinel,
    supersedes,
    watched_stages,
)

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.logger import warn_once
from inspect_ai._util.registry import registry_info, registry_lookup
from inspect_ai.approval._human.approver import human_approver
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sentinel import (
    SentinelAction,
    SentinelEvent,
    SentinelStatus,
    SentinelSuspicion,
)
from inspect_ai.log._samples import sample_active
from inspect_ai.log._transcript import (
    Transcript,
    TranscriptHistoryUnavailableError,
    transcript,
)
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import (
    Model,
    active_model,
    get_model,
    model_roles,
    suspend_model_event_sink,
)
from inspect_ai.model._model_info import get_model_input_budget
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer._metric import Reference
from inspect_ai.solver._task_state import sample_state
from inspect_ai.tool._tool import ToolApprovalError, ToolResult
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallView,
    ToolCallViewer,
    ToolCallViewError,
    resolve_tool_call_view,
)
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._limit import suspend_limits
from inspect_ai.util._span import span
from inspect_ai.util._store import store

from ._agent_state import agent_messages
from ._config import SENTINEL_MIN_VERSION, SentinelRoot
from ._context import (
    SentinelFailure,
    active_sentinel,
    active_task_description,
    active_task_metadata,
)
from ._conversation import current_conversation
from ._person import (
    ask_about_request,
    ask_about_turn,
    chosen_decision,
    escalation_lines,
    human_view,
    offered_choices,
)
from ._scope import BRIDGE_CHECK_SPAN, sentinel_scope
from ._steps import (
    ConversationRecord,
    after_generate,
    after_tool_call,
    before_generate,
    before_tool_call,
    not_sent_before,
    produced_by,
    producer_of,
    step_stage,
)

logger = getLogger(__name__)

_UPGRADE = f"inspect_ai requires inspect_sentinel {SENTINEL_MIN_VERSION} or later: pip install --upgrade inspect-sentinel"

_Kind = Literal["observation", "decision"]


async def sentinel_before_tool_call(
    message: str,
    message_id: str | None,
    call: ToolCall,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage] | None,
    producer: ModelEvent | None = None,
    *,
    bridge: bool = False,
    execution_id: str | None = None,
) -> Decision | None:
    if not _watches(BeforeToolCall):
        return None
    _require_message_id()
    try:
        view = resolve_tool_call_view(call, viewer, reject_on_error=True)
    except ToolCallViewError as ex:
        raise ToolApprovalError(str(ex)) from ex
    if producer is None and history is not None:
        producer = _producing_event(call, history)
    conversation = current_conversation()
    step = before_tool_call(
        conversation=conversation,
        message=message,
        message_id=_message_id(message_id),
        call=call,
        view=view,
        producer=producer_of(producer),
        agent_messages=agent_messages(conversation),
        record=_record(conversation),
    )
    return await _run(step, call.id, bridge=bridge, execution_id=execution_id)


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
    message_id: str | None,
    call: ToolCall,
    result: ChatMessageTool,
    output: ToolResult,
    truncated: tuple[int, int] | Literal[False] | None,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage] | None,
    producer: ModelEvent | None = None,
    *,
    reject_on_viewer_error: bool = False,
    bridge: bool = False,
    execution_id: str | None = None,
    view: ToolCallView | None = None,
) -> None:
    """Run the sentinel after a tool call ran, before the model sees its result.

    `view` is the call's view, if already rendered with `viewer` (a bridge
    renders it to tell the step apart from those already checked); otherwise
    it is rendered here.
    """
    if not _watches(AfterToolCall):
        return
    _require_message_id()
    if producer is None and history is not None:
        producer = _producing_event(call, history)
    conversation = current_conversation()
    step = after_tool_call(
        conversation=conversation,
        message=message,
        message_id=_message_id(message_id),
        call=call,
        view=view
        if view is not None
        else resolve_tool_call_view(
            call, viewer, reject_on_error=reject_on_viewer_error
        ),
        result=result,
        output=output,
        # None when the host cannot tell (a scaffold-run tool under a bridge)
        truncated=Truncation(*truncated) if truncated else truncated,
        producer=producer_of(producer),
        agent_messages=agent_messages(conversation),
        record=_record(conversation),
    )
    decision = await _run(step, call.id, bridge=bridge, execution_id=execution_id)
    if decision is not None and decision.action == "terminate":
        raise TerminateSampleError(
            decision.explanation or "Sentinel requested termination."
        )


async def sentinel_before_generate(
    *,
    generate_id: str,
    model: str,
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
) -> BeforeGenerate | None:
    """Run the sentinel before one of the agent's generates.

    Args:
        generate_id: The generate's id, the `uuid` its first `ModelEvent` is created with: the step id of both generate stages.
        model: The model's name.
        input: The input as prepared for the model.
        tools: The tools as prepared for the model.
        tool_choice: The tool choice as prepared for the model.
        config: The generate config.

    Returns:
        The step, for `sentinel_after_generate`, or None when nothing in the sentinel watches either generate stage.

    Raises:
        TerminateSampleError: The sentinel requested termination.
        SentinelFailure: A monitor or protocol failed.
    """
    root = active_sentinel()
    if root is None or not (watched_stages(root) & {BeforeGenerate, AfterGenerate}):
        return None
    conversation = current_conversation()
    step = before_generate(
        model=model,
        conversation=conversation,
        input=input,
        tools=tools,
        tool_choice=tool_choice,
        config=config,
        agent_messages=agent_messages(conversation),
        record=_record(conversation),
    )
    await _run_generate(step, generate_id)
    return step


async def sentinel_after_generate(
    before: BeforeGenerate, output: ModelOutput, generate_id: str
) -> None:
    """Run the sentinel after one of the agent's generates, before its output reaches the agent.

    Raises:
        TerminateSampleError: The sentinel requested termination.
        SentinelFailure: A monitor or protocol failed.
    """
    step = after_generate(
        model=before.model,
        conversation=before.conversation,
        input=before.input,
        tools=before.tools,
        tool_choice=before.tool_choice,
        config=before.config,
        output=output,
        agent_messages=agent_messages(before.conversation),
        record=_record(before.conversation),
    )
    await _run_generate(step, generate_id)


async def _run_generate(step: BeforeGenerate | AfterGenerate, step_id: str) -> None:
    decision = await _run(step, step_id)
    if decision is not None and decision.action == "terminate":
        raise TerminateSampleError(
            decision.explanation or "Sentinel requested termination."
        )


def _watches(stage: type[Step]) -> bool:
    root = active_sentinel()
    return root is not None and stage in watched_stages(root)


def watches_tool_results() -> bool:
    return _watches(AfterToolCall)


async def _run(
    step: Step,
    step_id: str,
    *,
    bridge: bool = False,
    execution_id: str | None = None,
) -> Decision | None:
    root = active_sentinel()
    if root is None or type(step) not in watched_stages(root):
        return None
    recorder = _Recorder(step_id, execution_id)
    try:
        try:
            async with span(
                name=BRIDGE_CHECK_SPAN if bridge else "sentinel", type="sentinel"
            ):
                try:
                    with (
                        suspend_limits(),
                        sentinel_scope("sentinel", final=True),
                        suspend_model_event_sink(),
                    ):
                        decision = await run_sentinel(
                            root, _host_context(recorder), step
                        )
                except Exception as ex:
                    recorder.raised(root, step, ex)
                    raise
        except TimeoutError as ex:
            # the sample runner treats a bare TimeoutError as benign
            raise RuntimeError(
                f"A sentinel timed out at the {step_stage(step)} stage: {ex}"
            ) from ex
    except Exception as ex:
        raise SentinelFailure(ex) from ex
    if recorder.kept:
        _record(step.conversation).publish(recorder.kept)
    if decision is not None and decision.action == "escalate":
        raise SentinelFailure(
            RuntimeError(
                f"inspect_sentinel returned an escalate at the {step_stage(step)} stage, "
                f"which it should have turned into a terminate. {_UPGRADE}"
            )
        )
    return decision


def _host_context(recorder: "_Recorder") -> HostContext:
    return HostContext(
        host=_HostNative(_eval_context()),
        recorder=recorder,
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


def record_agent_turn(input: list[ChatMessage], model: str) -> None:
    _record(current_conversation()).record(input, model)


def _record(conversation: str) -> ConversationRecord:
    records = _records.setdefault(transcript(), {})
    record = records.get(conversation)
    if record is None:
        record = records[conversation] = ConversationRecord()
    return record


# each conversation's record, per sample
_records: "WeakKeyDictionary[Transcript, dict[str, ConversationRecord]]" = (
    WeakKeyDictionary()
)


def _require_message_id() -> None:
    if "message_id" not in {f.name for f in fields(BeforeToolCall)}:
        raise SentinelFailure(
            RuntimeError(
                f"The installed inspect_sentinel predates the tool steps' message_id. {_UPGRADE}"
            )
        )


def _message_id(message_id: str | None) -> str:
    # every message is given an id when built; only one read back from a
    # log that recorded none lacks it
    assert message_id is not None, (
        "The assistant message that made a tool call has no id."
    )
    return message_id


def _assistant_index(call: ToolCall, history: list[ChatMessage]) -> int | None:
    for index in range(len(history) - 1, -1, -1):
        message = history[index]
        if isinstance(message, ChatMessageAssistant) and any(
            tool_call.id == call.id for tool_call in message.tool_calls or []
        ):
            return index
    return None


def _producing_event(call: ToolCall, history: list[ChatMessage]) -> ModelEvent | None:
    index = _assistant_index(call, history)
    message_id = history[index].id if index is not None else None
    if message_id is None:
        return None
    try:
        return transcript().history.find_last(produced_by(message_id))
    except TranscriptHistoryUnavailableError:
        return None
    except Exception as ex:
        raise SentinelFailure(ex) from ex


class _HostNative:
    def __init__(self, eval: EvalContext | None) -> None:
        self.eval = eval

    def _resolve(self, model: str | None, role: str | None) -> Model:
        """Resolve the model a host call names, the way `generate` does.

        A `model` name without a `role` runs as its own model under the
        'sentinel' role; otherwise the role (default 'monitor') resolves,
        falling back to the agent's own model when no role is configured.
        """
        if isinstance(cast(object, model), Model):
            raise TypeError(
                "A host model argument must be a model name, not a Model. "
                "Configure the Model for a role with Task(model_roles={'<role>': model}) "
                "or --model-role, and pass role='<role>'."
            )
        if model == "":
            raise ValueError(
                "A host model argument must be a model name, not an empty string. "
                "Pass None to use a role."
            )
        if role == "":
            raise ValueError(
                "A host role argument must be a model role, not an empty string. "
                "Pass None for the 'monitor' role."
            )
        if model is not None and role is None:
            resolved = copy(get_model(model))
            resolved._set_role("sentinel")
            return resolved
        role = role or "monitor"
        if model is None and role not in model_roles():
            warn_once(
                logger,
                f"No model is configured for the sentinel role '{role}', so monitor calls use the agent's own model. "
                f"Set one with Task(model_roles={{'{role}': ...}}) or --model-role {role}=<model>.",
            )
        return get_model(model, role=role, default=active_model())

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
        return await self._resolve(model, role).generate(
            input,
            tools=tools or [],
            tool_choice=tool_choice,
            config=config or GenerateConfig(),
        )

    async def input_budget(
        self,
        *,
        model: str | None = None,
        role: str | None = None,
        config: GenerateConfig | None = None,
    ) -> int:
        return get_model_input_budget(self._resolve(model, role), config)

    async def count_tokens(
        self,
        input: str | list[ChatMessage],
        *,
        model: str | None = None,
        role: str | None = None,
        config: GenerateConfig | None = None,
    ) -> int:
        return await self._resolve(model, role).count_tokens(input, config)

    async def ask_human(
        self,
        step: Step,
        escalations: Escalations,
        choices: Sequence[str],
    ) -> HumanAnswer:
        if "modify" in choices:
            raise NotImplementedError(
                "human() cannot offer 'modify' in inspect_ai, since its human "
                "approval surfaces cannot edit a tool call yet."
            )
        if isinstance(step, BeforeGenerate | AfterGenerate) and "reject" in choices:
            raise ValueError(
                f"human() cannot offer 'reject' at the {step_stage(step)} stage, "
                "where a generate can only proceed or be terminated."
            )
        offered = offered_choices(choices)
        # the approval surfaces are given the conversation; a step with no
        # agent's list gives what the model saw instead, and nothing when that
        # is unknown too
        if step.agent_messages is not None:
            conversation = step.agent_messages
        elif step.input is not None:
            conversation = step.input
        else:
            conversation = []
        approve = human_approver(choices=offered)
        if isinstance(step, BeforeGenerate):
            approval = await ask_about_request(
                approve,
                step.model,
                len(step.input),
                # by this host's record of what the model was sent:
                # `step.history` is what the conversation has sent any model
                not_sent_before(
                    step.input, _record(step.conversation).sent_to(step.model)
                ),
                [tool.name for tool in step.tools],
                step.tool_choice,
                [(e.name, e.report.explanation) for e in escalations],
                offered,
                list(conversation),
            )
        elif isinstance(step, AfterGenerate):
            approval = await ask_about_turn(
                approve,
                step.output.message if step.output.choices else None,
                [(e.name, e.report.explanation) for e in escalations],
                offered,
                list(conversation),
            )
        else:
            approval = await approve(
                step.message,
                step.call,
                _human_view(step, escalations),
                list(conversation),
            )
        decision, reason = chosen_decision(approval, offered)
        return HumanAnswer(decision=decision, reason=reason)


def _human_view(
    step: BeforeToolCall | AfterToolCall, escalations: Escalations
) -> ToolCallView:
    return human_view(
        step.view,
        _escalation_lines(escalations) if escalations else None,
        step.result if isinstance(step, AfterToolCall) else None,
    )


def _escalation_lines(escalations: Escalations) -> str:
    return escalation_lines((e.name, e.report.explanation) for e in escalations)


class _Recorder:
    def __init__(
        self,
        step_id: str,
        execution_id: str | None = None,
    ) -> None:
        self._step_id = step_id
        # the execution a tool-stage step judged (`SentinelEvent.execution_id`)
        self._execution_id = execution_id
        # this step's human() decisions, published once it settles
        self.kept: list[HumanDecision] = []

    def record(
        self, context: Context, factory: str, step: Step, reported: Reported[Report]
    ) -> None:
        report = reported.report
        if isinstance(report, Observation):
            self._emit(
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
            self._emit_decision(
                context,
                factory,
                step,
                "reported",
                reported.function,
                report,
            )
        kept = kept_human_decision(factory, step, self._step_id, reported)
        if kept is not None:
            self.kept.append(kept)

    def failed(
        self, context: Context, factory: str, step: Step, failed: Failed
    ) -> None:
        self._emit(
            context,
            factory,
            step,
            "observation",
            "error",
            function=failed.function,
            error=f"{type(failed.error).__name__}: {failed.error}",
        )

    def raised(self, root: SentinelRoot, step: Step, error: Exception) -> None:
        # the step's invocation failed, so its human() decisions are not
        # published; replay reads this event to withhold them too
        transcript()._event(
            SentinelEvent(
                factory=registry_info(root).name,
                path="",
                function=root.__name__,
                step_id=self._step_id,
                execution_id=self._execution_id,
                conversation=step.conversation,
                stage=step_stage(step),
                kind="observation",
                status="error",
                error=f"{type(error).__name__}: {error}",
            )
        )

    def cancelled(self, context: Context, factory: str, step: Step, name: str) -> None:
        self._emit(context, factory, step, _factory_kind(factory), "cancelled")

    def bypassed(self, context: Context, factory: str, step: Step, name: str) -> None:
        self._emit(context, factory, step, "decision", "bypassed")

    def superseded(
        self,
        context: Context,
        factory: str,
        step: Step,
        reported: Reported[Decision],
    ) -> None:
        self._emit_decision(
            context,
            factory,
            step,
            "superseded",
            reported.function,
            reported.report,
        )
        self.kept = [k for k in self.kept if not supersedes(context.path, reported, k)]

    def _emit_decision(
        self,
        context: Context,
        factory: str,
        step: Step,
        status: SentinelStatus,
        function: str,
        decision: Decision,
    ) -> None:
        self._emit(
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
        self,
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
                step_id=self._step_id,
                execution_id=self._execution_id,
                conversation=step.conversation,
                stage=step_stage(step),
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


def _factory_kind(factory: str) -> _Kind:
    if registry_lookup("protocol", factory) is not None:
        return "decision"
    return "observation"
