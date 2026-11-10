"""The log driver: a sample's steps rebuilt from its events, with the builders the live dispatcher uses (`_steps.py`)."""

import logging
import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from functools import partial
from itertools import accumulate
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from inspect_ai._util.content import Content
from inspect_ai._util.json import json_equal, jsonable_python
from inspect_ai.agent._bridge.sandbox.host_tool import delivered_host_tool_content
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
    _call_failed,
    _timeline_build,
)
from inspect_ai.event._tool import ToolEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallView,
    default_tool_call_viewer,
)
from inspect_ai.util._span import AGENT_SPAN_TYPE

from ._conversation import SpanConversations
from ._scope import BRIDGE_CHECK_SPAN, is_agent_turn
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
    """The inspect_ai that wrote the log (`eval.packages["inspect_ai"]`); a log without one does not say whether a tool's output was cut."""

    sentinel: bool
    """Whether the eval ran a sentinel (`eval.config.sentinel`): if it did, earlier `human()` decisions come from its `SentinelEvent`s; otherwise, logs from inspect_ai 0.3.277 or later can use the `ApprovalEvent`s of human approvers."""

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
    messages_from: Sequence[str] | None = None,
) -> list["ReplayStep"]:
    """The steps a sentinel was handed live, or would have been had it watched every stage, rebuilt from a sample's events.

    One pass reads the events in log order, and a second applies what changed each conversation's record (the inputs its agent turns sent, the `human()` decisions published) in that order, building each step at the point live built it. For the input shapes Inspect normally logs, work grows with the stored log: model inputs are read as ranges of the message pool, each pool row's content key is computed once, and steps hold views of each conversation's lists rather than copies. Repeated summary compactions can still cost retained messages times compactions when no summary text is found in the next input.

    Every step's `agent_messages` is None: the log does not record the agent's own messages, and model input can hold messages the agent kept out of them.

    A log that does not record where a model call was made (`ModelEvent.origin`, written since inspect_ai PR #5990), as an older Inspect log does not, has its turns inferred from its span tree: a call made in the scorers' span is a scorer's, whatever tool or agent span holds it (live, the scorers' scope is final); one in a tool's span a tool's, and one in the init span, or, in a log that records a phase span (`init`, `solvers` or `scorers`, as every log since 0.3.100 does), outside every phase span (lifecycle hooks before solving, scoring hooks and `Task.cleanup` after it, whether or not solving started), setup's; of the rest, those the inferred timeline shows as utility (`timeline_build`'s prompt and continuity rules, the calls above and a sentinel's taking no part in either) are not turns, and the others are. A final scope no span records reads as the region holding it: a `model_origin()` region, `score()` called by a solver or a tool, an approver's model call; where the timeline does not show such a call as utility, its call is a turn (or, in a tool, its calls are checked), as live it was not.

    Inspect logs record origins on every model call or on none. If a transcript mixes calls with and without origins, recorded calls retain their recorded classification and calls without origins are inferred; continuity across that mixed sequence is not guaranteed.

    In logs without origins, recorded sentinel checks and human decisions are used only when their step id pairs with a model call's exact id. Inferred turns may differ from those seen by a sentinel that ran before origins were recorded; reproducing that sentinel's live steps is outside this replay contract. For a run without a sentinel, human decisions are reconstructed from `ApprovalEvent`s only when the log records inspect_ai 0.3.277 or later; older or unknown versions omit them and warn once when a selected human approver appears. A `tool_call` step whose call an approver changed has no `view.context`: the `ApprovalEvent` view describes the call the approver was shown, and live renders the changed call's context again, which the log does not record. A log is refused where the call an approval approved (its modified call, else the call it records) is not the call its `ToolEvent` records, unless a recorded sentinel modify changed the call again to the one the `ToolEvent` records. Inspect before 0.3.277 wrote such logs, including for a call an approver changed in place and approved without a modified call, and they are refused whatever version the header records, since a retried eval keeps its completed samples under a newer header. This includes an approved call whose tool records other arguments than it was given, such as `memory()` resolving a path: the log does not show which implementation ran. Replay such a transcript from its messages instead. Where such a call has no recorded step and its `ToolEvent` has a parsing or approval error, it may have been refused before it ran or raised the error after running, so replay skips its tool steps with a warning naming the call instead of refusing the log.

    A tool call is joined to the model call that proposed it by the id of the message its `ToolEvent` records (`call_message_id`, written since inspect_ai #6143), and to its result by its tool message's id (`message_id`). Where the event records no proposing message (an older log), or the id names several model calls' output (a cached output reused), a native call's producer is the latest model call that proposed its id (in the call's own conversation, where model calls in several conversations proposed it), a bridge's generation included, and its steps are matched by heuristic (`ReplayStep.matched`). A native call's recorded checks are those under its id between its own events: its `tool_call` check after its producer and before its tool span, and its `tool_result` check after its tool span and before a later model call proposed its id again in its conversation.

    A host call a sandbox bridge ran (`ToolEvent.metadata["bridge"]`) is replayed where its event ties it to its proposal and its run exactly: its proposing message is one model call's output holding the call under the model's id (`proposal_id`), and either the bridge linked the run to its answer (`message_id`) or a check the bridge recorded names the proposal and the run (`SentinelEvent.execution_id`, else the call id). Its `tool_call` step is the call as the bridge checked it, under the model's id, with the host tool's name and the arguments it ran with (a sentinel's modify aside), once per proposal, keyed by the id its first run has; each run's `tool_result` step holds the result as the service delivered it, keyed by the run's id: rebuilt from the `ToolEvent`'s result as the service converts it, except that an error's text is the tool's, not the service's wrapper, and a single content item other than an image, which the event records as a list of one, is delivered as that list. Other host calls, and the calls a bridged scaffold ran itself, which leave no `ToolEvent`, are skipped, and a warning names them. A `human()` decision at a skipped step, and a person's approval of a host call, still reach the later steps of the conversation, as live. A bridge's tool checks are recorded in spans named `sentinel_bridge`, so a native call under an id a bridge also checked keeps its own checks.

    A transcript Scout imported from another source (`eval_info` is None) replays from its events where Scout records which model calls its messages come from (`messages_from`): its turns are inferred as for a log without origins, and its tool steps come from its messages, each assistant message joined by its id to the turn whose output it is, which gives the steps that turn's input, tools and conversation; a message no one turn made is placed after the last message before it that one did, with no input, matched by heuristic. Its tool events are not read: importers record them without the model's call ids.

    Replay requires a log written by Inspect 0.3.100 or later. Earlier logs lack the `solvers` and `scorers` spans (and, before 0.3.94, native tool spans) and cannot be replayed reliably. A log whose samples have an earlier layout is refused whatever its header says, since a retried eval keeps its completed samples under a newer header: a `ToolEvent` that nests other events, a solver or scorer `StepEvent`, a top-level scorer span, or a top-level solver span in a sample that records no `solvers` span (where one is recorded, a top-level solver span is a chain `Task.cleanup` or a hook awaited, and its calls are setup's; a `scorers` span alone does not count, since rescoring adds one to an older sample). If the recorded version is unknown, completed native tool events without a matching tool span, including execution failures, are also refused as potentially older logs. Pending calls and spanless parsing, approval, or cancelled errors remain allowed. A completed spanless timeout is refused when the version is unknown.

    Args:
        messages: The sample's messages (`EvalSample.messages`).
        events: The sample's events, with model inputs condensed (`input_refs` into `message_pool`), as the log stores them; inputs given expanded are condensed first. Attachments must be resolved (`resolve_attachments`), or monitors are handed `attachment://` references.
        message_pool: The sample's message pool (`EvalSample.events_data["messages"]`).
        sample_uuid: The sample's uuid: the conversation of calls made outside any agent span.
        eval_info: What the log's header says about the eval (`EvalInfo.from_eval`), or None for a transcript imported from another source, which has no header.
        timeline: A stored timeline for grouping replay steps into its conversations. For logs without origins, turn inference uses the event span tree, regardless of this timeline.
        human_approvers: The registry names of approvers that are people, whose `ApprovalEvent`s are `human_decisions` in a log from an eval that ran no sentinel and records inspect_ai 0.3.277 or later.
        messages_from: For an imported transcript, the `uuid`s of the model events its messages are from (Scout's `TranscriptInfo.messages_from`). Ignored for an Inspect log.

    Returns:
        The steps, in the order they ran live.

    Raises:
        ValueError: `eval_info` and `messages_from` are both `None`, the log predates Inspect 0.3.100 or its samples have an earlier layout (or it has an unknown version and completed spanless native tool events), or the call an approval approved is not the call its `ToolEvent` records. Replay such transcripts from their messages instead.
        MalformedLogError: Two generate steps of one stage have one step id, the span tree has a `parent_id` cycle, or a model input names rows outside the message pool.
        Unmatched recorded model_input checks are skipped with one warning per transcript.
    """
    if eval_info is None and messages_from is None:
        raise ValueError(
            "steps_from_events replays an Inspect log, which needs its header "
            "(EvalInfo.from_eval), or a transcript imported from another source, "
            "which needs the model calls its messages are from (messages_from). "
            "Replay this transcript from its messages instead."
        )
    version = eval_info.inspect_ai_version if eval_info is not None else None
    if eval_info is not None and (
        _before_phase_spans(version)
        or _has_earlier_layout(events)
        or (
            (version is None or _VERSION.fullmatch(version.strip()) is None)
            and _has_spanless_native_tool(events)
        )
    ):
        raise ValueError(
            "steps_from_events requires an Inspect log written by inspect_ai "
            "0.3.100 or later. Replay this transcript from its messages instead."
        )
    conversations = _timeline_conversations(timeline) if timeline else None
    pool: list[ChatMessage] | Sequence[ChatMessage] = message_pool
    if any(isinstance(e, ModelEvent) and e.input_refs is None for e in events):
        condensed, pool = _condensed(events, message_pool)
        if conversations is not None:
            _rekey(conversations, events, condensed)
        events = condensed
    return _Driver(
        messages,
        list(events),
        pool,
        sample_uuid,
        eval_info,
        conversations,
        human_approvers,
        messages_from,
    ).steps()


