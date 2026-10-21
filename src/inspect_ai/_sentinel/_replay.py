"""The log driver: a sample's steps rebuilt from its events, with the builders the live dispatcher uses (`_steps.py`)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from functools import partial
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from packaging.version import InvalidVersion, Version

from inspect_ai._util.content import Content
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.event._compaction import CompactionEvent
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._pool import _build_msg_index, condense_model_event_inputs
from inspect_ai.event._sentinel import SentinelEvent, SentinelStage
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.event._timeline import Timeline, TimelineEvent, TimelineSpan
from inspect_ai.event._tool import ToolEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.tool._tool_call import ToolCall, ToolCallView, default_tool_call_viewer
from inspect_ai.util._span import AGENT_SPAN_TYPE

from ._conversation import SpanConversations
from ._scope import is_agent_turn
from ._steps import (
    ConversationRecord,
    FoldInput,
    PoolView,
    Producer,
    after_generate,
    after_tool_call,
    before_generate,
    before_tool_call,
    content_key,
    producing_message_id,
)

if TYPE_CHECKING:
    from inspect_sentinel import HumanAnswer, HumanDecision, ReplayStep, Step

    from inspect_ai.log._log import EvalSpec


class EvalInfo(NamedTuple):
    """What the log driver reads from the log's header."""

    inspect_ai_version: str | None
    """The inspect_ai that wrote the log (`eval.packages["inspect_ai"]`): logs from before 0.3.31 do not record whether a tool's output was cut."""

    sentinel: bool
    """Whether the eval ran a sentinel (`eval.config.sentinel`): if it did, earlier `human()` decisions come from its `SentinelEvent`s, else from the `ApprovalEvent`s of human approvers."""

    @staticmethod
    def from_eval(eval: "EvalSpec") -> "EvalInfo":
        return EvalInfo(
            inspect_ai_version=eval.packages.get("inspect_ai"),
            sentinel=eval.config.sentinel is not None,
        )


class MalformedLogError(ValueError):
    """A log replay cannot read without guessing."""


def steps_from_events(
    messages: Sequence[ChatMessage],
    events: Sequence[Event],
    message_pool: Sequence[ChatMessage],
    *,
    sample_uuid: str,
    eval_info: EvalInfo,
    timeline: Timeline | None = None,
    human_approvers: Sequence[str] = (),
) -> list["ReplayStep"]:
    """The steps a sentinel was handed live, or would have been had it watched every stage, rebuilt from a sample's events.

    One pass reads the events in log order, and a second applies what changed each conversation's record (the inputs its agent turns sent, its outputs and tool results as the agent ran them, the `human()` decisions published) in that order, building each step at the point live built it. The work is linear in the log as stored: model inputs are read as ranges of the message pool, each pool row's content key is computed once, and steps hold views of each conversation's lists rather than copies.

    Args:
        messages: The sample's messages (`EvalSample.messages`).
        events: The sample's events, with model inputs condensed (`input_refs` into `message_pool`), as the log stores them; inputs given expanded are condensed first.
        message_pool: The sample's message pool (`EvalSample.events_data["messages"]`).
        sample_uuid: The sample's uuid: the conversation of calls made outside any agent span.
        eval_info: What the log's header says about the eval.
        timeline: A stored timeline whose spans define which conversation each event is in (such as Petri's `"target"`), in place of the span tree.
        human_approvers: The registry names of approvers that are people, whose `ApprovalEvent`s are `human_decisions` in a log from an eval that ran no sentinel.

    Returns:
        The steps, in the order they ran live.

    Raises:
        MalformedLogError: Two steps of one stage have one step id, or the span tree has a `parent_id` cycle.
        NotImplementedError: The log does not record where its model calls were made (`ModelEvent.origin`, written since inspect_ai PR #5990); turns from the timeline come later.
    """
    flat = _flatten(events)
    pool: list[ChatMessage] | Sequence[ChatMessage] = message_pool
    if any(isinstance(e, ModelEvent) and e.input_refs is None for e in flat):
        flat, pool = _condensed(flat, message_pool)
    try:
        return _Driver(
            messages, flat, pool, sample_uuid, eval_info, timeline, human_approvers
        ).steps()
    except ValueError as ex:
        if isinstance(ex, MalformedLogError):
            raise
        raise MalformedLogError(str(ex)) from ex


