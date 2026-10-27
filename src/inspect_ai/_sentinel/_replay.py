"""The log driver: a sample's steps rebuilt from its events, with the builders the live dispatcher uses (`_steps.py`)."""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from functools import partial
from itertools import accumulate
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from inspect_ai._util.content import Content
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.event._compaction import CompactionEvent
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._pool import _build_msg_index, condense_model_event_inputs
from inspect_ai.event._sentinel import SentinelEvent, SentinelStage
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.event._step import StepEvent
from inspect_ai.event._timeline import (
    Timeline,
    TimelineEvent,
    TimelineSpan,
    _timeline_build,
)
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
    MalformedLogError,
    PoolView,
    Producer,
    after_generate,
    after_tool_call,
    before_generate,
    before_tool_call,
    content_key,
    producing_message_id,
    view,
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


def steps_from_events(
    messages: Sequence[ChatMessage],
    events: Sequence[Event],
    message_pool: Sequence[ChatMessage],
    *,
    sample_uuid: str,
    eval_info: EvalInfo | None,
    timeline: Timeline | None = None,
    human_approvers: Sequence[str] = (),
) -> list["ReplayStep"]:
    """The steps a sentinel was handed live, or would have been had it watched every stage, rebuilt from a sample's events.

    One pass reads the events in log order, and a second applies what changed each conversation's record (the inputs its agent turns sent, the `human()` decisions published) in that order, building each step at the point live built it. The work is linear in the log as stored: model inputs are read as ranges of the message pool, each pool row's content key is computed once, and steps hold views of each conversation's lists rather than copies.

    Every step's `agent_messages` is None: the log does not record the agent's own messages, and model input can hold messages the agent kept out of them.

    A log that does not record where a model call was made (`ModelEvent.origin`, written since inspect_ai PR #5990), an older Inspect log or a transcript imported from another source, has its turns inferred: a call made in the scorers' span (in a log from before spans, between a scorer's `StepEvent`s) is a scorer's, whatever tool or agent span holds it (live, the scorers' scope is final); one in a tool's span (or nested in its `ToolEvent`) a tool's, and one in the init span setup's; of the rest, those the timeline shows as utility (`timeline_build`'s prompt and continuity rules) are not turns, and the others are. A final scope no span records reads as the region holding it: a `model_origin()` region, `score()` called by a solver or a tool, an approver's model call; where the timeline does not show such a call as utility, its call is a turn (or, in a tool, its calls are checked), as live it was not.

    A transcript imported from another source (`eval_info` is `None`) has its tool steps from the sample's messages alone, as sentinel's messages projection (`steps_from_messages`) takes them: each call of each assistant message, in order, a `tool_call` step, and a `tool_result` step holding the first tool message with the call's id after that assistant message, none when there is none; step ids, calls, views and results as the projection's, with no input or tools. An importer takes the messages from one model call and adds its output (Scout's Logfire importer the call with the longest input, its LangSmith importer the last), which can be a nested agent's; so among the turns whose output is one of the messages (by id, or by content without the model's name, as LangSmith copies outputs), the latest wins. The steps are in that turn's conversation, with its record; with no such turn, in that of the turn with the longest input whose last message is one of the messages (of those, the latest), else of the conversation with the fewest agent spans enclosing it. Its `ToolEvent`s and model calls do not decide which tool steps there are or what answers them, only where they go among that conversation's turns, which decides their order and the record they are built with (`history`, `human_decisions`, segment): a message's steps follow the `model_output` step of the latest turn whose output is the message, else of the turn before the first turn whose input is longer than the message's position in the messages (the turn that made it, where the messages extend each turn's input), else they precede the first turn. So a call no message holds (a sub-agent's, or one in a turn the messages dropped) has no tool steps, as in the projection.

    Args:
        messages: The sample's messages (`EvalSample.messages`).
        events: The sample's events, with model inputs condensed (`input_refs` into `message_pool`), as the log stores them; inputs given expanded are condensed first. Attachments must be resolved (`resolve_attachments`), or monitors are handed `attachment://` references.
        message_pool: The sample's message pool (`EvalSample.events_data["messages"]`).
        sample_uuid: The sample's uuid: the conversation of calls made outside any agent span.
        eval_info: What the log's header says about the eval (`EvalInfo.from_eval`), or `None` for a transcript imported from another source, which has no header.
        timeline: A stored timeline whose spans define which conversation each event is in (such as Petri's `"target"`), in place of the span tree; a log without origins has its turns inferred within those conversations, its events matched to the stored timeline's by UUID.
        human_approvers: The registry names of approvers that are people, whose `ApprovalEvent`s are `human_decisions` in a log from an eval that ran no sentinel.

    Returns:
        The steps, in the order they ran live.

    Raises:
        MalformedLogError: Two steps of one stage have one step id (other than an imported transcript's tool steps, which keep the ids its messages give them), the span tree has a `parent_id` cycle, or a model input names rows outside the message pool.
        NotImplementedError: A sentinel checked a model_input step whose model call was not made (a sentinel ended the sample there or failed, or a token or cost limit or a cancellation stopped the call before it was recorded), whose input the log does not record.
    """
    flat, nested = _flatten(events)
    pool: list[ChatMessage] | Sequence[ChatMessage] = message_pool
    if any(isinstance(e, ModelEvent) and e.input_refs is None for e in flat):
        flat, pool = _condensed(flat, message_pool)
    return _Driver(
        messages, flat, nested, pool, sample_uuid, eval_info, timeline, human_approvers
    ).steps()