def _has_earlier_layout(events: Sequence[Event]) -> bool:
    """Whether the samples have a layout of Inspect before 0.3.100, which a retried eval keeps under a newer header: a `ToolEvent` that nests events, a solver or scorer `StepEvent`, a top-level scorer span, or a top-level solver span in a log that records no `solvers` span (0.3.99 records `init`, and rescoring adds `scorers`). Where one is recorded, a solver span outside it is a chain awaited by `Task.cleanup` or a hook."""
    phased = _records_phases(events, ("solvers",))
    return any(
        (isinstance(event, ToolEvent) and event.events)
        or (isinstance(event, StepEvent) and event.type in ("solver", "scorer"))
        or (
            isinstance(event, SpanBeginEvent)
            and event.parent_id is None
            and (event.type == "scorer" or (event.type == "solver" and not phased))
        )
        for event in events
    )


def _records_phases(
    events: Sequence[Event], phases: tuple[str, ...] = ("init", "solvers", "scorers")
) -> bool:
    return any(
        isinstance(e, SpanBeginEvent) and e.parent_id is None and e.name in phases
        for e in events
    )


def _has_spanless_native_tool(events: Sequence[Event]) -> bool:
    """Whether a completed native tool event has no matching tool span, as in logs before 0.3.94."""
    spans = _tool_spans(events)
    return any(
        isinstance(event, ToolEvent)
        and index not in spans
        and event.completed is not None
        and not _bridged(event)
        and not event.pending
        and (
            event.error is None
            or event.error.type not in ("parsing", "approval", "cancelled")
        )
        for index, event in enumerate(events)
    )


def _tool_spans(events: Sequence[Event]) -> dict[int, str]:
    """The `tool` span of each `ToolEvent` that has one, by event index.

    `call_tool` records the event, which names the span that called the tool, first in the tool's span (under a `handoff` span for a handoff), so the span is the event's previous sibling in the span tree. Rescoring rebuilds the events from that tree, which moves the event after the span's end. A handoff span's tool span is its last child span, since the handoff ends with the `StoreEvent` of an agent that changes the store. An event that names the tool span itself is paired with it when it is the span's first child.
    """
    begins: dict[str, SpanBeginEvent] = {}
    last_child: dict[str | None, Event] = {}
    last_span: dict[str | None, SpanBeginEvent] = {}
    spans: dict[int, str] = {}
    for index, event in enumerate(events):
        if isinstance(event, SpanEndEvent):
            continue
        if isinstance(event, SpanBeginEvent):
            begins[event.id] = event
            parent = event.parent_id
        else:
            parent = event.span_id
        if isinstance(event, ToolEvent):
            own = begins.get(parent) if parent is not None else None
            if own is not None and parent not in last_child:
                candidate: Event | None = own
            else:
                candidate = last_child.get(parent)
                if (
                    isinstance(candidate, SpanBeginEvent)
                    and candidate.type == "handoff"
                ):
                    candidate = last_span.get(candidate.id)
            if (
                isinstance(candidate, SpanBeginEvent)
                and candidate.type == "tool"
                and candidate.name == event.function
            ):
                spans[index] = candidate.id
        last_child[parent] = event
        if isinstance(event, SpanBeginEvent):
            last_span[parent] = event
    return spans


def _condensed(
    events: Sequence[Event], pool: Sequence[ChatMessage]
) -> tuple[list[Event], list[ChatMessage]]:
    """`events` with their model inputs condensed, and the pool."""
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
    seq: int


class _Proposal(NamedTuple):
    position: int
    message: ChatMessageAssistant
    event: ModelEvent
    call: ToolCall
    conversation: str


class _Proposals:
    # Concurrent agents can propose the same call id. An approval or ToolEvent
    # is owned by the latest proposal of the only conversation proposing its
    # id, else by the latest in its own conversation, else by the latest in
    # its own span (a stored timeline can split a span), else by none.

    def __init__(self) -> None:
        self._latest: dict[str, _Proposal] = {}
        self._by_span: dict[tuple[str, str | None], _Proposal] = {}
        self._by_conversation: dict[tuple[str, str], _Proposal] = {}
        # the one conversation proposing each id; None once several have
        self._conversation: dict[str, str | None] = {}

    def add(self, proposal: _Proposal) -> None:
        id = proposal.call.id
        self._latest[id] = proposal
        self._by_span[(id, proposal.event.span_id)] = proposal
        self._by_conversation[(id, proposal.conversation)] = proposal
        if self._conversation.get(id, proposal.conversation) != proposal.conversation:
            self._conversation[id] = None
        else:
            self._conversation[id] = proposal.conversation

    def proposed(self, id: str) -> bool:
        return id in self._latest

    def owner(
        self, id: str, span_id: str | None, conversation: str
    ) -> _Proposal | None:
        if self._conversation.get(id) is not None:
            return self._latest[id]
        found = self._by_conversation.get((id, conversation))
        return found if found is not None else self._by_span.get((id, span_id))

    def approval_key(
        self, id: str, owner: _Proposal | None, conversation: str
    ) -> tuple[str, str | None]:
        # an approval a ToolEvent can consume is held under its owner's
        # conversation, its own where proposals are ambiguous, and None where
        # nothing has proposed the id yet (a pre-filled call)
        if owner is not None:
            return (id, owner.conversation)
        return (id, conversation if self.proposed(id) else None)


