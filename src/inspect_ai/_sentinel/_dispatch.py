import re
from collections import Counter
from collections.abc import Callable, Sequence
from copy import copy
from dataclasses import fields
from logging import getLogger
from typing import Any, Literal, NamedTuple, TypeGuard, cast
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
from shortuuid import uuid as shortuuid

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.format import MARKER_CLOSE, MARKER_OPEN, display_safe
from inspect_ai._util.logger import warn_once
from inspect_ai._util.registry import registry_lookup
from inspect_ai.approval._approval import Approval, ApprovalDecision
from inspect_ai.approval._approver import Approver
from inspect_ai.approval._human.approver import human_approver
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sentinel import (
    SentinelAction,
    SentinelEvent,
    SentinelStage,
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
    ToolCallViewError,
    default_tool_call_viewer,
    resolve_tool_call_view,
    substitute_tool_call_content,
)
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._limit import (
    suspend_token_limit,
    suspend_turn_limit,
    suspend_working_limit,
)
from inspect_ai.util._span import span
from inspect_ai.util._store import store

from ._agent_state import agent_messages
from ._context import (
    SentinelFailure,
    active_sentinel,
    active_task_description,
    active_task_metadata,
)
from ._conversation import current_conversation
from ._scope import sentinel_scope
from ._sent import record_sent, sent_messages

logger = getLogger(__name__)

# the oldest inspect_sentinel this inspect_ai works with
_UPGRADE = "inspect_ai requires inspect_sentinel 0.2.0 or later: pip install --upgrade inspect-sentinel"

_Kind = Literal["observation", "decision"]