def _flatten(events: Sequence[Event]) -> tuple[list[Event], list[bool]]:
    """The events with those older logs nest inside a tool call's `ToolEvent` after it, and whether each was nested."""
    flat: list[Event] = []
    nested: list[bool] = []

    def walk(events: Sequence[Event], inside: bool) -> None:
        for event in events:
            flat.append(event)
            nested.append(inside)
            if isinstance(event, ToolEvent) and event.events:
                walk(event.events, True)

    walk(events, False)
    return flat, nested


def _condensed(
    events: list[Event], pool: Sequence[ChatMessage]
) -> tuple[list[Event], list[ChatMessage]]:
    rows = list(pool)
    condensed, _, entries = condense_model_event_inputs(
        events, len(rows), _build_msg_index(rows)
    )
    return condensed, [*rows, *(message for _, message in entries)]


class _PoolKeys:
    """Each pool row's content, as a canonical row: the first row with the same content key. Every row is keyed once, the first time the fold needs any."""

    def __init__(self, pool: Sequence[ChatMessage]) -> None:
        self.pool = pool
        self._canonical: list[int] | None = None
        self._rows: dict[int, list[int]] = {}

    def canonical(self, row: int) -> int:
        if self._canonical is None:
            self._key_every_row()
        assert self._canonical is not None
        return self._canonical[row]

    def rows(self, canonical: int) -> list[int]:
        """The rows whose content is the canonical row's."""
        return self._rows[canonical]

    def _key_every_row(self) -> None:
        first: dict[str, int] = {}
        canonical: list[int] = []
        for row, message in enumerate(self.pool):
            found = first.setdefault(content_key(message), row)
            canonical.append(found)
            self._rows.setdefault(found, []).append(row)
        self._canonical = canonical