@dataclass
class _Call:
    index: int
    event: ToolEvent
    conversation: str
    assistant: ChatMessageAssistant | None
    proposal: ToolCall | None
    producer: ModelEvent | None
    # the index of the producer's event, or -1
    produced_at: int
    approval: ApprovalEvent | None
    seq: int
    # the call's `tool` span (_tool_spans)
    tool_span: str | None
    # whether its producer, or the message holding a call no model call
    # produced, was found by the id its ToolEvent records (`call_message_id`)
    by_id: bool = False
    # the sentinel spans of the call's checks (_take_checks)
    before_span: str | None = None
    after_span: str | None = None
    # where a later call under its id was produced: its result check began
    # before then (_take_checks)
    until: int | None = None
    # for a sandbox bridge's host call, whether it is its proposal's first run,
    # which has the proposal's tool_call step
    first_run: bool = True


class _Region(NamedTuple):
    """Where a span sits, as origin inference reads it."""

    kind: str | None
    """The type of the innermost agent or tool span holding it."""

    phase: str | None
    """The phase span (`"init"`, `"solvers"`, `"scorers"`) holding it."""

    sentinel: bool
    """Whether a sentinel's span holds it."""


class _Action(NamedTuple):
    position: int
    # at one position: steps built before the event there (1), the event's own
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
        pool: Sequence[ChatMessage],
        sample_uuid: str,
        eval_info: EvalInfo | None,
        conversations: dict[object, str] | None,
        human_approvers: Sequence[str],
        messages_from: Sequence[str] | None = None,
    ) -> None:
        self.messages = messages
        self.events = events
        self.pool = pool
        self.keys = _PoolKeys(pool)
        # a transcript imported from another source has no header
        self.imported = eval_info is None
        self.messages_from = set(messages_from or ())
        eval_info = eval_info or EvalInfo(inspect_ai_version=None, sentinel=False)
        self.eval_info = eval_info
        self.human_approvers = set(human_approvers)
        self.approval_log_reliable = _records_approval_decisions(
            eval_info.inspect_ai_version
        )
        self.reconstruct_approval_decisions = (
            not eval_info.sentinel and self.approval_log_reliable
        )
        self.spans = SpanConversations(sample_uuid)
        self.timeline = conversations
        self.begins: dict[str, tuple[int, SpanBeginEvent]] = {}
        self.ends: dict[str, int] = {}
        self.sentinel_span_of: dict[str, str | None] = {}
        # (stage, step id) -> the sentinel span of the step, for generate steps
        self.step_spans: dict[tuple[SentinelStage, str], str] = {}
        # (stage, call id) -> the sentinel spans of native tool steps with that
        # id, in log order: a model can reuse a call id
        self.tool_spans: dict[tuple[SentinelStage, str], list[str]] = {}
        # (stage, call id, run) -> the sentinel spans of bridge tool checks
        # (BRIDGE_CHECK_SPAN), in log order; the run is the id the scaffold was
        # handed the call under (`execution_id`, else the call id)
        self.bridge_spans: dict[tuple[SentinelStage, str, str], list[str]] = {}
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
        # the ids of the calls whose tool steps replay skips
        self.skipped: list[str] = []
        # call id -> the indexes of the model events that proposed it
        self.proposed: dict[str, list[int]] = {}
        # output message id -> the indexes of the model events that produced it
        # (more than one for a cached output reused)
        self.outputs: dict[str, list[int]] = {}
        # (call id, run) -> the approvals recorded for it, in log order
        self.run_approvals: dict[tuple[str, str], list[tuple[int, ApprovalEvent]]] = {}
        # (producer index, call id) of each host call proposal run so far
        self.runs: dict[tuple[int, str], str] = {}
        # the ids of native calls, and of the host runs replayed
        self.native_ids: set[str] = set()
        self.host_runs: set[str] = set()
        # each model event's input view and producer, shared by its steps
        self._views: dict[int, PoolView] = {}
        self._producers: dict[int, Producer] = {}
        self._assistants: dict[str, tuple[ChatMessageAssistant, ToolCall]] | None = None
        # each assistant message and its text, by id() (`_text`)
        self._texts: dict[int, tuple[ChatMessageAssistant, str]] = {}
        self._messages_by_id: dict[str, list[ChatMessage]] | None = None
        # the origins of model calls the log records none for, by id()
        self._inferred: dict[int, str] | None = None
        # the uuids of model calls made outside sentinel spans
        self.calls_made: set[str | None] = set()
        # event indexes of ToolEvents whose tool steps are skipped
        # (_check_modified_approval); a call id can recur across turns
        self.unverified_calls: set[int] = set()
        # span id -> the region holding it
        self._regions: dict[str | None, _Region] = {}
        self._span_begins: dict[str, SpanBeginEvent] | None = None

    # ---- the first pass: read the events in log order

    def steps(self) -> list["ReplayStep"]:
        _check_span_tree(self.events)
        generates: list[_Generate] = []
        # each span's generates whose last attempt errored, by input: a retry
        # joins the open generate with its own input
        open_generates: dict[
            tuple[str | None, tuple[tuple[int, int], ...]], _Generate
        ] = {}
        calls_made: set[str | None] = set()
        proposals = _Proposals()
        # approvals a ToolEvent can consume, by call id and owning conversation
        # (None before any model call proposed the id)
        approvals: dict[tuple[str, str | None], tuple[int, ApprovalEvent]] = {}
        approval_entries: list[tuple[int, ApprovalEvent, str]] = []
        unplaced_approvals: list[tuple[int, ApprovalEvent]] = []
        consumed_approvals: set[int] = set()
        calls: list[_Call] = []
        tool_spans = _tool_spans(self.events)

        # Every span first so origin inference sees later span declarations.
        for event in self.events:
            if isinstance(event, SpanBeginEvent):
                self.spans.add(event)
        for index, event in enumerate(self.events):
            if isinstance(event, SpanBeginEvent):
                self.begins[event.id] = (index, event)
            elif isinstance(event, SpanEndEvent):
                self.ends[event.id] = index
            elif isinstance(event, SentinelEvent):
                self._sentinel_event(event)
            elif isinstance(event, ModelEvent):
                if self._in_sentinel_span(event.span_id):
                    continue
                calls_made.add(event.uuid)
                message_id = producing_message_id(event)
                if message_id is not None:
                    self.outputs.setdefault(message_id, []).append(index)
                    message = event.output.choices[0].message
                    proposed_in = self._conversation(event)
                    for tool_call in message.tool_calls or []:
                        # A new proposal cannot consume the prior attempt's approval.
                        approvals.pop((tool_call.id, proposed_in), None)
                        approvals.pop((tool_call.id, None), None)
                        proposals.add(
                            _Proposal(index, message, event, tool_call, proposed_in)
                        )
                        self.proposed.setdefault(tool_call.id, []).append(index)
                if not is_agent_turn(self._origin(event)):
                    continue
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
                        self._next_seq(2),
                    )
                    generates.append(group)
                if event.error is not None:
                    open_generates[attempt_key] = group
            elif isinstance(event, ApprovalEvent):
                if self.imported or self._in_sentinel_span(event.span_id):
                    continue
                self.run_approvals.setdefault(
                    (event.call.id, event.execution_id or event.call.id), []
                ).append((index, event))
                own = self._conversation(event)
                owner = proposals.owner(event.call.id, event.span_id, own)
                approvals[proposals.approval_key(event.call.id, owner, own)] = (
                    index,
                    event,
                )
                if owner is None and proposals.proposed(event.call.id):
                    unplaced_approvals.append((index, event))
                else:
                    approval_entries.append(
                        (index, event, owner.conversation if owner else own)
                    )
            elif isinstance(event, CompactionEvent):
                conversation = self._conversation(event)
                self._at(index, 2, partial(self._count_compaction, conversation))
            elif isinstance(event, ToolEvent):
                # an imported transcript's tool steps are its messages'
                # (_imported_tool_steps)
                if self.imported or self._in_sentinel_span(event.span_id):
                    continue
                own = self._conversation(event)
                # the model call that proposed it, by the message id its event
                # records, else, in a log from before that id or where it is
                # ambiguous, the latest proposal of its call id (`_Proposals`);
                # a host call is not given a proposal by call id
                owner = self._proposal_by_id(event)
                # a call no model call produced (a pre-filled message): the
                # message holding it, by the same id
                prefilled = None if owner is not None else self._prefilled_by_id(event)
                by_id = owner is not None or prefilled is not None
                if not by_id and not _bridged(event):
                    owner = proposals.owner(event.id, event.span_id, own)
                producer: ModelEvent | None = None
                produced_at = -1
                assistant: ChatMessageAssistant | None
                proposal: ToolCall | None
                if owner is not None:
                    assistant, producer, proposal, produced_at = (
                        owner.message,
                        owner.event,
                        owner.call,
                        owner.position,
                    )
                elif prefilled is not None:
                    assistant, proposal = prefilled
                elif _bridged(event):
                    assistant, proposal = None, None
                else:
                    assistant, proposal = self._assistant(event.id)
                conversation = owner.conversation if owner is not None else own
                # The bridge approves a host call when the model proposes it,
                # and the scaffold may run it after later requests, so its
                # decision is published where the approval is recorded.
                recorded_approval = (
                    None
                    if _bridged(event)
                    else approvals.pop(
                        proposals.approval_key(event.id, owner, own), None
                    )
                )
                if recorded_approval is not None:
                    consumed_approvals.add(recorded_approval[0])
                entry = _Call(
                    index,
                    event,
                    conversation,
                    assistant,
                    proposal,
                    producer,
                    produced_at,
                    recorded_approval[1] if recorded_approval is not None else None,
                    self._next_seq(3),
                    tool_spans.get(index),
                    by_id,
                )
                calls.append(entry)

        self.calls_made = calls_made
        self._warn_unmatched_checks()
        if (
            not self.eval_info.sentinel
            and not self.reconstruct_approval_decisions
            and any(
                approval.approver in self.human_approvers
                for _, approval, _ in approval_entries
            )
        ):
            logging.getLogger(__name__).warning(
                "Skipped human decisions from ApprovalEvents: reconstruction "
                "requires inspect_ai 0.3.277 or later; this log's version is "
                "older or unknown."
            )
        if self.reconstruct_approval_decisions:
            unplaced = [
                approval.call.id
                for index, approval in unplaced_approvals
                if index not in consumed_approvals
                and approval.approver in self.human_approvers
            ]
            if unplaced:
                logging.getLogger(__name__).warning(
                    "Skipped the human decisions on call(s) %s: model calls in "
                    "several conversations proposed each id, none in the "
                    "approval's own.",
                    ", ".join(repr(id) for id in unplaced),
                )
            for index, approval, conversation in approval_entries:
                if index not in consumed_approvals:
                    self._approval_decision(
                        approval,
                        conversation,
                        (index, 2),
                        self._next_seq(),
                    )
        _bound_result_checks(
            calls,
            lambda call: (
                call.producer is not None and is_agent_turn(self._origin(call.producer))
            ),
        )
        self.native_ids = {c.event.id for c in calls if not _bridged(c.event)}
        for entry in calls:
            self._take_checks(entry)
            self._check_modified_approval(entry)
        if self.unverified_calls:
            logging.getLogger(__name__).warning(
                "Skipped the tool steps of call(s) %s: each ended in a parsing or "
                "approval error, and its approved call differs from its ToolEvent, "
                "so the log cannot show whether or with which arguments it ran.",
                ", ".join(
                    repr(entry.event.id)
                    for entry in calls
                    if entry.index in self.unverified_calls
                ),
            )
        for group in generates:
            self._generate(group)
        if self.imported:
            self._imported_tool_steps(generates)
        for entry in calls:
            self._tool_call(entry)
        self._settle_unbuilt_checks()

        # the second pass: in log order, each step at its cut
        for action in sorted(self.actions, key=lambda a: (a.position, a.phase, a.seq)):
            action.run()
        return self.built

    def _sentinel_event(self, event: SentinelEvent) -> None:
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
        if event.stage in ("tool_call", "tool_result"):
            if self.begins[span][1].name == BRIDGE_CHECK_SPAN:
                run = event.execution_id or event.step_id
                self.bridge_spans.setdefault(
                    (event.stage, event.step_id, run), []
                ).append(span)
            else:
                self.tool_spans.setdefault(key, []).append(span)
            return
        other = self.step_spans.get(key)
        if other is not None and other != span:
            raise MalformedLogError(
                f"Two {event.stage} steps have the step id {event.step_id!r}."
            )
        self.step_spans[key] = span

    def _warn_unmatched_checks(self) -> None:
        unmatched = sum(
            step_id not in self.calls_made
            for stage, step_id in self.step_spans
            if stage in ("model_input", "model_output")
        )
        if unmatched:
            logging.getLogger(__name__).warning(
                "Skipped %d sentinel model check(s) without a matching model call in this transcript.",
                unmatched,
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

        before_span = (
            self.step_spans.get(("model_input", first.uuid))
            if first.uuid is not None
            else None
        )
        before_id = first.uuid
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
            self._built(before_id, "model_input", step, before_span, True)

        self._at_point(
            self._cut(before_span, (first_index, 1)), group.seq, build_before
        )
        self._settle_at_end(before_span)

        if _call_failed(last):
            return
        after_span = (
            self.step_spans.get(("model_output", first.uuid))
            if first.uuid is not None
            else None
        )
        after_id = before_id

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
            self._built(after_id, "model_output", step, after_span, True)

        self._at_point(
            self._cut(after_span, (last_index, 3)), group.seq + 1, build_after
        )
        self._settle_at_end(after_span)

    def _check_modified_approval(self, call: _Call) -> None:
        """Refuse an approval whose approved call its `ToolEvent` does not record.

        The approved call is the approval's modified call, else the call it
        records. Before 0.3.277 the `ToolEvent` kept the proposal while the
        approved call ran, including a call the approver changed in place and
        approved without a modified call, and a retried eval keeps such samples
        under a newer header, so only the events can show which call ran.
        Arguments must be equal as recorded: a tool that rewrites them, such as
        `memory()` resolving a path, is refused, since a custom tool can share
        its name. A sentinel's recorded modify can change the call again after
        the approval. A call with no recorded step whose `ToolEvent` has a
        parsing or approval error may have been refused before it ran, or its
        tool may have raised the error after running; where its approved call
        differs, it is added to `unverified_calls` instead of refused.

        A host call a sandbox bridge ran (`metadata["bridge"]`) has no paired
        approval, so is not checked: its approval may record the call under the
        scaffold's name and its `ToolEvent` under the host tool's, and replay
        takes the arguments it ran with from its run (`_host_call`).
        """
        approval = call.approval
        event = call.event
        if approval is None or approval.decision not in ("approve", "modify"):
            return
        before_span = call.before_span
        approved = approval.modified if approval.modified is not None else approval.call
        if (
            event.function == approved.function
            and json_equal(event.arguments, approved.arguments)
        ) or self._sentinel_modify(before_span, event) is not None:
            return
        if (
            before_span is None
            and call.after_span is None
            and event.error is not None
            and event.error.type in ("parsing", "approval")
        ):
            self.unverified_calls.add(call.index)
            return
        raise ValueError(
            "steps_from_events cannot replay an approval whose approved call "
            "does not match the ToolEvent that ran, so the log cannot show which "
            "arguments ran. Replay this transcript from its messages instead."
        )

    def _take_checks(self, call: _Call) -> None:
        """Pair a native call with the first of its recorded checks no earlier call took, in log order.

        A call its approver refused never ran, so takes no result check.
        """
        event = call.event
        tool_span = call.tool_span
        # live checks the call before its tool span opens, and its result once
        # the span has ended
        begin = self.begins[tool_span][0] if tool_span is not None else call.index
        end = self.ends.get(tool_span) if tool_span is not None else None
        if _bridged(event):
            self._take_bridge_checks(call, begin, end)
            return
        call.before_span = self._tool_span_of(
            ("tool_call", event.id), call.produced_at, begin
        )
        if end is not None and not _approval_refused(call.approval):
            call.after_span = self._tool_span_of(
                ("tool_result", event.id),
                end,
                call.until,
                ending=event.failed is True,
            )

    def _take_bridge_checks(self, call: _Call, begin: int, end: int | None) -> None:
        """Pair a sandbox bridge's host call with its recorded checks, by the call's id and the id of the run they checked.

        The bridge checks every call of a response before the scaffold gets it,
        so a proposal's `tool_call` check is before its first run, under the id
        its first run has (#6370: `execution_id`, else the call id); each run's
        result is checked after its tool span ends, under the run's own id.
        """
        proposal = call.proposal
        if not call.by_id or proposal is None:
            return
        run = (call.produced_at, proposal.id)
        call.first_run = run not in self.runs
        self.runs.setdefault(run, call.event.id)
        if call.first_run:
            call.before_span = self._bridge_span_of(
                ("tool_call", proposal.id, call.event.id), call.produced_at, begin
            )
        if end is not None:
            call.after_span = self._bridge_span_of(
                ("tool_result", proposal.id, call.event.id), end
            )

    def _bridge_span_of(
        self,
        key: tuple[SentinelStage, str, str],
        after: int,
        before: int | None = None,
    ) -> str | None:
        """The first bridge check with this stage, call id and run that no call has taken and begins between the events at `after` and `before`."""
        spans = self.bridge_spans.get(key, [])
        for at, span in enumerate(spans):
            position = self.begins[span][0]
            if position > after and (before is None or position < before):
                return spans.pop(at)
        return None

    def _tool_call(self, call: _Call) -> None:
        event = call.event
        approval = call.approval
        tool_span = call.tool_span
        begin = self.begins[tool_span][0] if tool_span is not None else call.index
        end = self.ends.get(tool_span) if tool_span is not None else None
        if self.reconstruct_approval_decisions and approval is not None:
            self._approval_decision(
                approval, call.conversation, (begin, 1), call.seq + 1
            )
        if _bridged(event):
            if self._links_host_call(call):
                self.host_runs.add(event.id)
                self._host_call(call, begin, end)
            else:
                # its checks still publish their decisions
                self._settle_at_end(call.before_span)
                self._settle_at_end(call.after_span)
                self.skipped.append(event.id)
            return
        before_span = call.before_span
        after_span = call.after_span
        proposal = call.proposal
        if (
            proposal is None
            or call.assistant is None
            or call.index in self.unverified_calls
        ):
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
                    approval.decision == "modify"
                    and (
                        approver_modified is None
                        or approver_modified.function == proposal.function
                    )
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
        if modify is None:
            before_call = replace(approved, arguments=event.arguments)
        elif self.approval_log_reliable and approval is not None:
            # the call the approver approved, validated, which the sentinel's
            # modify then replaced
            before_call = approver_modified or approval.call
        else:
            before_call = approved
        presented = event if modify is None else before_call
        shown = (
            approval is not None
            and presented.function == approval.call.function
            and json_equal(presented.arguments, approval.call.arguments)
        )
        if (
            self.approval_log_reliable
            and approval is not None
            and approval.view is not None
            and (modify is None or shown)
        ):
            # the approval's view is of the call it was shown; a changed call's
            # context is not recorded
            before_view = ToolCallView(
                context=approval.view.context if shown else None,
                call=(event.view if modify is None else approval.view.call)
                or _default_view(before_call),
            )
        elif (
            not self.approval_log_reliable
            and approval is not None
            and approval.view is not None
            and event.function == approval.call.function
            and json_equal(event.arguments, approval.call.arguments)
        ):
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
        assistant_text = self._text(assistant)

        def build_before() -> None:
            step = before_tool_call(
                conversation=conversation,
                message=assistant_text,
                message_id=assistant_id,
                call=before_call,
                view=before_view,
                producer=producer,
                agent_messages=None,
                record=self._record(conversation),
            )
            self._built(event.id, "tool_call", step, before_span, call.by_id)

        self._at_point(self._cut(before_span, (begin, 1)), call.seq, build_before)
        self._settle_at_end(before_span)
        if not ran:
            return

        after_call = modify if modify is not None else before_call
        after_call = replace(
            after_call,
            id=event.id,
            function=event.function,
            arguments=event.arguments,
        )
        truncated = self._truncated(event)
        result = self._result(event)

        def build_after() -> None:
            step = after_tool_call(
                conversation=conversation,
                message=assistant_text,
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
            self._built(event.id, "tool_result", step, after_span, call.by_id)

        after_cut = self._cut(after_span, (end if end is not None else call.index, 3))
        self._at_point(after_cut, call.seq + 2, build_after)
        self._settle_at_end(after_span)

    def _links_host_call(self, call: _Call) -> bool:
        """Whether a sandbox bridge's host call is tied to the model call that proposed it and to its run exactly, so replay builds its steps.

        Its proposal is found by the message id its event records
        (`call_message_id`, #6143), naming one model call's output with one
        call under the model's id (`proposal_id`). That id names the reply the
        bridge granted the run to, which is the reply that ran only where the
        bridge could tell: so the run must also be linked to its answer
        (`message_id`, which the bridge sets only for a reply placed and run
        once, with no other reply's pending call matching the run), or a check
        the bridge recorded must name the proposal and the run (#6370). Its run
        must not share its id with a native call or an earlier run, since step
        ids are unique in a sample. Else replay skips its steps, and warns.
        """
        return (
            call.by_id
            # step ids are unique in a sample: a native call, or an earlier
            # run, under the run's id keeps it
            and call.event.id not in self.native_ids
            and call.event.id not in self.host_runs
            and call.producer is not None
            and call.proposal is not None
            and call.assistant is not None
            and (
                call.event.message_id is not None
                or call.before_span is not None
                or call.after_span is not None
            )
        )

    def _host_call(self, call: _Call, begin: int, end: int | None) -> None:
        """The steps of a sandbox bridge's host call, as the bridge built them live.

        The bridge checks each call of a response before the scaffold gets it,
        once per proposal, as the host tool it runs (`reviewed_calls`): under
        the model's call id, with the host tool's name and the arguments
        approval left. It checks each run's result after the run, as the
        service delivered it, which replay rebuilds from the `ToolEvent`'s
        result as the service converts it (`delivered_host_tool_content()`);
        its step is
        keyed by the id the run has (`execution_id`, else the call id), as is
        its `tool_call` step for its proposal's first run.
        """
        event = call.event
        proposal = call.proposal
        assistant = call.assistant
        assert proposal is not None and assistant is not None
        before_span = call.before_span
        after_span = call.after_span
        approval = self._run_approval(call)
        approver_modified = (
            approval.modified
            if approval is not None and approval.decision == "modify"
            else None
        )
        modify = self._sentinel_modify(before_span, event)
        if modify is None:
            arguments = event.arguments
        elif approver_modified is not None:
            arguments = approver_modified.arguments
        else:
            arguments = _reviewed_arguments(proposal)
        before_call = replace(proposal, function=event.function, arguments=arguments)
        shown = approval.view if approval is not None else None
        if modify is None:
            before_view = ToolCallView(
                context=shown.context
                if shown is not None and approver_modified is None
                else None,
                call=event.view or _default_view(before_call),
            )
        else:
            # a sentinel's modify replaced the event's view with the modified
            # call's, and the tool's viewer is not in the log
            before_view = ToolCallView(
                call=shown.call
                if shown is not None and approver_modified is None
                else None
            )
        producer = self._producer(call.producer)
        conversation = call.conversation
        assistant_id = assistant.id or ""
        assistant_text = self._text(assistant)
        if call.first_run:

            def build_before() -> None:
                step = before_tool_call(
                    conversation=conversation,
                    message=assistant_text,
                    message_id=assistant_id,
                    call=before_call,
                    view=before_view,
                    producer=producer,
                    agent_messages=None,
                    record=self._record(conversation),
                )
                self._built(event.id, "tool_call", step, before_span, True)

            # checked once its model call returned, before the scaffold got it
            self._at_point(
                self._cut(before_span, (call.produced_at, 3)), call.seq, build_before
            )
            self._settle_at_end(before_span)
        ran = after_span is not None or (
            (
                event.error is None
                or event.error.type not in ("parsing", "approval", "cancelled")
            )
            and not event.failed
            and not event.pending
        )
        if not ran:
            return
        after_call = replace(
            modify if modify is not None else before_call,
            function=event.function,
            arguments=event.arguments,
        )
        # as the service delivered it (an error's content is the tool's),
        # answering the id the run has; under the agent's tool message's id
        # where the bridge linked it, else, so that replay is deterministic,
        # its event's
        result = ChatMessageTool(
            id=event.message_id or event.uuid,
            content=cast(str | list[Content], event.result)
            if event.error is not None
            else delivered_host_tool_content(event.result),
            tool_call_id=event.id,
            function=event.function,
            error=event.error,
        )
        truncated = self._truncated(event)

        def build_after() -> None:
            step = after_tool_call(
                conversation=conversation,
                message=assistant_text,
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
            self._built(event.id, "tool_result", step, after_span, True)

        after_cut = self._cut(after_span, (end if end is not None else call.index, 3))
        self._at_point(after_cut, call.seq + 2, build_after)
        self._settle_at_end(after_span)

    def _run_approval(self, call: _Call) -> ApprovalEvent | None:
        """The last approval recorded for a host call's proposal between its model call and its run, by the call's id and the run its proposal was handed as (#6370)."""
        proposal = call.proposal
        assert proposal is not None
        handed = self.runs.get((call.produced_at, proposal.id), call.event.id)
        found = None
        for index, approval in self.run_approvals.get((proposal.id, handed), []):
            if call.produced_at < index < call.index:
                found = approval
        return found

    def _imported_tool_steps(self, generates: list[_Generate]) -> None:
        """An imported transcript's tool steps, from its messages, each placed after the turn that made it.

        Its messages are one conversation, taken from the model calls
        `messages_from` names, and keep one id per message across them and
        the model calls' inputs and outputs (Scout's importers since #753). So
        each assistant message is joined by its id to the turn whose output it
        is: its tool steps follow that turn, with its input, tools,
        conversation and record. A message no one turn made is placed after
        the last message before it that one did, or before the first turn,
        in that message's conversation, else the conversation of the calls
        `messages_from` names, with no input, matched by heuristic: after
        the turn before the first whose input is longer than its position in
        the messages, where that is later. A call's
        result is the tool message answering its id before the next assistant
        message with tool calls. A call no message holds (a sub-agent's, or
        one in a turn the messages left out) has no tool steps, and the
        transcript's tool events are not read.
        """
        made: dict[str, list[_Generate]] = {}
        for group in generates:
            output = group.attempts[-1][1].output
            if output.choices and output.message.id is not None:
                made.setdefault(output.message.id, []).append(group)
        conversation = next(
            (
                self._conversation(event)
                for event in self.events
                if isinstance(event, ModelEvent) and event.uuid in self.messages_from
            ),
            self.spans.conversation(None),
        )
        place = (generates[0].attempts[0][0], 0) if generates else (len(self.events), 1)
        # where no id places a message: its conversation's turns, and the
        # longest input of each and those before it
        turns = [g for g in generates if g.conversation == conversation]
        longest = list(
            accumulate((len(self._input(g.attempts[0][1])) for g in turns), max)
        )
        answers: dict[int, dict[str, ChatMessageTool]] = {}
        current: dict[str, ChatMessageTool] | None = None
        for position, message in enumerate(self.messages):
            if isinstance(message, ChatMessageAssistant) and message.tool_calls:
                current = answers[position] = {}
            elif (
                isinstance(message, ChatMessageTool)
                and message.tool_call_id is not None
                and current is not None
            ):
                current.setdefault(message.tool_call_id, message)
        for position, message in enumerate(self.messages):
            if not isinstance(message, ChatMessageAssistant):
                continue
            makers = made.get(message.id) if message.id is not None else None
            producer: ModelEvent | None = None
            if makers is not None and len(makers) == 1:
                index, producer = makers[0].attempts[-1]
                place = (index, 3)
                conversation = makers[0].conversation
            else:
                # after the turn before the first whose input is longer than
                # the message's position, where the messages extend each
                # turn's input, and never before a message placed earlier
                later = bisect_right(longest, position)
                if later > 0:
                    place = max(place, (turns[later - 1].attempts[-1][0], 3))
            for call in message.tool_calls or []:
                self._message_call(
                    message,
                    call,
                    answers[position].get(call.id),
                    conversation,
                    place,
                    producer,
                )

    def _message_call(
        self,
        assistant: ChatMessageAssistant,
        call: ToolCall,
        result: ChatMessageTool | None,
        conversation: str,
        at: tuple[int, int],
        made_by: ModelEvent | None,
    ) -> None:
        """A call's tool steps from the messages holding it and its answer (`_imported_tool_steps`)."""
        view = ToolCallView(call=call.view)
        message_id = assistant.id or ""
        text = self._text(assistant)
        producer = self._producer(made_by)
        by_id = made_by is not None
        seq = self._next_seq(3)

        def build_before() -> None:
            step = before_tool_call(
                conversation=conversation,
                message=text,
                message_id=message_id,
                call=call,
                view=view,
                producer=producer,
                agent_messages=None,
                record=self._record(conversation),
            )
            self._built(call.id, "tool_call", step, None, by_id)

        self._at_point(at, seq, build_before)
        if result is None:
            return
        answer = result

        def build_after() -> None:
            step = after_tool_call(
                conversation=conversation,
                message=text,
                message_id=message_id,
                call=call,
                view=view,
                result=answer,
                output=None,
                truncated=None,
                producer=producer,
                agent_messages=None,
                record=self._record(conversation),
            )
            self._built(call.id, "tool_result", step, None, by_id)

        self._at_point(at, seq + 2, build_after)

    def _tool_span_of(
        self,
        key: tuple[SentinelStage, str],
        after: int,
        before: int | None = None,
        *,
        ending: bool = False,
    ) -> str | None:
        """The first native check with this tool step id that no call has taken and begins between the events at `after` and `before`.

        With `ending`, a failed call takes a result check only when that check
        itself failed or terminated.
        """
        spans = self.tool_spans.get(key, [])
        for at, span in enumerate(spans):
            position = self.begins[span][0]
            if position > after and (before is None or position < before):
                if ending and not self._ended_call(span):
                    return None
                return spans.pop(at)
        return None

    def _ended_call(self, span: str) -> bool:
        """Whether the result check failed or decided to terminate."""
        return span in self.failed or any(
            event.kind == "decision"
            and event.status == "reported"
            and event.action == "terminate"
            for event in self.span_events.get(span, [])
        )

    def _settle_unbuilt_checks(self) -> None:
        """Settle the tool checks no step is built for, then warn once for each kind."""
        for (_, call_id, _), spans in self.bridge_spans.items():
            for span in spans:
                self._settle_at_end(span)
                self.skipped.append(call_id)
        unmatched: list[str] = []
        for (_, call_id), spans in self.tool_spans.items():
            for span in spans:
                self._settle_at_end(span)
                unmatched.append(call_id)
        if self.skipped:
            logging.getLogger(__name__).warning(
                "Replay skipped the tool steps of calls an agent bridge checked or "
                "ran (%s): the log does not link each of them to the model call "
                "that made it and the run that answered it.",
                ", ".join(dict.fromkeys(self.skipped)),
            )
        if unmatched:
            logging.getLogger(__name__).warning(
                "Replay found tool checks under call id(s) %s that match no tool "
                "call in the log: their steps are not rebuilt.",
                ", ".join(dict.fromkeys(unmatched)),
            )

    def _checks_tool_calls(self, event: ToolEvent, producer: ModelEvent | None) -> bool:
        """Whether live checked the calls a model call produced, inferred from the region the model call was made in.

        Live decides by the region that runs the call (`checks_tool_calls()` in `call_tool`), which the log does not record, so a call run in a region other than the one its producer was made in is replayed by its producer's. For a producer without a recorded origin, continuity may reject its model turn but cannot cancel tool checks that already ran in an agent, tool, or setup region. A call no model call produced (a pre-filled message) is taken as checked, unless it ran in the scorers' phase, whose scope is final live.
        """
        if producer is None:
            return not self._scoring(event)
        if producer.origin is not None:
            return producer.origin in _NON_FINAL
        return (
            not self._scoring(producer) and not self._region(producer.span_id).sentinel
        )

    # ---- origins the log does not record

    def _origin(self, event: ModelEvent) -> str:
        if event.origin is not None:
            return event.origin
        if self._inferred is None:
            self._inferred = self._infer_origins()
        return self._inferred.get(id(event), "agent")

    def _infer_origins(self) -> dict[int, str]:
        # calls known not to be the agent's turns by their region, and
        # compactions there, are utility to the timeline: a scorer's, a tool's
        # or a sentinel's calls would otherwise move the agent's thread or set
        # the prompt its turns are classified by
        known: dict[int, str] = {}
        outside: set[int] = set()
        phased = _records_phases(self.events)
        for event in self.events:
            if not isinstance(event, ModelEvent | CompactionEvent):
                continue
            region = self._region(event.span_id)
            if self._scoring(event):
                # live, the scorers' scope is final: nothing inside it, a tool
                # or an agent, changes it
                origin: str | None = "scorer"
            elif region.kind == "tool":
                origin = "tool"
            elif region.phase == "init" or (region.phase is None and phased):
                origin = "setup"
            else:
                origin = None
            if origin is not None or region.sentinel:
                outside.add(id(event))
            if origin is not None:
                known[id(event)] = origin
        timeline = _timeline_build(
            self.events,
            message_pool=self.pool,
            continuity=True,
            outside=outside,
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
        for event in self.events:
            if not isinstance(event, ModelEvent) or event.origin is not None:
                continue
            inferred[id(event)] = known.get(
                id(event), "helper" if id(event) in utility else "agent"
            )
        return inferred

    def _scoring(self, event: Event) -> bool:
        """Whether `event` was recorded in the scorers' phase, under the top-level `scorers` span."""
        return self._region(event.span_id).phase == "scorers"

    def _region(self, span_id: str | None) -> _Region:
        found = self._regions.get(span_id)
        if found is not None:
            return found
        if self._span_begins is None:
            self._span_begins = {
                e.id: e for e in self.events if isinstance(e, SpanBeginEvent)
            }
        begin = self._span_begins.get(span_id) if span_id is not None else None
        if begin is None:
            found = _Region(kind=None, phase=None, sentinel=False)
        else:
            parent = self._region(begin.parent_id)
            found = _Region(
                kind=begin.type
                if begin.type in (AGENT_SPAN_TYPE, "tool")
                else parent.kind,
                phase=begin.name
                if begin.parent_id is None
                and begin.name in ("init", "solvers", "scorers")
                else parent.phase,
                sentinel=parent.sentinel or begin.type == "sentinel",
            )
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
        by_id: bool,
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
                matched="ids" if by_id else "heuristic",
            )
        )

    def _settle_at_end(self, span: str | None) -> None:
        """Publish the `human()` decisions of the step checked in `span` when the span ends, as live publishes them once the step settles, unless the invocation raised or was cancelled, which live records as an `error` or `cancelled` event at the root."""
        if span is None or span not in self.ends:
            return
        self._at(self.ends[span], 2, lambda: self._settle(span))

    def _settle(self, span: str) -> None:
        from inspect_sentinel._integration import kept_human_decision, supersedes

        events = self.span_events.get(span, [])
        if span in self.failed or not events:
            return
        built = self.span_steps.get(span)
        if built is not None:
            conversation = built[0].conversation
        else:
            conversation = self._skipped_conversation(span, events)
        kept: list["HumanDecision"] = []
        for event in events:
            if event.kind != "decision" or event.action is None:
                continue
            reported = _reported(event)
            if event.status == "reported":
                if built is not None:
                    decision = kept_human_decision(
                        event.factory, built[0], built[1], reported
                    )
                else:
                    decision = _unbuilt_tool_decision(event, reported)
                if decision is not None:
                    kept.append(decision)
            elif event.status == "superseded":
                kept = [k for k in kept if not supersedes(event.path, reported, k)]
        if kept:
            self._record(conversation).publish(kept)

    # ---- helpers

    def _skipped_conversation(self, span: str, events: list[SentinelEvent]) -> str:
        """The conversation of a bridge's check that replay skips: where a stored timeline places its decisions, else its producer's.

        A bridge checks a call in the conversation of the model call that proposed it (`SentinelEvent.conversation`), which the check's span need not be in.
        """
        if self.timeline is not None:
            for event in events:
                found = self.timeline.get(_event_key(event))
                if event.kind == "decision" and found is not None:
                    return found
        recorded = events[0].conversation
        begin = self.begins[span][0]
        for index in reversed(self.proposed.get(events[0].step_id, [])):
            producer = self.events[index]
            if index < begin and self.spans.conversation(producer.span_id) == recorded:
                return self._conversation(producer)
        return recorded

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
        return False if self.eval_info.inspect_ai_version is not None else None

    def _result(self, event: ToolEvent) -> ChatMessageTool:
        if event.message_id is not None:
            # code can edit a tool message in place, keeping its id: the copy
            # holding the event's result is what the call produced
            copies = [
                message
                for message in self._messages_by_id_all().get(event.message_id, [])
                if isinstance(message, ChatMessageTool)
            ]
            result = jsonable_python(event.result)
            found = next(
                (
                    message
                    for message in copies
                    if json_equal(jsonable_python(message.content), result)
                ),
                copies[0] if copies else None,
            )
            if found is not None:
                return found
        return ChatMessageTool(
            id=event.message_id,
            content=cast(str | list[Content], event.result),
            tool_call_id=event.id,
            function=event.function,
            error=event.error,
        )

    def _proposal_by_id(self, event: ToolEvent) -> _Proposal | None:
        """The model call that proposed a call, by the message id its event records (`call_message_id`).

        None where the event records none (a log from before #6143, or a call
        the bridge could not verify), or where the id is not one earlier model
        call's output holding exactly one call under the call's id: a cached
        output reused by several model calls has one id.
        """
        call_id = _proposal_id(event)
        message_id = event.call_message_id
        if message_id is None or call_id is None:
            return None
        found = self.outputs.get(message_id, [])
        if len(found) != 1:
            return None
        producer = cast(ModelEvent, self.events[found[0]])
        message = producer.output.choices[0].message
        calls = [c for c in message.tool_calls or [] if c.id == call_id]
        if len(calls) != 1:
            return None
        return _Proposal(
            found[0], message, producer, calls[0], self._conversation(producer)
        )

    def _prefilled_by_id(
        self, event: ToolEvent
    ) -> tuple[ChatMessageAssistant, ToolCall] | None:
        """A call no model call produced (a pre-filled message): the message holding it, by the id its event records, and the call."""
        call_id = _proposal_id(event)
        message_id = event.call_message_id
        if message_id is None or call_id is None or message_id in self.outputs:
            return None
        for message in self._messages_by_id_all().get(message_id, []):
            if isinstance(message, ChatMessageAssistant):
                calls = [c for c in message.tool_calls or [] if c.id == call_id]
                if len(calls) == 1:
                    return message, calls[0]
        return None

    def _messages_by_id_all(self) -> dict[str, list[ChatMessage]]:
        if self._messages_by_id is None:
            found: dict[str, list[ChatMessage]] = {}
            for message in [*self.pool, *self.messages]:
                if message.id is not None:
                    found.setdefault(message.id, []).append(message)
            self._messages_by_id = found
        return self._messages_by_id

    def _text(self, message: ChatMessageAssistant) -> str:
        # a message with several text parts joins them on each read, and
        # replay keeps every step
        cached = self._texts.get(id(message))
        if cached is None or cached[0] is not message:
            cached = self._texts[id(message)] = (message, message.text)
        return cached[1]

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
                and json_equal(recorded.modified.arguments, event.arguments)
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

    def _approval_decision(
        self,
        approval: ApprovalEvent,
        conversation: str,
        point: tuple[int, int],
        seq: int,
    ) -> None:
        if approval.approver not in self.human_approvers:
            return
        decided = _approval_report(approval)
        if decided is None:
            return
        from inspect_sentinel import HumanDecision

        decision = HumanDecision(
            stage="tool_call",
            step_id=approval.call.id,
            call_ids=(approval.call.id,),
            decided=decided,
        )
        self._at_point(
            point,
            seq,
            lambda: self._record(conversation).publish([decision]),
        )


def _unbuilt_tool_decision(
    event: SentinelEvent, reported: Any
) -> "HumanDecision | None":
    """What live kept of a `human()` decision at a tool step replay does not rebuild, as `kept_human_decision` keeps it."""
    from inspect_sentinel import HumanDecision

    if event.factory != _HUMAN_FACTORY:
        return None
    assert event.stage in ("tool_call", "tool_result")
    return HumanDecision(
        stage=event.stage,
        step_id=event.step_id,
        call_ids=(event.step_id,),
        decided=reported,
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


# a PEP 440 version, as `packaging` parses it (not an inspect_ai dependency)
_VERSION = re.compile(
    r"v?(?:(?P<epoch>\d+)!)?(?P<release>\d+(?:\.\d+)*)"
    r"(?P<pre>[-_.]?(?:a|b|c|rc|alpha|beta|pre|preview)[-_.]?\d*)?"
    r"(?P<post>-\d+|[-_.]?(?:post|rev|r)[-_.]?\d*)?"
    r"(?P<dev>[-_.]?dev[-_.]?\d*)?"
    r"(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?",
    re.IGNORECASE,
)


def _before_phase_spans(version: str | None) -> bool:
    """Whether this Inspect version predates the `solvers` and `scorers` spans (0.3.100)."""
    if version is None:
        return False
    parsed = _VERSION.fullmatch(version.strip())
    if parsed is None or int(parsed["epoch"] or 0) > 0:
        return False
    release = [int(part) for part in parsed["release"].split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    if release != [0, 3, 100]:
        return release < [0, 3, 100]
    return bool(parsed["pre"] or parsed["dev"]) and not parsed["post"]


def _records_approval_decisions(version: str | None) -> bool:
    """Whether this log can reconstruct human decisions from approval events."""
    if version is None:
        return False
    parsed = _VERSION.fullmatch(version.strip())
    if parsed is None:
        return False
    if int(parsed["epoch"] or 0) > 0:
        return True
    release = [int(part) for part in parsed["release"].split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    if release != [0, 3, 277]:
        return release > [0, 3, 277]
    return not parsed["pre"] and (not parsed["dev"] or bool(parsed["post"]))


def _event_key(event: Event) -> object:
    return event.uuid if event.uuid is not None else id(event)


def _timeline_conversations(timeline: Timeline) -> dict[object, str]:
    """The conversation of each event a stored timeline holds."""
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


def _rekey(
    conversations: dict[object, str],
    events: Sequence[Event],
    condensed: Sequence[Event],
) -> None:
    """Move the conversation of each uuid-less event that condensing replaced to its replacement."""
    for event, replacement in zip(events, condensed, strict=True):
        if event is not replacement and event.uuid is None:
            found = conversations.pop(id(event), None)
            if found is not None:
                conversations[id(replacement)] = found


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


def _proposal_id(event: ToolEvent) -> str | None:
    """The model's id for the call an event ran: a sandbox bridge's host call records it as `proposal_id` (#6370), since the scaffold may be handed the call under another id."""
    if not _bridged(event):
        return event.id
    assert event.metadata is not None
    bridge = event.metadata["bridge"]
    proposal_id = bridge.get("proposal_id") if isinstance(bridge, dict) else None
    return proposal_id if isinstance(proposal_id, str) else None


def _reviewed_arguments(call: ToolCall) -> dict[str, Any]:
    """The arguments the bridge reviews a call with: a dispatcher call (`call_mcp_tool`) stands for its target, with the target's arguments (`_dispatched_call`)."""
    target = call.arguments.get("Arguments")
    if call.function == "call_mcp_tool" and isinstance(target, dict):
        return cast(dict[str, Any], target)
    return call.arguments


def _bound_result_checks(
    calls: list[_Call], by_a_turn: Callable[[_Call], bool]
) -> None:
    """Bound where each native call's result check can begin: before the agent turn that proposed a later call under its id in its conversation.

    Live checks a call's result before its batch returns, so before the
    conversation's next turn; without the bound, a call that never reached its
    result check (its arguments failed validation) took a later call's. Only a
    turn bounds it: a reviewer's or a tool's own model call can run between a
    call's tool span and its result check.
    """
    groups: dict[tuple[str, str], list[_Call]] = {}
    for call in calls:
        if not _bridged(call.event) and by_a_turn(call):
            groups.setdefault((call.event.id, call.conversation), []).append(call)
    bounds: dict[int, int | None] = {}
    for group in groups.values():
        # the nearest later call's producer, and the nearest after that one
        nearest: int | None = None
        beyond: int | None = None
        for call in reversed(group):
            produced = call.produced_at
            if nearest is not None and nearest > produced:
                bounds[call.index] = nearest
            elif nearest == produced:
                bounds[call.index] = beyond
            if nearest != produced:
                beyond, nearest = nearest, produced
    # a call no turn produced (a pre-filled message, a reviewer's own call) is
    # bounded by the first turn after it that proposed its id
    turns = {
        key: sorted(call.produced_at for call in group) for key, group in groups.items()
    }
    for call in calls:
        if call.index in bounds:
            call.until = bounds[call.index]
        elif not _bridged(call.event) and not by_a_turn(call):
            later = turns.get((call.event.id, call.conversation), [])
            at = bisect_right(later, call.index)
            call.until = later[at] if at < len(later) else None


def _bridged(event: ToolEvent) -> bool:
    """Whether a sandbox bridge ran the call on the host."""
    return event.metadata is not None and "bridge" in event.metadata


def _approval_refused(approval: ApprovalEvent | None) -> bool:
    """Whether the approver's recorded decision kept the call from running (`apply_tool_approval`)."""
    return approval is not None and not (
        approval.decision == "approve"
        or (approval.decision == "modify" and approval.modified is not None)
    )