def _flatten(events: Sequence[Event]) -> list[Event]:
    # older logs nest a tool call's events inside its ToolEvent
    flat: list[Event] = []
    for event in events:
        flat.append(event)
        if isinstance(event, ToolEvent) and event.events:
            flat.extend(_flatten(event.events))
    return flat


def _condensed(
    events: list[Event], pool: Sequence[ChatMessage]
) -> tuple[list[Event], list[ChatMessage]]:
    rows = list(pool)
    condensed, _, entries = condense_model_event_inputs(
        events, len(rows), _build_msg_index(rows)
    )
    return condensed, [*rows, *(message for _, message in entries)]


class _PoolKeys:
    """Each pool row's content key, computed the first time it is needed."""

    def __init__(self, pool: Sequence[ChatMessage]) -> None:
        self.pool = pool
        self._keys: dict[int, str] = {}

    def key(self, row: int) -> str:
        key = self._keys.get(row)
        if key is None:
            key = self._keys[row] = content_key(self.pool[row])
        return key


class _PooledInput:
    """A logged model input for the fold: positions are pool rows, and a range equal to the previous input's is matched without reading its rows."""

    def __init__(self, view: PoolView, keys: _PoolKeys) -> None:
        self.view = view
        self._keys = keys

    def __len__(self) -> int:
        return len(self.view)

    def key(self, position: int) -> str:
        return self._keys.key(self.view.row(position))

    def message(self, position: int) -> ChatMessage:
        return self.view[position]

    def prefix(self, previous: FoldInput) -> int:
        assert isinstance(previous, _PooledInput)
        mine = list(self.view.refs)
        theirs = list(previous.view.refs)
        i = j = 0
        # rows left in the current range of each
        a_start, a_left = (mine[0][0], mine[0][1] - mine[0][0]) if mine else (0, 0)
        b_start, b_left = (
            (theirs[0][0], theirs[0][1] - theirs[0][0]) if theirs else (0, 0)
        )
        matched = 0
        while i < len(mine) and j < len(theirs):
            if a_left <= 0:
                i += 1
                if i < len(mine):
                    a_start, a_left = mine[i][0], mine[i][1] - mine[i][0]
                continue
            if b_left <= 0:
                j += 1
                if j < len(theirs):
                    b_start, b_left = theirs[j][0], theirs[j][1] - theirs[j][0]
                continue
            if a_start == b_start:
                step = min(a_left, b_left)
            elif self._keys.key(a_start) == self._keys.key(b_start):
                step = 1
            else:
                break
            matched += step
            a_start, a_left = a_start + step, a_left - step
            b_start, b_left = b_start + step, b_left - step
        return matched


@dataclass
class _Generate:
    conversation: str
    attempts: list[tuple[int, ModelEvent]]
    # the index of the conversation's previous agent-turn model event
    previous: int
    seq: int
    # model_input sentinel spans of the conversation since its previous turn
    candidates: list[str]


@dataclass
class _Call:
    index: int
    event: ToolEvent
    conversation: str
    assistant: ChatMessageAssistant | None
    proposal: ToolCall | None
    producer: ModelEvent | None
    approval: ApprovalEvent | None
    seq: int
    # the call's `tool` span, which call_tool opens just before recording the event
    tool_span: str | None


@dataclass
class _Batch:
    conversation: str
    assistant: ChatMessageAssistant | None
    calls: list[_Call] = field(default_factory=list)
    # the conversation's next agent turn, which closed the batch
    next_turn: ModelEvent | None = None
    # reserved when the batch closes: after its own steps, before the next turn's
    seq: int = 0