class _PooledInput:
    """A logged model input for the fold: positions are rows of the message pool, read as the ranges the log stores (`input_refs`).

    The alignment walks runs, not messages: where the input and the previous input continue through the same rows, the run is matched whole. A message the pointer does not match is looked up in an index of the previous input's ranges over pool rows, built once while it is the previous input. So the work per input is in its ranges and the messages it does not continue, not its length.
    """

    def __init__(self, view: PoolView, keys: _PoolKeys) -> None:
        self.view = view
        self._keys = keys
        # where its rows are, built the first time a lookup needs it: the
        # pool rows its ranges cover, cut into segments at every range's ends,
        # and for each segment the offsets (position - row) of the ranges
        # covering it, sorted
        self._points: list[int] | None = None
        self._covers: list[list[int]] = []
        self._held: tuple[list[int], list[int]] | None = None
        self._ends = [
            start + max(end - begin, 0)
            for start, (begin, end) in zip(view.starts, view.refs)
        ]

    def __len__(self) -> int:
        return len(self.view)

    def message(self, position: int) -> ChatMessage:
        return self.view[position]

    def new_positions(self, previous: FoldInput | None) -> Iterator[int]:
        if previous is None:
            yield from range(len(self))
            return
        assert isinstance(previous, _PooledInput)
        position, pointer = 0, 0
        while position < len(self):
            row = self.view.row(position)
            if pointer < len(previous):
                before = previous.view.row(pointer)
                if row == before:
                    # the same rows from here to the end of either range
                    run = min(self._left(position), previous._left(pointer))
                    position += run
                    pointer += run
                    continue
                if self._keys.canonical(row) == self._keys.canonical(before):
                    position += 1
                    pointer += 1
                    continue
            found = previous._find(self._keys.canonical(row), pointer)
            if found is None:
                yield position
                position += 1
            else:
                pointer = found

    def _left(self, position: int) -> int:
        """Positions left in the range holding `position`."""
        return self._ends[bisect_right(self.view.starts, position) - 1] - position

    def _find(self, canonical: int, at_least: int) -> int | None:
        """The first position at or after `at_least` holding the canonical row's content.

        The rows with that content that this input holds are looked up in the index of its ranges: the segment holding the row, then the first covering range whose position for the row is at or after `at_least`. They are found by walking whichever is shorter, the rows with that content or the row intervals this input covers, so a content stored under many rows (equal messages with different `metadata`) costs no more than this input's ranges.
        """
        if at_least >= len(self):
            return None
        points, covers, held = self._index()
        rows = self._keys.rows(canonical)
        best: int | None = None
        for row in rows if len(rows) <= len(held[0]) else _rows_within(rows, held):
            segment = bisect_right(points, row) - 1
            if segment < 0 or segment >= len(covers):
                continue
            offsets = covers[segment]
            found = bisect_left(offsets, at_least - row)
            if found < len(offsets):
                position = offsets[found] + row
                if best is None or position < best:
                    best = position
        return best

    def _index(
        self,
    ) -> tuple[list[int], list[list[int]], tuple[list[int], list[int]]]:
        # linear for non-overlapping inputs; nested overlapping pool ranges (an
        # input repeating runs of its own messages) are a known superlinear
        # case, pinned by
        # test_an_input_that_repeats_its_own_suffixes_costs_its_overlaps
        if self._points is None:
            ranges = [
                (begin, end, start - begin)
                for start, (begin, end) in zip(self.view.starts, self.view.refs)
                if begin < end
            ]
            points = sorted({p for begin, end, _ in ranges for p in (begin, end)})
            covers: list[list[int]] = [[] for _ in range(max(len(points) - 1, 0))]
            for begin, end, offset in ranges:
                for segment in range(
                    bisect_left(points, begin), bisect_left(points, end)
                ):
                    covers[segment].append(offset)
            # the row intervals covered, merged
            begins: list[int] = []
            ends: list[int] = []
            for segment, offsets in enumerate(covers):
                offsets.sort()
                if not offsets:
                    continue
                if ends and ends[-1] == points[segment]:
                    ends[-1] = points[segment + 1]
                else:
                    begins.append(points[segment])
                    ends.append(points[segment + 1])
            self._points, self._covers, self._held = points, covers, (begins, ends)
        assert self._held is not None
        return self._points, self._covers, self._held


def _rows_within(rows: list[int], held: tuple[list[int], list[int]]) -> Iterator[int]:
    """The rows (sorted) inside the intervals `held`."""
    for begin, end in zip(*held):
        at = bisect_left(rows, begin)
        while at < len(rows) and rows[at] < end:
            yield rows[at]
            at += 1


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


class _Action(NamedTuple):
    position: int
    # at one position: an imported transcript's tool steps placed before the
    # turn there (0), steps built before the event there (1), the event's own
    # effect (2), then steps built once the event has happened (3)
    phase: int
    seq: int
    run: Callable[[], None]


_HUMAN_FACTORY = "inspect_sentinel/human"

# the origins of regions that are not final, so the tool calls of a model call
# made there are checked live
_NON_FINAL = {"agent", "tool", "setup"}