async def sentinel_before_tool_call(
    message: str,
    message_id: str | None,
    call: ToolCall,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage],
) -> Decision | None:
    if not _watches(BeforeToolCall):
        return None
    _require_message_id()
    try:
        view = resolve_tool_call_view(call, viewer, reject_on_error=True)
    except ToolCallViewError as ex:
        raise ToolApprovalError(str(ex)) from ex
    producer = _producing_event(call, history)
    conversation = current_conversation()
    step = BeforeToolCall(
        conversation=conversation,
        message=message,
        message_id=_message_id(message_id),
        call=call,
        view=view,
        input=list(producer.input) if producer is not None else None,
        agent_messages=agent_messages(conversation),
        history=sent_messages(conversation),
        human_decisions=_human_decisions(conversation),
        tools=list(producer.tools) if producer is not None else None,
        tool_choice=producer.tool_choice if producer is not None else None,
    )
    return await _run(step, call.id)


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
    truncated: tuple[int, int] | None,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage],
) -> None:
    if not _watches(AfterToolCall):
        return
    _require_message_id()
    producer = _producing_event(call, history)
    conversation = current_conversation()
    step = AfterToolCall(
        conversation=conversation,
        message=message,
        message_id=_message_id(message_id),
        call=call,
        result=result,
        output=output,
        view=resolve_tool_call_view(call, viewer),
        input=list(producer.input) if producer is not None else None,
        agent_messages=agent_messages(conversation),
        history=sent_messages(conversation),
        human_decisions=_human_decisions(conversation),
        tools=list(producer.tools) if producer is not None else None,
        tool_choice=producer.tool_choice if producer is not None else None,
        truncated=Truncation(*truncated) if truncated is not None else False,
    )
    decision = await _run(step, call.id)
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
    step = BeforeGenerate(
        model=model,
        conversation=conversation,
        input=input,
        agent_messages=agent_messages(conversation),
        history=sent_messages(conversation),
        human_decisions=_human_decisions(conversation),
        tools=tools,
        tool_choice=tool_choice,
        config=config,
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
    step = AfterGenerate(
        model=before.model,
        conversation=before.conversation,
        input=before.input,
        agent_messages=agent_messages(before.conversation),
        history=sent_messages(before.conversation),
        human_decisions=_human_decisions(before.conversation),
        tools=before.tools,
        tool_choice=before.tool_choice,
        config=before.config,
        output=output,
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


async def _run(step: Step, step_id: str) -> Decision | None:
    root = active_sentinel()
    if root is None or type(step) not in watched_stages(root):
        return None
    recorder = _Recorder(step_id)
    try:
        try:
            async with span(name="sentinel", type="sentinel"):
                with (
                    suspend_token_limit(),
                    suspend_turn_limit(),
                    suspend_working_limit(),
                    sentinel_scope("sentinel", final=True),
                    suspend_model_event_sink(),
                ):
                    decision = await run_sentinel(root, _host_context(recorder), step)
        except TimeoutError as ex:
            # the sample runner treats a bare TimeoutError as benign
            raise RuntimeError(
                f"A sentinel timed out at the {_stage(step)} stage: {ex}"
            ) from ex
    except Exception as ex:
        raise SentinelFailure(ex) from ex
    _publish(step.conversation, recorder.kept)
    if decision is not None and decision.action == "escalate":
        raise SentinelFailure(
            RuntimeError(
                f"inspect_sentinel returned an escalate at the {_stage(step)} stage, "
                f"which it should have turned into a terminate. {_UPGRADE}"
            )
        )
    return decision


def _stage(step: Step) -> SentinelStage:
    if isinstance(step, BeforeGenerate):
        return "model_input"
    elif isinstance(step, AfterGenerate):
        return "model_output"
    elif isinstance(step, BeforeToolCall):
        return "tool_call"
    return "tool_result"


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


def record_agent_turn(input: list[ChatMessage]) -> None:
    record_sent(current_conversation(), input)


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


def _human_decisions(conversation: str) -> tuple[HumanDecision, ...]:
    """The `human()` decisions published so far in the conversation, for a step about to run.

    Taken when the step is built. A step's decisions are published only once it has settled (see `_publish`), so a decision made at the step itself, or at a parallel call's step still running, is not among them.
    """
    return tuple(_published.get(transcript(), {}).get(conversation, []))


def _publish(conversation: str, kept: list[HumanDecision]) -> None:
    """Add a settled step's `human()` decisions to its conversation's human decisions.

    Called after the step's sentinel span ends, so a supersession has already withdrawn any decision that did not take effect, and a parallel step built before then never saw one that might yet be.
    """
    if kept:
        conversations = _published.setdefault(transcript(), {})
        conversations.setdefault(conversation, []).extend(kept)


# the `human()` decisions of each conversation's settled steps, oldest first
_published: "WeakKeyDictionary[Transcript, dict[str, list[HumanDecision]]]" = (
    WeakKeyDictionary()
)


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
        return transcript().history.find_last(_produced_by(message_id))
    except TranscriptHistoryUnavailableError:
        return None
    except Exception as ex:
        raise SentinelFailure(ex) from ex


def _produced_by(message_id: str) -> Callable[[Event], TypeGuard[ModelEvent]]:
    def produced(event: Event) -> TypeGuard[ModelEvent]:
        return (
            isinstance(event, ModelEvent)
            and event.role != "monitor"
            and not event.pending
            and bool(event.output.choices)
            and event.output.choices[0].message.id == message_id
        )

    return produced


class _HostNative:
    def __init__(self, eval: EvalContext | None) -> None:
        self.eval = eval

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

    async def ask_human(
        self,
        step: Step,
        escalations: Escalations,
        choices: Sequence[str],
    ) -> HumanAnswer:
        if isinstance(step, BeforeGenerate):
            raise NotImplementedError(
                f"inspect_ai cannot ask a person at the {_stage(step)} stage; "
                "its human approval surfaces show tool calls and assistant turns."
            )
        if "modify" in choices:
            raise NotImplementedError(
                "human() cannot offer 'modify' in inspect_ai, since its human "
                "approval surfaces cannot edit a tool call yet."
            )
        if isinstance(step, AfterGenerate) and "reject" in choices:
            raise ValueError(
                f"human() cannot offer 'reject' at the {_stage(step)} stage, "
                "where a turn can only proceed or be terminated."
            )
        offered: list[ApprovalDecision] = []
        for choice in choices:
            if choice not in _HUMAN_CHOICES:
                raise ValueError(
                    f"human() cannot offer {choice!r}; the choices are "
                    f"{', '.join(repr(c) for c in _HUMAN_CHOICES)}."
                )
            offered.append(cast(ApprovalDecision, choice))
        # the approval surfaces show the conversation; a step with no agent's
        # list shows what the model saw instead, and nothing when that is
        # unknown too
        if step.agent_messages is not None:
            conversation = step.agent_messages
        elif step.input is not None:
            conversation = step.input
        else:
            conversation = []
        approve = human_approver(choices=offered)
        if isinstance(step, AfterGenerate):
            approval = await _ask_about_turn(
                approve, step, escalations, offered, conversation
            )
        else:
            approval = await approve(
                step.message, step.call, _human_view(step, escalations), conversation
            )
        if approval.decision in offered:
            return HumanAnswer(decision=approval.decision, reason=approval.explanation)
        # the reason says the person did not choose, since later steps read
        # this decision in human_decisions
        return HumanAnswer(
            decision="reject" if "reject" in offered else "terminate",
            reason=(
                "The person closed the prompt without choosing; failing closed "
                f"(the surface answered {approval.decision}: {approval.explanation})."
            ),
        )


_HUMAN_CHOICES = ("approve", "reject", "terminate")


def _human_view(
    step: BeforeToolCall | AfterToolCall, escalations: Escalations
) -> ToolCallView:
    view = step.view
    if escalations:
        lines = _escalation_lines(escalations)
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


def _escalation_lines(escalations: Escalations) -> str:
    return escape_placeholders(
        "\n".join(
            f"- {e.name}: {e.report.explanation}"
            if e.report.explanation
            else f"- {e.name}"
            for e in escalations
        )
    )


async def _ask_about_turn(
    approve: Approver,
    step: AfterGenerate,
    escalations: Escalations,
    offered: list[ApprovalDecision],
    conversation: list[ChatMessage],
) -> Approval:
    # deferred: the ACP shim imports `acp.schema`, which only matters once a
    # person is asked
    from inspect_ai.approval._human.acp import finish_approval_card

    prompt = _turn_prompt(step, escalations)
    status: Literal["completed", "failed"] = "failed"
    try:
        approval = await approve(prompt.message, prompt.call, prompt.view, conversation)
        if approval.decision in offered:
            status = "completed"
        return approval
    finally:
        # no tool event completes the card the turn's prompt opened; a prompt
        # that ended without one of the choices failed
        finish_approval_card(prompt.call, prompt.view, status)


class _Prompt(NamedTuple):
    message: str
    call: ToolCall
    view: ToolCallView


def _turn_prompt(step: AfterGenerate, escalations: Escalations) -> _Prompt:
    """The assistant turn as one prompt for the human approval surfaces.

    The surfaces show one tool call, so the turn becomes a single view: the
    escalations, how many calls the turn makes, then each call. Two things
    keep a call from hiding, merging into or passing for another:

    - Markdown: a call's content is shown only inside a code block it cannot
      close (see `_call_markdown`), and everything outside the code blocks is
      written here, so the count says how many calls there are.
    - Characters that act rather than show (terminal escape sequences, which
      could move the cursor over another call's lines, bidi overrides, and
      zero-width and tag characters): everything the agent wrote in the view,
      the calls, the escalations quoting it and the title, goes through
      `display_safe`, which shows each as a marker, and the view says so when
      it did. So does the assistant text, which the panel and the console show
      above the view; an ACP client shows the turn's streamed text and
      reasoning instead, which the Inspect ACP TUI makes safe the same way,
      as `--display conversation` does for the turn it prints.

    What a call's own viewer makes of its arguments inside its code block is
    the viewer's; a call can still garble its own content there. Earlier
    tool output in the ACP TUI's stream and the conversation display is not
    made safe yet.

    The call handed to the surfaces stands for the whole turn, and its
    function is the turn's title, which carries the count too. Its id is its
    own, unlike any tool call's or another prompt's, since an ACP client opens
    a card under it; its empty arguments leave the view as rendered here.
    """
    safe = _Escaped()
    message = step.output.message if step.output.choices else None
    calls = (message.tool_calls if message else None) or []
    shown = [
        _call_markdown(call, index, len(calls), safe)
        for index, call in enumerate(calls, 1)
    ]
    tally = Counter(_one_line(call.function, safe) for call in calls)
    tools = ", ".join(
        function if count == 1 else f"{function} ×{count}"
        for function, count in tally.items()
    )
    text = safe(message.text) if message else ""
    blocks: list[str] = []
    if escalations:
        escalated = safe(_escalation_lines(escalations))
        blocks.append(f"**Escalated by**\n\n{fenced(escalated)}")
    count = f"**The turn makes {_calls(len(calls))}.**"
    if safe.escaped:
        count = f"{count}\n\n**{_ESCAPED_NOTICE}**"
    blocks.append(count)
    blocks.extend(shown)
    turn = ToolCall(
        id=f"turn_{shortuuid()}",
        function=f"Assistant turn: {_calls(len(calls))}"
        + (f" ({tools})" if tools else ""),
        arguments={},
    )
    view = ToolCallView(
        call=ToolCallContent(format="markdown", content="\n\n---\n\n".join(blocks))
    )
    return _Prompt(text, turn, view)


_ESCAPED_NOTICE = (
    "This turn contains hidden or control characters, "
    f"shown as {MARKER_OPEN}U+…{MARKER_CLOSE}."
)


class _Escaped:
    """`display_safe` for one turn, remembering whether it escaped anything."""

    def __init__(self) -> None:
        self.escaped = False

    def __call__(self, text: str) -> str:
        shown = display_safe(text)
        self.escaped = self.escaped or shown.escaped
        return shown.text


def _calls(count: int) -> str:
    if count == 0:
        return "no tool calls"
    return "1 tool call" if count == 1 else f"{count} tool calls"


def _call_markdown(call: ToolCall, index: int, count: int, safe: _Escaped) -> str:
    """One call: a header written here, then its content as a code block.

    The content is what the transcript shows (`ToolCall.view`, which
    `Model.generate` sets from the tool's viewer, or the default rendering),
    with the call's placeholders filled in. Viewers interpolate arguments into
    markdown unescaped, so an argument could close the viewer's code fence and
    open an HTML comment that swallows the calls after it. A viewer's single
    code block keeps its language and is fenced again by a fence longer than
    any backtick run in it; any other content is shown as source.
    """
    content = substitute_tool_call_content(
        call.view or cast(ToolCallContent, default_tool_call_viewer(call).call),
        call.arguments,
    )
    header = f"**Call {index} of {count}:** {_markdown_text(call.function, safe)}"
    if content.title and content.title != call.function:
        header = f"{header} ({_markdown_text(content.title, safe)})"
    block = _CODE_BLOCK.fullmatch(content.content)
    if content.format == "markdown" and block is not None:
        language, code = block.group("language").strip(), block.group("code")
    else:
        language = "markdown" if content.format == "markdown" else ""
        code = content.content
    return f"{header}\n\n{_code_block(safe(code), language)}"


# a viewer's single fenced code block, e.g. `code_viewer`'s and the default's
_CODE_BLOCK = re.compile(
    r"(?P<fence>`{3,})(?P<language>[\w+.-]*)\n(?P<code>.*)\n(?P=fence)[ \t]*\n?",
    re.DOTALL,
)


def _code_block(code: str, language: str) -> str:
    # deferred: the ACP shim imports `acp.schema`, which only matters once a
    # person is asked
    from inspect_ai.approval._human.acp import _safe_code_fence

    fence = _safe_code_fence(code)
    return f"{fence}{language}\n{code}\n{fence}"


def _markdown_text(text: str, safe: _Escaped) -> str:
    # one line of literal text: markdown punctuation escaped, so a function
    # name or viewer title cannot add structure
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~&])", r"\\\1", _one_line(text, safe))