class _Action(NamedTuple):
    position: int
    # at one position: effects and steps before the event there (0, 1), then the event's own effect (2)
    phase: int
    seq: int
    run: Callable[[], None]


_HUMAN_FACTORY = "inspect_sentinel/human"


class _Driver:
    def __init__(
        self,
        messages: Sequence[ChatMessage],
        events: list[Event],
        pool: Sequence[ChatMessage],
        sample_uuid: str,
        eval_info: EvalInfo,
        timeline: Timeline | None,
        human_approvers: Sequence[str],
    ) -> None:
        self.messages = messages
        self.events = events
        self.pool = pool
        self.keys = _PoolKeys(pool)
        self.eval_info = eval_info
        self.human_approvers = set(human_approvers)
        self.spans = SpanConversations(sample_uuid)
        self.timeline = _timeline_conversations(timeline) if timeline else None
        self.begins: dict[str, tuple[int, SpanBeginEvent]] = {}
        self.ends: dict[str, int] = {}
        self.sentinel_span_of: dict[str, str | None] = {}
        # (stage, step id) -> the sentinel span of the step
        self.step_spans: dict[tuple[SentinelStage, str], str] = {}
        self.span_events: dict[str, list[SentinelEvent]] = {}
        self.records: dict[str, ConversationRecord] = {}
        self.compactions: dict[str, int] = {}
        self.actions: list[_Action] = []
        self.seq = 0
        self.built: list["ReplayStep"] = []
        self.ids: set[tuple[str, str]] = set()
        self.span_steps: dict[str, tuple["Step", str]] = {}
        self._assistants: dict[str, ChatMessageAssistant] | None = None
        self._messages_by_id: dict[str, ChatMessage] | None = None

    # ---- the first pass: read the events in log order

    def steps(self) -> list["ReplayStep"]:
        generates: list[_Generate] = []
        open_generates: dict[str | None, _Generate] = {}
        last_turn: dict[str, int] = {}
        candidates: dict[str, list[str]] = {}
        produced: dict[str, tuple[ChatMessageAssistant, ModelEvent]] = {}
        approvals: dict[str, ApprovalEvent] = {}
        batches: dict[str, _Batch] = {}
        closed: list[_Batch] = []
        calls: list[_Call] = []

        for index, event in enumerate(self.events):
            if isinstance(event, SpanBeginEvent):
                self.begins[event.id] = (index, event)
                self.spans.add(event)
            elif isinstance(event, SpanEndEvent):
                self.ends[event.id] = index
            elif isinstance(event, SentinelEvent):
                self._sentinel_event(event, candidates)
            elif isinstance(event, ModelEvent):
                if self._in_sentinel_span(event.span_id):
                    continue
                if event.origin is None:
                    raise NotImplementedError(
                        "This log does not record where its model calls were made "
                        "(ModelEvent.origin), so replay cannot tell which calls were "
                        "agent turns; replaying such logs from their timeline is not "
                        "built yet."
                    )
                message_id = producing_message_id(event)
                if message_id is not None:
                    message = event.output.choices[0].message
                    for tool_call in message.tool_calls or []:
                        produced[tool_call.id] = (message, event)
                if not is_agent_turn(event.origin):
                    continue
                conversation = self._conversation(event)
                self._at(index, 2, partial(self._fold, conversation, event))
                group = open_generates.get(event.span_id)
                if (
                    group is not None
                    and group.attempts[-1][1].error is not None
                    and group.attempts[-1][1].input_refs == event.input_refs
                ):
                    group.attempts.append((index, event))
                else:
                    batch = batches.pop(conversation, None)
                    if batch is not None:
                        batch.next_turn = event
                        batch.seq = self._next_seq()
                        closed.append(batch)
                    group = _Generate(
                        conversation,
                        [(index, event)],
                        last_turn.get(conversation, -1),
                        self._next_seq(2),
                        candidates.pop(conversation, []),
                    )
                    generates.append(group)
                    open_generates[event.span_id] = group
                last_turn[conversation] = index
            elif isinstance(event, ApprovalEvent):
                approvals[event.call.id] = event
            elif isinstance(event, CompactionEvent):
                conversation = self._conversation(event)
                self._at(index, 2, partial(self._count_compaction, conversation))
            elif isinstance(event, ToolEvent):
                if self._in_sentinel_span(event.span_id):
                    continue
                found = produced.get(event.id)
                if found is not None:
                    assistant: ChatMessageAssistant | None = found[0]
                    producer: ModelEvent | None = found[1]
                else:
                    assistant, producer = self._assistant(event.id), None
                if producer is not None and not is_agent_turn(producer.origin):
                    continue
                conversation = (
                    self._conversation(producer)
                    if producer is not None
                    else self._conversation(event)
                )
                proposal = next(
                    (c for c in (assistant.tool_calls or []) if c.id == event.id)
                    if assistant is not None
                    else iter(()),
                    None,
                )
                entry = _Call(
                    index,
                    event,
                    conversation,
                    assistant,
                    proposal,
                    producer,
                    approvals.pop(event.id, None),
                    self._next_seq(2),
                    self._tool_span(index, event),
                )
                calls.append(entry)
                batch = batches.get(conversation)
                if batch is None or batch.assistant is not assistant:
                    if batch is not None:
                        batch.seq = self._next_seq()
                        closed.append(batch)
                    batch = batches[conversation] = _Batch(conversation, assistant)
                batch.calls.append(entry)
        for batch in batches.values():
            batch.seq = self._next_seq()
            closed.append(batch)

        for group in generates:
            self._generate(group)
        for entry in calls:
            self._tool_call(entry)
        for batch in closed:
            self._batch(batch)

        # the second pass: in log order, each step at its cut
        for action in sorted(self.actions, key=lambda a: (a.position, a.phase, a.seq)):
            action.run()
        return self.built

    def _sentinel_event(
        self, event: SentinelEvent, candidates: dict[str, list[str]]
    ) -> None:
        span = self._sentinel_span(event.span_id)
        if span is None:
            return
        events = self.span_events.setdefault(span, [])
        events.append(event)
        if len(events) > 1:
            return
        key = (event.stage, event.step_id)
        other = self.step_spans.get(key)
        if other is not None and other != span:
            raise MalformedLogError(
                f"Two {event.stage} steps have the step id {event.step_id!r}."
            )
        self.step_spans[key] = span
        if event.stage == "model_input":
            candidates.setdefault(event.conversation, []).append(span)

    def _sentinel_span(self, span_id: str | None) -> str | None:
        walked: list[str] = []
        found: str | None = None
        while span_id is not None:
            if span_id in self.sentinel_span_of:
                found = self.sentinel_span_of[span_id]
                break
            begin = self.begins.get(span_id)
            if begin is None:
                break
            if span_id in walked:
                raise MalformedLogError(
                    f"The span tree has a parent_id cycle at {span_id}."
                )
            walked.append(span_id)
            if begin[1].type == "sentinel":
                found = span_id
                break
            span_id = begin[1].parent_id
        for walked_id in walked:
            self.sentinel_span_of[walked_id] = found
        return found

    def _tool_span(self, index: int, event: ToolEvent) -> str | None:
        previous = self.events[index - 1] if index > 0 else None
        if (
            isinstance(previous, SpanBeginEvent)
            and previous.type == "tool"
            and previous.name == event.function
        ):
            return previous.id
        return None

    def _in_sentinel_span(self, span_id: str | None) -> bool:
        return self._sentinel_span(span_id) is not None

    def _conversation(self, event: Event) -> str:
        if self.timeline is not None:
            found = self.timeline.get(_event_key(event))
            if found is not None:
                return found
        return self.spans.conversation(event.span_id)

    def _next_seq(self, count: int = 1) -> int:
        seq = self.seq
        self.seq += count
        return seq

    def _at(self, position: int, phase: int, run: Callable[[], None]) -> None:
        self.actions.append(_Action(position, phase, self._next_seq(), run))

    def _at_seq(
        self, position: int, phase: int, seq: int, run: Callable[[], None]
    ) -> None:
        self.actions.append(_Action(position, phase, seq, run))

    def _record(self, conversation: str) -> ConversationRecord:
        record = self.records.get(conversation)
        if record is None:
            record = self.records[conversation] = ConversationRecord()
        return record

    # ---- what each step is made from

    def _generate(self, group: _Generate) -> None:
        first_index, first = group.attempts[0]
        last_index, last = group.attempts[-1]
        conversation = group.conversation

        before_span = self.step_spans.get(("model_input", first.uuid or ""))
        before_id = first.uuid
        if before_span is None and len(group.candidates) == 1:
            # a log from before generate ids: the only model_input step of
            # the conversation since its previous turn
            candidate = group.candidates[0]
            if self.begins[candidate][0] > group.previous:
                before_span = candidate
                before_id = self.span_events[candidate][0].step_id
        if before_id is None:
            before_id = f"{conversation}:{first_index}"
        input = self._input(first)

        def build_before() -> None:
            record = self._record(conversation)
            record.open(list(input), sent=True)
            step = before_generate(
                model=first.model,
                conversation=conversation,
                input=input,
                tools=first.tools,
                tool_choice=first.tool_choice,
                config=first.config,
                record=record,
            )
            self._built(before_id, "model_input", step, before_span)

        self._at_seq(self._cut(before_span, first_index), 1, group.seq, build_before)
        self._settle_at_end(before_span)

        refused = (
            bool(last.config.fail_on_refusal)
            and not last.output.empty
            and last.output.stop_reason == "content_filter"
        )
        if last.error is not None or last.pending or refused:
            return
        after_span = self.step_spans.get(("model_output", first.uuid or ""))
        after_id = before_id
        if after_span is None and last.output.choices:
            # a log from before generate ids: model_output steps were
            # identified by the output message's id
            message_id = last.output.message.id or ""
            after_span = self.step_spans.get(("model_output", message_id))
            if after_span is not None:
                after_id = message_id

        def build_after() -> None:
            record = self._record(conversation)
            step = after_generate(
                model=first.model,
                conversation=conversation,
                input=input,
                tools=first.tools,
                tool_choice=first.tool_choice,
                config=first.config,
                output=last.output,
                record=record,
            )
            self._built(after_id, "model_output", step, after_span)
            if last.output.choices:
                record.ran([last.output.message])

        self._at_seq(
            self._cut(after_span, last_index + 1), 1, group.seq + 1, build_after
        )
        self._settle_at_end(after_span)

    def _tool_call(self, call: _Call) -> None:
        event = call.event
        before_span = self.step_spans.get(("tool_call", event.id))
        after_span = self.step_spans.get(("tool_result", event.id))
        tool_span = call.tool_span
        proposal = call.proposal
        if proposal is None or call.assistant is None:
            return
        approval = call.approval
        approver_modified = (
            approval.modified
            if approval is not None
            and approval.decision == "modify"
            and approval.modified is not None
            else None
        )
        checked = before_span is not None or (
            tool_span is not None
            and proposal.parse_error is None
            and (
                call.producer is None
                or any(tool.name == proposal.function for tool in call.producer.tools)
            )
            and (
                approval is None
                or approval.decision == "approve"
                or (
                    approver_modified is not None
                    and approver_modified.function == proposal.function
                )
            )
        )
        if not checked:
            return
        ran = after_span is not None or (
            (event.error is None or event.error.type not in ("parsing", "approval"))
            and not event.failed
            and not event.pending
        )

        modify = self._sentinel_modify(before_span, event)
        approved = approver_modified or proposal
        if modify is not None:
            before_call = approved
        else:
            before_call = replace(approved, arguments=event.arguments)
        if approval is not None and approval.view is not None and not approver_modified:
            before_view = approval.view
        elif modify is None:
            before_view = ToolCallView(call=event.view or _default_view(before_call))
        else:
            before_view = ToolCallView()
        producer = self._producer(call.producer)
        assistant = call.assistant
        conversation = call.conversation
        assistant_id = assistant.id or ""

        def build_before() -> None:
            step = before_tool_call(
                conversation=conversation,
                message=assistant.text,
                message_id=assistant_id,
                call=before_call,
                view=before_view,
                producer=producer,
                through=assistant,
                record=self._record(conversation),
            )
            self._built(event.id, "tool_call", step, before_span)

        before_cut = self._cut(
            before_span, self.begins[tool_span][0] if tool_span else call.index
        )
        self._at_seq(before_cut, 1, call.seq, build_before)
        self._settle_at_end(before_span)
        if not self.eval_info.sentinel and approval is not None:
            self._approval_decision(call, approval)
        if not ran:
            return

        after_call = modify if modify is not None else before_call
        after_call = replace(
            after_call, id=event.id, function=event.function, arguments=event.arguments
        )
        truncated = self._truncated(event)
        result = self._result(event)

        def build_after() -> None:
            step = after_tool_call(
                conversation=conversation,
                message=assistant.text,
                message_id=assistant_id,
                call=after_call,
                view=ToolCallView(call=event.view or _default_view(after_call)),
                result=result,
                output=None,
                truncated=truncated,
                producer=producer,
                through=assistant,
                record=self._record(conversation),
            )
            self._built(event.id, "tool_result", step, after_span)

        end = self.ends.get(tool_span) if tool_span is not None else None
        after_cut = self._cut(after_span, (end if end is not None else call.index) + 1)
        self._at_seq(after_cut, 1, call.seq + 1, build_after)
        self._settle_at_end(after_span)

    def _batch(self, batch: _Batch) -> None:
        if batch.assistant is None:
            return
        last = 0
        for call in batch.calls:
            last = max(last, call.index + 1)
            span = call.tool_span
            if span is not None and span in self.ends:
                last = max(last, self.ends[span] + 1)
            after_span = self.step_spans.get(("tool_result", call.event.id))
            if after_span is not None and after_span in self.ends:
                last = max(last, self.ends[after_span] + 1)
        conversation = batch.conversation
        if any(call.event.failed or call.event.pending for call in batch.calls):
            # live never reaches the append when a batch raises
            return
        handoff = any(call.event.agent is not None for call in batch.calls)
        if handoff:
            joined = self._handoff_results(batch)
        else:
            by_id = {call.event.id: call for call in batch.calls}
            joined = [
                self._result(by_id[tool_call.id].event)
                for tool_call in batch.assistant.tool_calls or []
                if tool_call.id in by_id
            ]

        def join() -> None:
            record = self._record(conversation)
            if joined is None:
                record.lose_ran()
            else:
                record.ran(joined)

        self._at_seq(last, 1, batch.seq, join)

    # ---- effects of the second pass

    def _fold(self, conversation: str, event: ModelEvent) -> None:
        self._record(conversation).sent.record_input(
            _PooledInput(self._input(event), self.keys)
        )

    def _count_compaction(self, conversation: str) -> None:
        self.compactions[conversation] = self.compactions.get(conversation, 0) + 1

    def _built(
        self,
        step_id: str,
        stage: SentinelStage,
        step: "Step",
        span: str | None,
    ) -> None:
        from inspect_sentinel import ReplayStep

        if (stage, step_id) in self.ids:
            raise MalformedLogError(f"Two {stage} steps have the step id {step_id!r}.")
        self.ids.add((stage, step_id))
        answers: dict[str, "HumanAnswer"] = {}
        if span is not None:
            answers = self._recorded_answers(span)
            self.span_steps[span] = (step, step_id)
        self.built.append(
            ReplayStep(
                id=step_id,
                stage=stage,
                step=step,
                segment=(step.conversation, self.compactions.get(step.conversation, 0)),
                recorded_answers=answers,
            )
        )

    def _settle_at_end(self, span: str | None) -> None:
        """Publish the `human()` decisions of the step checked in `span` when the span ends, as live publishes them once the step settles."""
        if span is None or span not in self.ends:
            return
        self._at(self.ends[span], 2, lambda: self._settle(span))

    def _settle(self, span: str) -> None:
        from inspect_sentinel._integration import kept_human_decision, supersedes

        built = self.span_steps.get(span)
        if built is None:
            return
        step, step_id = built
        kept: list["HumanDecision"] = []
        for event in self.span_events.get(span, []):
            if event.kind != "decision" or event.action is None:
                continue
            reported = _reported(event)
            if event.status == "reported":
                decision = kept_human_decision(event.factory, step, step_id, reported)
                if decision is not None:
                    kept.append(decision)
            elif event.status == "superseded":
                kept = [k for k in kept if not supersedes(event.path, reported, k)]
        if kept:
            self._record(step.conversation).publish(kept)

    # ---- helpers

    def _cut(self, span: str | None, anchor: int) -> int:
        return self.begins[span][0] if span is not None else anchor

    def _input(self, event: ModelEvent) -> PoolView:
        return PoolView(self.pool, event.input_refs or [])

    def _producer(self, event: ModelEvent | None) -> Producer | None:
        if event is None:
            return None
        return Producer(self._input(event), event.tools, event.tool_choice)

    def _truncated(self, event: ToolEvent) -> Any:
        from inspect_sentinel import Truncation

        if event.truncated is not None:
            return Truncation(*event.truncated)
        return False if _records_truncation(self.eval_info.inspect_ai_version) else None

    def _result(self, event: ToolEvent) -> ChatMessageTool:
        if event.message_id is not None:
            found = self._message_by_id(event.message_id)
            if isinstance(found, ChatMessageTool):
                return found
        return ChatMessageTool(
            content=cast(str | list[Content], event.result),
            tool_call_id=event.id,
            function=event.function,
            error=event.error,
        )

    def _message_by_id(self, message_id: str) -> ChatMessage | None:
        if self._messages_by_id is None:
            found: dict[str, ChatMessage] = {}
            for message in self.pool:
                if message.id is not None:
                    found.setdefault(message.id, message)
            for message in self.messages:
                if message.id is not None:
                    found.setdefault(message.id, message)
            self._messages_by_id = found
        return self._messages_by_id.get(message_id)

    def _assistant(self, call_id: str) -> ChatMessageAssistant | None:
        if self._assistants is None:
            found: dict[str, ChatMessageAssistant] = {}
            for message in [*self.pool, *self.messages]:
                if isinstance(message, ChatMessageAssistant):
                    for tool_call in message.tool_calls or []:
                        found[tool_call.id] = message
            self._assistants = found
        return self._assistants.get(call_id)

    def _handoff_results(self, batch: _Batch) -> list[ChatMessage] | None:
        assert batch.assistant is not None
        source: Sequence[ChatMessage] = (
            self._input(batch.next_turn)
            if batch.next_turn is not None
            else self.messages
        )
        for position in range(len(source) - 1, -1, -1):
            if source[position].id == batch.assistant.id:
                return list(source[position + 1 :])
        return None

    def _sentinel_modify(self, span: str | None, event: ToolEvent) -> ToolCall | None:
        if span is None:
            return None
        for recorded in self.span_events.get(span, []):
            if (
                recorded.status == "reported"
                and recorded.kind == "decision"
                and recorded.action == "modify"
                and recorded.modified is not None
                and recorded.modified.arguments == event.arguments
            ):
                return recorded.modified
        return None

    def _recorded_answers(self, span: str) -> dict[str, "HumanAnswer"]:
        from inspect_sentinel import HumanAnswer

        return {
            event.path: HumanAnswer(
                decision="approve" if event.action == "proceed" else event.action,
                reason=event.explanation,
                modified=event.modified,
            )
            for event in self.span_events.get(span, [])
            if event.factory == _HUMAN_FACTORY
            and event.kind == "decision"
            and event.status == "reported"
            and event.action is not None
        }

    def _approval_decision(self, call: _Call, approval: ApprovalEvent) -> None:
        if approval.approver not in self.human_approvers:
            return
        decided = _approval_report(approval)
        if decided is None:
            return
        from inspect_sentinel import HumanDecision

        decision = HumanDecision(
            stage="tool_call",
            step_id=call.event.id,
            call_ids=(call.event.id,),
            decided=decided,
        )
        span = call.tool_span
        end = self.ends.get(span) if span is not None else None
        conversation = call.conversation
        self._at(
            (end if end is not None else call.index) + 1,
            0,
            lambda: self._record(conversation).publish([decision]),
        )