class _Driver:
    def __init__(
        self,
        messages: Sequence[ChatMessage],
        events: list[Event],
        nested: list[bool],
        pool: Sequence[ChatMessage],
        sample_uuid: str,
        eval_info: EvalInfo | None,
        timeline: Timeline | None,
        human_approvers: Sequence[str],
    ) -> None:
        self.messages = messages
        self.events = events
        self.nested = nested
        self.pool = pool
        self.keys = _PoolKeys(pool)
        self.imported = eval_info is None
        self.eval_info = eval_info or EvalInfo(inspect_ai_version=None, sentinel=False)
        self.human_approvers = set(human_approvers)
        self.spans = SpanConversations(sample_uuid)
        self.timeline = _timeline_conversations(timeline) if timeline else None
        self.begins: dict[str, tuple[int, SpanBeginEvent]] = {}
        self.ends: dict[str, int] = {}
        self.sentinel_span_of: dict[str, str | None] = {}
        # (stage, step id) -> the sentinel span of the step
        self.step_spans: dict[tuple[SentinelStage, str], str] = {}
        self.span_events: dict[str, list[SentinelEvent]] = {}
        # the sentinel spans whose invocation raised or was cancelled
        self.failed: set[str] = set()
        self.records: dict[str, ConversationRecord] = {}
        self.compactions: dict[str, int] = {}
        self.actions: list[_Action] = []
        self.seq = 0
        self.built: list["ReplayStep"] = []
        self.ids: set[tuple[str, str]] = set()
        self.span_steps: dict[str, tuple["Step", str]] = {}
        # each model event's input view and producer, shared by its steps
        self._views: dict[int, PoolView] = {}
        self._producers: dict[int, Producer] = {}
        self._assistants: dict[str, tuple[ChatMessageAssistant, ToolCall]] | None = None
        self._messages_by_id: dict[str, ChatMessage] | None = None
        # the origins of model calls the log records none for, by id()
        self._inferred: dict[int, str] | None = None
        # the uuids of the model calls made outside sentinel spans
        self.calls_made: set[str | None] = set()
        # span id -> the innermost agent or tool span's type, and the phase
        # span ("init", "scorers") holding it
        self._regions: dict[str | None, tuple[str | None, str | None]] = {}
        self._span_begins: dict[str, SpanBeginEvent] | None = None
        # id() of the events in a scorer's StepEvents (logs from before spans)
        self._scored: set[int] | None = None

    # ---- the first pass: read the events in log order

    def steps(self) -> list["ReplayStep"]:
        _check_span_tree(self.events)
        generates: list[_Generate] = []
        # each span's generates whose last attempt errored, by input: a retry
        # joins the open generate with its own input
        open_generates: dict[
            tuple[str | None, tuple[tuple[int, int], ...]], _Generate
        ] = {}
        last_turn: dict[str, int] = {}
        candidates: dict[str, list[str]] = {}
        turn_ids: set[str | None] = set()
        # calls made whose origin is inferred, not as turns
        inferred_other: set[str | None] = set()
        produced: dict[str, tuple[ChatMessageAssistant, ModelEvent, ToolCall]] = {}
        approvals: dict[str, ApprovalEvent] = {}
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
                message_id = producing_message_id(event)
                if message_id is not None:
                    message = event.output.choices[0].message
                    for tool_call in message.tool_calls or []:
                        produced[tool_call.id] = (message, event, tool_call)
                if not is_agent_turn(self._origin(event)):
                    if event.origin is None:
                        inferred_other.add(event.uuid)
                    continue
                turn_ids.add(event.uuid)
                conversation = self._conversation(event)
                self._at(index, 2, partial(self._fold, conversation, event))
                attempt_key = (
                    event.span_id,
                    tuple((start, end) for start, end in event.input_refs or []),
                )
                group = open_generates.pop(attempt_key, None)
                if group is not None:
                    group.attempts.append((index, event))
                else:
                    group = _Generate(
                        conversation,
                        [(index, event)],
                        last_turn.get(conversation, -1),
                        self._next_seq(2),
                        candidates.pop(conversation, []),
                    )
                    generates.append(group)
                if event.error is not None:
                    open_generates[attempt_key] = group
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
                producer: ModelEvent | None = None
                assistant: ChatMessageAssistant | None
                proposal: ToolCall | None
                if found is not None:
                    assistant, producer, proposal = found
                else:
                    assistant, proposal = self._assistant(event.id)
                conversation = (
                    self._conversation(producer)
                    if producer is not None
                    else self._conversation(event)
                )
                entry = _Call(
                    index,
                    event,
                    conversation,
                    assistant,
                    proposal,
                    producer,
                    approvals.pop(event.id, None),
                    self._next_seq(3),
                    self._tool_span(index, event),
                )
                calls.append(entry)

        self.calls_made = turn_ids | inferred_other
        self._check_generated(candidates)
        for group in generates:
            self._generate(group)
        if self.imported:
            self._projected_tool_steps(generates)
        else:
            for entry in calls:
                self._tool_call(entry)

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
        if event.path == "" and event.status in ("error", "cancelled"):
            self.failed.add(span)
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

    def _check_generated(self, candidates: dict[str, list[str]]) -> None:
        # a model_input step without its model call (a sentinel ended the
        # sample there, or failed and the scaffold carried on, or a limit or
        # cancellation stopped the call): the input it was handed is not in
        # the log. A step whose call was made but whose inferred origin is not
        # a turn is where inference differs from what was recorded live; it
        # has no step, as the other calls inferred so
        inputs = [
            step_id for stage, step_id in self.step_spans if stage == "model_input"
        ]
        if any(step_id in self.calls_made for step_id in inputs):
            # the log identifies generates by id, so each step names its call
            orphans = [step_id for step_id in inputs if step_id not in self.calls_made]
        else:
            # an id from before generate ids names the last message of the
            # step's input, and the step goes with its conversation's next
            # turn; an id naming neither a call nor a message is a generate id
            # whose call was not made
            left = {
                self.span_events[span][0].step_id
                for spans in candidates.values()
                for span in spans
            }
            orphans = [
                step_id
                for step_id in inputs
                if step_id in left or not self._names_message(step_id)
            ]
        if orphans:
            raise NotImplementedError(
                f"The model_input step {orphans[0]!r} was checked, but its model "
                "call was not made (a sentinel ended the sample there or failed, or "
                "a limit or cancellation stopped the call before it was recorded): "
                "the log does not record the input the step was handed, so "
                "replay cannot rebuild it."
            )

    def _names_message(self, step_id: str) -> bool:
        # the same input checked again had ":<n>" appended
        message_id, _, count = step_id.rpartition(":")
        return self._message_by_id(step_id) is not None or (
            count.isdigit() and self._message_by_id(message_id) is not None
        )

    def _sentinel_span(self, span_id: str | None) -> str | None:
        # the span tree has no cycle (_check_span_tree)
        walked: list[str] = []
        found: str | None = None
        while span_id is not None:
            if span_id in self.sentinel_span_of:
                found = self.sentinel_span_of[span_id]
                break
            begin = self.begins.get(span_id)
            if begin is None:
                break
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

    def _at_point(
        self, point: tuple[int, int], seq: int, run: Callable[[], None]
    ) -> None:
        self.actions.append(_Action(point[0], point[1], seq, run))

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
            step_id = self.span_events[candidate][0].step_id
            if (
                self.begins[candidate][0] > group.previous
                # a generate id names its own call, one inferred not a turn
                and step_id not in self.calls_made
            ):
                before_span = candidate
                before_id = step_id
        if before_id is None:
            before_id = f"{conversation}:{first_index}"
        input = self._input(first)

        def build_before() -> None:
            step = before_generate(
                model=first.model,
                conversation=conversation,
                input=input,
                tools=first.tools,
                tool_choice=first.tool_choice,
                config=first.config,
                agent_messages=None,
                record=self._record(conversation),
            )
            self._built(before_id, "model_input", step, before_span)

        self._at_point(
            self._cut(before_span, (first_index, 1)), group.seq, build_before
        )
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
            step = after_generate(
                model=first.model,
                conversation=conversation,
                input=input,
                tools=first.tools,
                tool_choice=first.tool_choice,
                config=first.config,
                output=last.output,
                agent_messages=None,
                record=self._record(conversation),
            )
            self._built(after_id, "model_output", step, after_span)

        self._at_point(
            self._cut(after_span, (last_index, 3)), group.seq + 1, build_after
        )
        self._settle_at_end(after_span)

    def _tool_call(self, call: _Call) -> None:
        event = call.event
        before_span = self.step_spans.get(("tool_call", event.id))
        after_span = self.step_spans.get(("tool_result", event.id))
        tool_span = call.tool_span
        proposal = call.proposal
        approval = call.approval
        if not self.eval_info.sentinel and approval is not None:
            self._approval_decision(call, approval)
        if proposal is None or call.assistant is None:
            return
        recorded = before_span is not None or after_span is not None
        if not recorded and not self._checks_tool_calls(event, call.producer):
            return
        approver_modified = (
            approval.modified
            if approval is not None
            and approval.decision == "modify"
            and approval.modified is not None
            else None
        )
        checked = before_span is not None or (
            tool_span is not None
            # the call was rejected before its step was built: by validation
            # or a viewer that raised, or with every instance abstaining, by
            # a tool that raised ToolParsingError or ToolApprovalError itself,
            # which reads the same
            and (event.error is None or event.error.type not in ("parsing", "approval"))
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
        elif modify is None or event.view is None:
            # a ToolEvent without a view is a call to a tool without a viewer,
            # whose view is the default rendering of the call
            before_view = ToolCallView(call=event.view or _default_view(before_call))
        else:
            # a sentinel's modify replaced the view with the modified call's,
            # and the tool's viewer is not in the log
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
                agent_messages=None,
                record=self._record(conversation),
            )
            self._built(event.id, "tool_call", step, before_span)

        begin = self.begins[tool_span][0] if tool_span else call.index
        self._at_point(self._cut(before_span, (begin, 1)), call.seq, build_before)
        self._settle_at_end(before_span)
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
                agent_messages=None,
                record=self._record(conversation),
            )
            self._built(event.id, "tool_result", step, after_span)

        end = self.ends.get(tool_span) if tool_span is not None else None
        after_cut = self._cut(after_span, (end if end is not None else call.index, 3))
        self._at_point(after_cut, call.seq + 2, build_after)
        self._settle_at_end(after_span)

    def _projected_tool_steps(self, generates: list[_Generate]) -> None:
        """An imported transcript's tool steps, as sentinel's messages projection takes them from the sample's messages (see `steps_from_events`), placed among the main conversation's turns."""
        conversation, turns = self._main_turns(generates)
        longest = list(
            accumulate((len(self._input(g.attempts[0][1])) for g in turns), max)
        )
        # the latest turn whose output has each id, and each content without
        # the model's name (a copy, as LangSmith writes them)
        made: dict[str, _Generate] = {}
        copied: dict[str, _Generate] = {}
        for group in turns:
            output = group.attempts[-1][1].output
            if output.choices:
                if output.message.id is not None:
                    made[output.message.id] = group
                copied[_copy_key(output.message)] = group
        answers: dict[str, list[int]] = {}
        for position, message in enumerate(self.messages):
            if (
                isinstance(message, ChatMessageTool)
                and message.tool_call_id is not None
            ):
                answers.setdefault(message.tool_call_id, []).append(position)
        for position, message in enumerate(self.messages):
            if not isinstance(message, ChatMessageAssistant):
                continue
            # the latest turn whose output is the message, else the turn before
            # the first whose input is longer than the message's position
            turn = (
                made.get(message.id) if message.id is not None else None
            ) or copied.get(_copy_key(message))
            later = bisect_right(longest, position)
            if turn is not None or later > 0:
                at = ((turn or turns[later - 1]).attempts[-1][0], 3)
            elif turns:
                at = (turns[0].attempts[0][0], 0)
            else:
                at = (len(self.events), 1)
            for call in message.tool_calls or []:
                found = answers.get(call.id, [])
                after = bisect_right(found, position)
                result = (
                    cast(ChatMessageTool, self.messages[found[after]])
                    if after < len(found)
                    else None
                )
                self._projected_call(message, position, call, result, conversation, at)

    def _main_turns(self, generates: list[_Generate]) -> tuple[str, list[_Generate]]:
        """The conversation the sample's messages are (see `steps_from_events`), and its turns."""
        ids = {m.id for m in self.messages if m.id is not None}
        keys = {_copy_key(m) for m in self.messages}

        def held(message: ChatMessage) -> bool:
            return (message.id is not None and message.id in ids) or _copy_key(
                message
            ) in keys

        made: str | None = None
        extended: tuple[int, str] | None = None
        for group in generates:
            output = group.attempts[-1][1].output
            if output.choices and held(output.message):
                made = group.conversation
            input = self._input(group.attempts[0][1])
            if input and held(input[-1]):
                if extended is None or len(input) >= extended[0]:
                    extended = (len(input), group.conversation)
        main = made or (extended[1] if extended is not None else None)
        if main is None:
            main = self._shallowest(generates)
        return main, [g for g in generates if g.conversation == main]

    def _shallowest(self, generates: list[_Generate]) -> str:
        depths: dict[str, int] = {}
        for group in generates:
            if group.conversation not in depths:
                depth = 0
                span_id: str | None = group.conversation
                while span_id is not None and span_id in self.begins:
                    begin = self.begins[span_id][1]
                    depth += begin.type == AGENT_SPAN_TYPE
                    span_id = begin.parent_id
                depths[group.conversation] = depth
        if not depths:
            return self.spans.conversation(None)
        least = min(depths.values())
        return [g for g in generates if depths[g.conversation] == least][
            -1
        ].conversation

    def _projected_call(
        self,
        assistant: ChatMessageAssistant,
        position: int,
        call: ToolCall,
        result: ChatMessageTool | None,
        conversation: str,
        at: tuple[int, int],
    ) -> None:
        view = ToolCallView(call=call.view)
        message_id = assistant.id or f"m{position}"
        seq = self._next_seq(3)

        def build_before() -> None:
            step = before_tool_call(
                conversation=conversation,
                message=assistant.text,
                message_id=message_id,
                call=call,
                view=view,
                producer=None,
                agent_messages=None,
                record=self._record(conversation),
            )
            self._built(call.id, "tool_call", step, None, unique=False)

        self._at_point(at, seq, build_before)
        if result is None:
            return
        answer = result

        def build_after() -> None:
            step = after_tool_call(
                conversation=conversation,
                message=assistant.text,
                message_id=message_id,
                call=call,
                view=view,
                result=answer,
                output=None,
                truncated=None,
                producer=None,
                agent_messages=None,
                record=self._record(conversation),
            )
            self._built(call.id, "tool_result", step, None, unique=False)

        self._at_point(at, seq + 2, build_after)

    def _checks_tool_calls(self, event: ToolEvent, producer: ModelEvent | None) -> bool:
        """Whether live checked the calls a model call produced, inferred from the region the model call was made in.

        Live decides by the region that runs the call (`checks_tool_calls()` in `call_tool`), which the log does not record, so a call run in a region other than the one its producer was made in is replayed by its producer's. A call no model call produced (a pre-filled message) is taken as checked, unless it ran in the scorers' phase, whose scope is final live. A call a sandbox bridge ran on the host (`metadata["bridge"]`) is not: the host executor runs no tool stage.
        """
        if event.metadata is not None and "bridge" in event.metadata:
            return False
        if producer is None:
            return not self._scoring(event)
        return self._origin(producer) in _NON_FINAL

    # ---- origins the log does not record

    def _origin(self, event: ModelEvent) -> str:
        if event.origin is not None:
            return event.origin
        if self._inferred is None:
            self._inferred = self._infer_origins()
        return self._inferred.get(id(event), "agent")

    def _infer_origins(self) -> dict[int, str]:
        top = [e for e, nested in zip(self.events, self.nested) if not nested]
        timeline = _timeline_build(
            top,
            message_pool=self.pool,
            final_messages=self.messages,
            conversations={
                key: conversation
                for key, conversation in (self.timeline or {}).items()
                if isinstance(key, str)
            },
            continuity=True,
        )
        utility: set[int] = set()

        def walk(span: TimelineSpan, inside: bool) -> None:
            for item in span.content:
                if isinstance(item, TimelineEvent):
                    if inside and isinstance(item.event, ModelEvent):
                        utility.add(id(item.event))
                else:
                    walk(item, inside or item.utility)
            for branch in span.branches:
                walk(branch, inside or branch.utility)

        walk(timeline.root, timeline.root.utility)
        inferred: dict[int, str] = {}
        for event, nested in zip(self.events, self.nested):
            if not isinstance(event, ModelEvent) or event.origin is not None:
                continue
            kind, phase = self._region(event.span_id)
            if self._scoring(event):
                # live, the scorers' scope is final: nothing inside it, a tool
                # or an agent, changes it
                inferred[id(event)] = "scorer"
            elif nested or kind == "tool":
                inferred[id(event)] = "tool"
            elif phase == "init":
                inferred[id(event)] = "setup"
            elif id(event) in utility:
                inferred[id(event)] = "helper"
            else:
                inferred[id(event)] = "agent"
        return inferred

    def _scoring(self, event: Event) -> bool:
        """Whether `event` was recorded in the scorers' phase: under the top-level `scorers` span, or, in a log from before spans, between a scorer's `StepEvent`s."""
        if self._scored is None:
            scored: set[int] = set()
            steps = 0
            for each in self.events:
                if isinstance(each, StepEvent) and each.type == "scorer":
                    steps = steps + 1 if each.action == "begin" else max(steps - 1, 0)
                elif steps > 0:
                    scored.add(id(each))
            self._scored = scored
        return id(event) in self._scored or self._region(event.span_id)[1] == "scorers"

    def _region(self, span_id: str | None) -> tuple[str | None, str | None]:
        """The type of the innermost agent or tool span holding `span_id`, and the phase span above it."""
        found = self._regions.get(span_id)
        if found is not None:
            return found
        if self._span_begins is None:
            self._span_begins = {
                e.id: e for e in self.events if isinstance(e, SpanBeginEvent)
            }
        begin = self._span_begins.get(span_id) if span_id is not None else None
        if begin is None:
            found = (None, None)
        else:
            kind, phase = self._region(begin.parent_id)
            if begin.type in (AGENT_SPAN_TYPE, "tool"):
                kind = begin.type
            if begin.parent_id is None and begin.name in ("init", "scorers"):
                phase = begin.name
            found = (kind, phase)
        self._regions[span_id] = found
        return found

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
        unique: bool = True,
    ) -> None:
        from inspect_sentinel import ReplayStep

        if unique:
            if (stage, step_id) in self.ids:
                raise MalformedLogError(
                    f"Two {stage} steps have the step id {step_id!r}."
                )
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
        """Publish the `human()` decisions of the step checked in `span` when the span ends, as live publishes them once the step settles, unless the invocation raised or was cancelled, which live records as an `error` or `cancelled` event at the root."""
        if span is None or span not in self.ends:
            return
        self._at(self.ends[span], 2, lambda: self._settle(span))

    def _settle(self, span: str) -> None:
        from inspect_sentinel._integration import kept_human_decision, supersedes

        built = self.span_steps.get(span)
        if built is None or span in self.failed:
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

    def _cut(self, span: str | None, anchor: tuple[int, int]) -> tuple[int, int]:
        """Where a step is built: before its sentinel span, else at its anchor."""
        return (self.begins[span][0], 1) if span is not None else anchor

    def _input(self, event: ModelEvent) -> PoolView:
        found = self._views.get(id(event))
        if found is None:
            found = self._views[id(event)] = PoolView(self.pool, event.input_refs or [])
        return found

    def _producer(self, event: ModelEvent | None) -> Producer | None:
        if event is None:
            return None
        found = self._producers.get(id(event))
        if found is None:
            found = self._producers[id(event)] = Producer(
                self._input(event), view(event.tools), event.tool_choice
            )
        return found

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
            id=event.message_id,
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

    def _assistant(
        self, call_id: str
    ) -> tuple[ChatMessageAssistant | None, ToolCall | None]:
        """A call no model call produced: the assistant message holding it, and the call."""
        if self._assistants is None:
            found: dict[str, tuple[ChatMessageAssistant, ToolCall]] = {}
            for message in [*self.pool, *self.messages]:
                if isinstance(message, ChatMessageAssistant):
                    for tool_call in message.tool_calls or []:
                        found[tool_call.id] = (message, tool_call)
            self._assistants = found
        return self._assistants.get(call_id, (None, None))

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
        # the person decided before the call ran, so its own after-call step
        # sees the decision, as a human() answer at tool_call reaches it
        span = call.tool_span
        begin = self.begins[span][0] if span is not None else call.index
        conversation = call.conversation
        self._at_point(
            (begin, 1),
            call.seq + 1,
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


def _copy_key(message: ChatMessage) -> str:
    # an importer can write an output's copy into later inputs without the
    # model's name (LangSmith)
    if isinstance(message, ChatMessageAssistant) and message.model is not None:
        message = message.model_copy(update={"model": None})
    return content_key(message)


def _default_view(call: ToolCall) -> Any:
    return default_tool_call_viewer(call).call


# a PEP 440 version, as `packaging` parses it (not an inspect_ai dependency)
_VERSION = re.compile(
    r"v?(?:(?P<epoch>\d+)!)?(?P<release>\d+(?:\.\d+)*)"
    r"(?P<pre>[-_.]?(?:a|b|c|rc|alpha|beta|pre|preview)[-_.]?\d*)?"
    r"(?P<post>-\d+|[-_.]?(?:post|rev|r)[-_.]?\d*)?"
    r"(?P<dev>[-_.]?dev[-_.]?\d*)?"
    r"(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?",
    re.IGNORECASE,
)


def _records_truncation(version: str | None) -> bool:
    # ToolEvent.truncated exists since inspect_ai 0.3.31 (max_tool_output);
    # PEP 440 orders 0.3.31's dev and pre-releases before it, and a version
    # that does not parse is taken as recording it
    if version is None:
        return False
    parsed = _VERSION.fullmatch(version.strip())
    if parsed is None:
        return True
    if int(parsed["epoch"] or 0) > 0:
        return True
    release = [int(part) for part in parsed["release"].split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    if release != [0, 3, 31]:
        return release > [0, 3, 31]
    if parsed["pre"]:
        return False
    return bool(parsed["post"]) or not parsed["dev"]


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


def _check_span_tree(events: Sequence[Event]) -> None:
    """Fail on a `parent_id` cycle anywhere in the span tree, visiting each span once."""
    parents = {
        event.id: event.parent_id
        for event in events
        if isinstance(event, SpanBeginEvent)
    }
    done: set[str] = set()
    for span_id in parents:
        path: list[str] = []
        on_path: set[str] = set()
        current: str | None = span_id
        while current is not None and current in parents and current not in done:
            if current in on_path:
                raise MalformedLogError(
                    f"The span tree has a parent_id cycle at {current}."
                )
            path.append(current)
            on_path.add(current)
            current = parents[current]
        done.update(path)