def _one_line(text: str, safe: _Escaped) -> str:
    return " ".join(safe(text).split())


class _Recorder:
    def __init__(self, step_id: str) -> None:
        self._step_id = step_id
        # this step's human() decisions, published once it settles
        self.kept: list[HumanDecision] = []

    def record(
        self, context: Context, factory: str, step: Step, reported: Reported[Report]
    ) -> None:
        report = reported.report
        if isinstance(report, Observation):
            _emit(
                context,
                factory,
                step,
                self._step_id,
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
                context,
                factory,
                step,
                self._step_id,
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
        _emit(
            context,
            factory,
            step,
            self._step_id,
            "observation",
            "error",
            function=failed.function,
            error=f"{type(failed.error).__name__}: {failed.error}",
        )

    def cancelled(self, context: Context, factory: str, step: Step, name: str) -> None:
        _emit(
            context, factory, step, self._step_id, _factory_kind(factory), "cancelled"
        )

    def bypassed(self, context: Context, factory: str, step: Step, name: str) -> None:
        _emit(context, factory, step, self._step_id, "decision", "bypassed")

    def superseded(
        self,
        context: Context,
        factory: str,
        step: Step,
        reported: Reported[Decision],
    ) -> None:
        _emit_decision(
            context,
            factory,
            step,
            self._step_id,
            "superseded",
            reported.function,
            reported.report,
        )
        self.kept = [k for k in self.kept if not supersedes(context.path, reported, k)]


def _factory_kind(factory: str) -> _Kind:
    if registry_lookup("protocol", factory) is not None:
        return "decision"
    return "observation"


def _emit_decision(
    context: Context,
    factory: str,
    step: Step,
    step_id: str,
    status: SentinelStatus,
    function: str,
    decision: Decision,
) -> None:
    _emit(
        context,
        factory,
        step,
        step_id,
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
    step_id: str,
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
            step_id=step_id,
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