def _reported(event: SentinelEvent) -> Any:
    """The report a `SentinelEvent` recorded, as the runner handed it to the recorder."""
    from inspect_sentinel import Decision, Reported

    assert event.action is not None
    name = (
        event.path.rsplit("/", 1)[-1]
        if event.path
        else event.factory.rsplit("/", 1)[-1]
    )
    return Reported(
        name=name,
        path=event.path,
        report=Decision(
            action=event.action,
            audit=event.audit,
            modified=event.modified,
            explanation=event.explanation,
            references=list(event.references),
            message=event.message,
            metadata=event.metadata,
        ),
        function=event.function or "",
    )


def _approval_report(approval: ApprovalEvent) -> Any:
    """A person's approval as the `human()` decision it stands for; None for an escalate, which decides nothing."""
    from inspect_sentinel import Decision, Reported

    if approval.decision == "escalate":
        return None
    explanation = approval.explanation
    if approval.decision == "approve":
        decision = Decision(action="proceed", explanation=explanation)
    elif approval.decision == "reject":
        decision = Decision(
            action="reject", explanation=explanation, message=explanation
        )
    elif approval.decision == "terminate":
        decision = Decision(action="terminate", explanation=explanation)
    else:
        decision = Decision(
            action="modify", explanation=explanation, modified=approval.modified
        )
    return Reported(
        name=approval.approver,
        path=approval.approver,
        report=decision,
        function=approval.approver,
    )


def _default_view(call: ToolCall) -> Any:
    return default_tool_call_viewer(call).call


def _records_truncation(version: str | None) -> bool:
    # ToolEvent.truncated exists since inspect_ai 0.3.31 (max_tool_output)
    if version is None:
        return False
    try:
        return Version(version) >= Version("0.3.31")
    except InvalidVersion:
        return True


def _event_key(event: Event) -> object:
    return event.uuid if event.uuid is not None else id(event)


def _timeline_conversations(timeline: Timeline) -> dict[object, str]:
    """The conversation of each event a stored timeline holds: its innermost agent span or branch, else the root."""
    conversations: dict[object, str] = {}

    def walk(span: TimelineSpan, conversation: str) -> None:
        for item in span.content:
            if isinstance(item, TimelineEvent):
                conversations[_event_key(item.event)] = conversation
            else:
                walk(
                    item,
                    item.id if item.span_type == AGENT_SPAN_TYPE else conversation,
                )
        for branch in span.branches:
            walk(branch, branch.id)

    walk(timeline.root, timeline.root.id)
    return conversations
