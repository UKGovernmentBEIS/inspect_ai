import hashlib
import json
import struct
from collections import OrderedDict, deque
from contextlib import AbstractContextManager, ExitStack, nullcontext
from copy import deepcopy
from dataclasses import dataclass, is_dataclass, replace
from dataclasses import fields as dataclass_fields
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from functools import cached_property, partial
from itertools import chain
from logging import getLogger
from pathlib import PurePath
from typing import (
    TYPE_CHECKING,
    AbstractSet,
    Any,
    Awaitable,
    Callable,
    Hashable,
    Iterable,
    Iterator,
    NamedTuple,
    Sequence,
    TypeVar,
)
from uuid import UUID

import anyio
from pydantic import BaseModel
from pydantic_core import to_jsonable_python
from shortuuid import uuid

from inspect_ai._sentinel._context import (
    SentinelFailure,
    active_sentinel,
    checks_tool_calls,
)
from inspect_ai._sentinel._conversation import current_conversation
from inspect_ai._util._async import tg_collect
from inspect_ai._util.content import (
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._bridge.types import AgentBridge, BridgedToolId
from inspect_ai.model._call_tools import (
    decisive_sentinel_exception,
    repeated_call_ids,
)
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._providers._google_computer_use_name import (
    GEMINI_COMPUTER_ACTIONS,
)
from inspect_ai.tool._tool import Tool, ToolResult
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallView,
    ToolCallViewer,
    ToolCallViewError,
    resolve_tool_call_view,
)
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._span import in_agent_span

if TYPE_CHECKING:
    from inspect_sentinel import Decision

    from inspect_ai.event._model import ModelEvent

logger = getLogger(__name__)

T = TypeVar("T")

_MAX_PROPOSALS = 1000

# A longer model id is handed over under a fresh one (`_Handouts.reused`):
# reserving its Gemini CLI echoes reads every part of it after a `__`, which is
# quadratic in its length. Providers' ids are a few dozen characters.
MAX_CALL_ID_LENGTH = 256

# a check with no proposal's context has no message that made the call: the
# assistant message a request carries the call in is the scaffold's
_NO_MESSAGE_ID = ""

# The fields of the step a result check sends the protocol (`AfterToolCall`)
# that its digest (`_Steps`) covers, and those it leaves out, with why.
STEP_DIGEST_FIELDS = frozenset(
    {
        "conversation",
        "message",
        "message_id",
        "call",
        "view",
        "result",
        "input",
        "tools",
        "tool_choice",
    }
)
STEP_DIGEST_EXCLUDED = {
    "output": "the result's own content (`_output`), which the result covers: "
    "the tool's return value never reaches the bridge",
    "truncated": "None in every bridge check: only the scaffold or the host "
    "tool's execution knows the cut",
    "history": "the conversation's record when the check runs, which grows with "
    "every step, so a replay would never be the same step",
    "human_decisions": "as `history`",
    "agent_messages": "None in every bridge check (`bridge_request`)",
}


@dataclass(frozen=True, eq=False)
class Produced:
    """The generation that produced a bridged call, and the agent span it ran in."""

    event: "ModelEvent"
    """What the model was sent (`input`, `tools`, `tool_choice`)."""

    agent_span_id: str | None
    """The agent span current during the generation: the call's conversation."""

    def scope(self) -> AbstractContextManager[None]:
        return in_agent_span(self.agent_span_id)

    @cached_property
    def digest(self) -> str:
        """The digest of what a step reads of the generation (`input`, `tools`, `tool_choice`).

        Computed once, so the steps of every result of its calls cost nothing
        in the length of its input.
        """
        return _parts_digest(
            _serialized(self.event.input),
            _serialized(self.event.tools),
            _serialized(self.event.tool_choice),
        )


class SentinelCheck(NamedTuple):
    call: ToolCall
    """The call the steps show (the model's id; a dispatched call's target)."""

    viewer: ToolCallViewer | None
    message: str

    message_id: str | None
    """The id of the assistant message that made the call."""

    producer: Produced | None = None
    """The generation that produced the call, if the bridge knows it; the steps
    take what the model was sent from it, and its conversation, and without it
    have no input and the bridge's current conversation."""

    alternatives: tuple["SentinelCheck", ...] = ()
    """Checks for other host tools denoted by the same handed call."""

    target: BridgedToolId | None = None
    """The bridged tool the check is for, or None for a call no bridged tool serves."""


class HandedTarget(NamedTuple):
    """A target a handed call resolved to (`handed_targets`)."""

    target: BridgedToolId | None
    """As `SentinelCheck.target`."""

    call: ToolCall
    """As `SentinelCheck.call`: the call its checks show."""


class _Target(NamedTuple):
    """A target a handout resolved to, kept for the sample (`_Handed.targets`)."""

    handout: str
    """The handed call (`_exact_key`)."""

    target: BridgedToolId | None
    """As `SentinelCheck.target`."""

    call: ToolCall
    """As `SentinelCheck.call`: the call its checks show, with its arguments
    as JSON carries them (`_as_json`), so a checkpoint keeps it exactly."""

    digest: str
    """The call as resolved, exactly (`_shown_key`): a target is another only
    with the same."""


class _Handed(NamedTuple):
    """What the bridge keeps for each call id it has handed to the scaffold."""

    function: str

    proposed: str | None
    """The call as the model proposed it (`_exact_key`), or None when several
    calls of its response shared the id."""

    handed: tuple[str, ...]
    """The call as handed over under the id, once for each set of arguments
    it was handed with (`_exact_key`): each is a handout of its own."""

    execution_id: str | None
    """The id of the call's latest handout, which its approvals, steps and host
    `ToolEvent`s record as their `execution_id`, or None for a call only in a
    rejected turn."""

    ambiguous: bool = False
    """Whether the call was handed out more than once, in any requests: a
    retry, a cache hit and another conversation alike. Which handout a
    result answers can't be told, then or after any later handout, so none
    of its results keeps a proposal's context (`_Handouts`); each is still
    checked as the targets its handouts resolved to."""

    forms: tuple[tuple[str, str], ...] = ()
    """The forms a request may show its handouts in, each a call as JSON
    carries it (`_call_key`) and the handout it is (`_exact_key`): the call
    as handed, and the form its dialect reads it back in where that differs
    (`read_back`). Handouts JSON carries alike share a form."""

    targets: tuple[_Target, ...] = ()
    """The targets each of its handouts resolved to, without their viewers or
    context, recorded while a sentinel is configured for the sample, active
    at the handout or not (`handed_targets`). A result under the id is
    checked as them whenever its proposal's checks are not used: the proposal
    is evicted or lost to a resume, the id is ambiguous or shared within a
    response, the sentinel was not active at the handout, or the call the
    request shows is none of its handouts (`_Handouts._checks`)."""

    latest: tuple[int, ...] = ()
    """The calls its latest response handed over under the id, in order, each
    as its handout's position in `handed`, where they were several handouts
    sharing the id; otherwise empty. A result whose call is none of the id's
    handouts is paired with them by position (`_HandoutIndex.of`)."""

    functions: tuple[str, ...] = ()
    """Every function handed over under the id, where they are several (calls
    of a response sharing it); otherwise empty: it is `function`. Gemini CLI
    may echo the id prefixed with any of their names
    (`_Handouts.wire_names`)."""


class _SavedHandouts(BaseModel):
    reserved_ids: list[str]
    handed: dict[str, _Handed]
    checked: list[str]
    """The digests of the steps whose checks passed (`_Steps`)."""

    inherited: list[str] = []
    """The conservative keys of the results the bridge started with (`inherited_result_keys`)."""

    def encoded(self) -> str:
        """The record as a checkpoint keeps it: JSON in ASCII, written here.

        A checkpoint's writer keeps such a string as it is. Values it
        serializes itself can change: NaN and the infinities become null, and
        a lone surrogate is escaped, or replaced in a key, so one call id can
        become another's. The record holds only values JSON carries exactly
        (`_as_json`), with NaN and the infinities as JSON's constants.
        """
        return json.dumps(self.model_dump())

    @classmethod
    def decoded(cls, encoded: str) -> "_SavedHandouts":
        return cls.model_validate(json.loads(encoded))


class _Result(NamedTuple):
    message: ChatMessageTool

    checks: tuple[SentinelCheck, ...]
    """The checks of every target the result may be of."""

    digests: tuple[str, ...]
    """The digest of each check's step (`_Steps`)."""

    views: tuple[ToolCallView | None, ...]
    """Each check's call's view, as its digest was taken of it; None where its
    viewer failed and the check rejects that."""

    execution_id: str | None = None
    """The handout whose result this is (`_Handed.execution_id`), or None
    where the bridge can't tell: an id handed out more than once or shared
    by calls of one response, or one it never handed out."""


class _Claim(NamedTuple):
    result: _Result

    owned: tuple[int, ...]
    """The checks this claim runs, by index: those whose steps no check passed,
    is running or failed."""

    event: anyio.Event
    """Set on release; the `running` entry of each owned step this claim took
    (one another claim already held stays that claim's)."""


class _Claimed(NamedTuple):
    owned: list[_Claim]
    waiting: list[anyio.Event]


class _ReadBack(NamedTuple):
    """An id's record as a reply's read-back forms are added to it (`_Handouts.read_back`)."""

    handed: frozenset[str]
    known: set[tuple[str, str]]
    added: list[tuple[str, str]]


@dataclass
class _Call:
    call: ToolCall
    text: str
    position: int

    @cached_property
    def key(self) -> str:
        return _call_key(self.call)


class _Handouts:
    """The calls a bridge has handed to the scaffold, and the checks of their results.

    A call is handed over under the model's id. Each handout is an execution
    with its own `execution_id`, identified by the id and the arguments it
    was handed with, exactly (`_exact_key`): a scaffold retry served from the
    model cache hands the same call over again, under the same id, and its
    result is that of the latest handout with the arguments the result's call
    has, the one the scaffold received. The result's call matches a handout
    as handed, or in the form its dialect reads it back in (a Gemini action
    for a `computer` call, say), compared as JSON carries it (`_call_key`): a
    scaffold may send a call back in another spelling. Handouts JSON carries
    alike (`0.0` and `-0.0`) are then several the call matches. For an id the
    bridge handed out, its record is the authority,
    not the call a request shows: a result whose call matches no handout of
    its id, or several, or one with no call in its request when the id was
    handed with several arguments, gets no proposal's context and is checked
    as every target the id's handouts resolved to: across responses, one
    handout may be another bridged tool's than the next. Calls of one
    response sharing an id are each a handout of it, with no proposal's
    context, and such a result under their id is instead paired by position:
    the nth after an assistant message is checked as the targets of the nth
    of those calls, and one past the last as the last's (`_HandoutIndex.of`),
    so N results of N calls sharing an id cost N checks. Only
    a result under an id the bridge never handed out (a scaffold that
    rewrites ids, or one answering no call) is checked as the call it answers
    in its request. A call handed out more than once
    is ambiguous, whether a retry or cache hit handed it out again or another
    conversation: the bridge can't tell those apart, as an identical request
    may be generated from other input (a filter's) or answer another
    conversation. Its results get no proposal's context from then on, after
    any resume too. Context is the generation and the proposing message; a
    result without it has neither (never the assistant message its request
    carries the call in, which is the scaffold's), and is still checked as
    the handout's targets (a dispatched or renamed call's bridged tool, with
    its viewer).

    A call gets a fresh id instead (`reused`) when the model's id can't name
    it: an empty id, one longer than `MAX_CALL_ID_LENGTH`, or one that already
    names another call (Claude Code drops a repeated id and the result under
    it). The ids handed over or
    rejected, with their calls, and the ids seen in requests
    (`reserved_ids`) are kept for the life of the bridge and in its
    checkpoint (`saved`), apart from the proposals (bounded).

    A result is checked when a request carries it to the model, whether the
    scaffold ran the tool or a bridged host tool did: the request holds the
    call's id, which a host tool's execution (an MCP call) does not, and the
    result as the model will see it. A host execution runs no check of its
    own (`execute_host_tool`).

    A result of a handout is checked as the handout's targets, with its
    proposal's checks, while the proposal is kept. The targets each handout
    of an id resolved to are kept for the sample and in its checkpoint
    (`_Handed.targets`), whether or not the sample's sentinel was active at
    the handout, so once the proposal is evicted or lost to a resume, or when
    there never was one, the result is checked as them with the request's
    conversation and no model input, each with its bridged tool's viewer
    (`viewer`) or, without one, none; and a later handout of the call adds
    its targets to them. A sample with no sentinel records none: its results
    are never checked. A call handed out before any sentinel was configured
    is, if its result is reported once one is, checked as the call the
    request shows.

    A result is exempt from checking only if an identical check already
    passed: one whose step, as the protocol receives it, is the same
    (`_Steps`). A result's step is resolved first (its targets, any context
    removed, the fallback once its proposal is gone), so a result needing a
    check no step covered (another target, other arguments, another
    conversation, no context, other content) gets one, while an unchanged
    replay is the same step and is not checked again. Each target's step is
    its own: a result checked as more targets than before runs only the new
    ones. A step whose check is running (another request's) is waited for,
    and one whose check failed fails again. The digests of passed steps are
    kept in the checkpoint (`checked`); proposals are not, so after a resume
    a result gets its targets' steps without context and is checked again,
    as after its proposal's eviction.

    The results in the state the bridge starts with were in the agent's
    conversation before the bridge ran, and are not checked again, as a native
    agent handed a conversation does not check its results again
    (`inherited_result_keys`). Each is recorded under its conservative key,
    taken when the bridge is first constructed and kept in its checkpoint, so
    a result reported with other content (including one changed in place
    since, before or after a resume) is checked. The key applies only to a
    result under an id the bridge never handed over: their call ids are
    reserved at the same point (`history_ids`), so none of the bridge's own
    results is one.

    Held by its bridge, since a failure's traceback references the bridge.
    """

    def __init__(
        self,
        saved: _SavedHandouts,
        viewer: Callable[[BridgedToolId], ToolCallViewer | None] = lambda _: None,
    ) -> None:
        self.viewer = viewer
        """The viewer of a bridged tool the bridge serves, if any."""
        self.handed: dict[str, _Handed] = dict(saved.handed)
        self.reserved_ids: set[str] = set(saved.reserved_ids)
        # by call id (`wire_names`)
        self._wire_names: dict[str, frozenset[str]] = {}
        # by call id and handout (`_exact_key`)
        self.proposals: OrderedDict[tuple[str, str], SentinelCheck] = OrderedDict()
        # step digests (`_Steps`)
        self.checked: set[str] = set(saved.checked)
        self.inherited: frozenset[str] = frozenset(saved.inherited)
        self.running: dict[str, anyio.Event] = {}
        self.failed: dict[str, Exception] = {}

    def saved(self) -> _SavedHandouts:
        """What a resumed bridge needs to hand over calls and match results as this one does.

        Proposals hold their generation and viewer, so a resumed bridge
        matches a result as it would after the proposal's eviction. A check
        that was running or failed is made again.
        """
        return _SavedHandouts(
            reserved_ids=sorted(self.reserved_ids),
            handed=dict(self.handed),
            checked=sorted(self.checked),
            inherited=sorted(self.inherited),
        )

    def reserve(self, ids: Iterable[str]) -> None:
        self.reserved_ids.update(ids)

    def wire_names(self, call_id: str) -> frozenset[str] | None:
        """The names a Gemini scaffold can send the calls handed over under `call_id` as; None for an id the bridge neither handed over nor proposed.

        Those of every function handed over under it (`_Handed.functions`):
        calls of a response sharing an id may be to several. Kept per id, so
        reading many calls sharing one is linear in them.
        """
        handed = self.handed.get(call_id)
        if handed is None:
            return None
        names = self._wire_names.get(call_id)
        if names is None:
            functions = handed.functions or (handed.function,)
            names = frozenset().union(*map(wire_names, functions))
            self._wire_names[call_id] = names
        return names

    def reused(
        self,
        call_id: str,
        calls: Sequence[ToolCall],
        history: AbstractSet[str],
        siblings: AbstractSet[str] = frozenset(),
    ) -> bool:
        """Whether the model's id for `calls` (those of a response under it) names another call.

        An id the bridge proposed before (handed over or rejected) names
        another call when it was another function or arguments as proposed
        (`_exact_key`), or several calls. The same call proposed again keeps its id: a retry of
        its request (served from the model cache, or after a rejection), or
        the call again in a later turn or another conversation, whose results
        then get no proposal's context (`hand_over`). Any other id names
        another call when it is empty, in the request's conversation
        (`history`, `history_ids`) or reserved: the bridge can't tell which
        call it was. So
        does an id a Gemini CLI echo (`name__id`) can't tell apart from a
        reserved or handed one, or one of the response's other calls
        (`siblings`), in either direction: an echo of one of `calls`
        (`_echoes`) that is such an id, or an id of `calls` that may be an
        echo of one (`_echoed`). An echo is taken under every name its call
        can be handed over under, as approval and the sentinel review the
        call after its id is chosen. So does an id longer than
        `MAX_CALL_ID_LENGTH`, which bounds that work.
        """
        if not call_id or len(call_id) > MAX_CALL_ID_LENGTH:
            return True
        if any(
            echo in self.reserved_ids or echo in self.handed or echo in siblings
            for echo in chain(
                (echo for call in calls for echo in _echoes(call)),
                _echoed(call_id),
            )
        ):
            return True
        handed = self.handed.get(call_id)
        if handed is None:
            return call_id in history or call_id in self.reserved_ids
        return (
            handed.proposed is None
            or len(calls) > 1
            or _exact_key(calls[0]) != handed.proposed
        )

    def hand_over(
        self,
        proposed: Sequence[ToolCall],
        handed: Sequence[ToolCall],
        checks: Sequence[SentinelCheck] | None,
        resolved: Sequence[Sequence[HandedTarget]] | None = None,
        execution_ids: Sequence[str] | None = None,
    ) -> None:
        """Record a response's calls as handed over, each a new execution.

        `proposed` are the calls as the model proposed them, `handed` as
        approval gave them, and `checks` their `tool_result` checks, in order
        (None without an active sentinel). `execution_ids` are the ids the
        calls' approvals and `tool_call` steps were recorded under, one for
        each, in order (fresh ones without them). `resolved` are the targets each
        handed call resolved to (`handed_targets`), which a response handed
        over while the sample's sentinel is not active has no checks to give
        (None when the sample has no sentinel). Each handout's targets are
        recorded (`_Handed.targets`), for calls sharing an id within the
        response too: each is a handout of the id, which is ambiguous. So is
        a call whose id was handed out before (`_Handed.ambiguous`), and its
        proposal checks every target its handouts resolved to.
        """
        by_id: dict[str, list[int]] = {}
        for index, call in enumerate(handed):
            by_id.setdefault(call.id, []).append(index)
        # one record per id, so calls sharing an id cost work linear in them
        for call_id, indexes in by_id.items():
            shared = len(indexes) > 1
            earlier = self.handed.get(call_id)
            previous = (
                earlier
                if earlier is not None and earlier.execution_id is not None
                else None
            )
            ambiguous = shared or (
                earlier is not None
                and (earlier.ambiguous or earlier.execution_id is not None)
            )
            handouts = dict.fromkeys(previous.handed if previous is not None else ())
            forms = dict.fromkeys(previous.forms if previous is not None else ())
            functions = dict.fromkeys(handed[index].function for index in indexes)
            targets = _Targets(previous.targets if previous is not None else ())
            keys = [_exact_key(handed[index]) for index in indexes]
            for index, key in zip(indexes, keys):
                handouts.setdefault(key)
                forms.setdefault((_call_key(handed[index]), key))
                if checks is not None:
                    targets.add(key, _check_targets(checks[index]))
                elif resolved is not None:
                    targets.add(key, resolved[index])
            positions = {key: position for position, key in enumerate(handouts)}
            last = indexes[-1]
            self.handed[call_id] = _Handed(
                handed[last].function,
                None if shared else _exact_key(proposed[last]),
                tuple(handouts),
                execution_ids[last] if execution_ids is not None else uuid(),
                ambiguous,
                tuple(forms),
                tuple(targets.records),
                tuple(positions[key] for key in keys)
                if shared and len(handouts) > 1
                else (),
                tuple(functions) if len(functions) > 1 else (),
            )
            self._wire_names.pop(call_id, None)
            if checks is None:
                continue
            if shared:
                for stale in [k for k in self.proposals if k[0] == call_id]:
                    del self.proposals[stale]
                continue
            key = keys[-1]
            check = checks[last]
            earlier_check = self.proposals.pop((call_id, key), None)
            if ambiguous and earlier_check is not None:
                check = _with_targets_of(check, earlier_check)
            self.proposals[(call_id, key)] = check
            while len(self.proposals) > _MAX_PROPOSALS:
                self.proposals.popitem(last=False)
                warn_once(
                    logger,
                    f"More than {_MAX_PROPOSALS} bridged tool calls have been "
                    "handed to the scaffold; the oldest proposal was dropped, so "
                    "the sentinel's tool_result check of a call handed over more "
                    f"than {_MAX_PROPOSALS} calls ago sees its targets and the "
                    "conversation that carries its result, and no model input.",
                )

    def propose(self, calls: Sequence[ToolCall]) -> None:
        """Record a response's calls under the ids they keep, before approval and the sentinel review them.

        So a concurrent request's call under one of the ids is another call's
        (`reused`), whether these are then handed over (`hand_over`) or
        rejected, when the model sees them but the scaffold never runs them.
        """
        shared = repeated_call_ids(calls)
        for call in calls:
            if call.id not in self.handed:
                key = _exact_key(call)
                self.handed[call.id] = _Handed(
                    call.function,
                    None if call.id in shared else key,
                    (key,),
                    None,
                )

    def read_back(self, handed: Sequence[ToolCall], read: Sequence[ToolCall]) -> None:
        """Record the form a dialect reads a reply's handed calls back in.

        `read` are the `handed` calls as the dialect parses the wire form it
        hands them over in: paired by id when it keeps them (Anthropic can
        place a call elsewhere), otherwise in order (Google reads them back
        under ids of its own); ignored unless there is one for each.
        """
        if len(read) != len(handed):
            return
        ids = [call.id for call in handed]
        by_id = {back.id: back for back in read}
        if len(set(ids)) == len(ids) == len(by_id) and by_id.keys() == set(ids):
            read = [by_id[id] for id in ids]
        # one pass over each id's record, so calls sharing an id cost work
        # linear in them
        adding: dict[str, _ReadBack | None] = {}
        for call, back in zip(handed, read, strict=True):
            back_key = _call_key(back)
            # the form a call is handed in is recorded with it (`hand_over`)
            if back_key == _call_key(call):
                continue
            if call.id not in adding:
                record = self.handed.get(call.id)
                adding[call.id] = (
                    _ReadBack(frozenset(record.handed), set(record.forms), [])
                    if record is not None
                    else None
                )
            forms = adding[call.id]
            if forms is None:
                continue
            pair = (back_key, _exact_key(call))
            if pair[1] not in forms.handed or pair in forms.known:
                continue
            forms.known.add(pair)
            forms.added.append(pair)
        for call_id, forms in adding.items():
            if forms is not None and forms.added:
                record = self.handed[call_id]
                self.handed[call_id] = record._replace(
                    forms=(*record.forms, *forms.added)
                )

    def claim(self, input: list[ChatMessage]) -> _Claimed:
        claimed = _Claimed([], [])
        steps = _Steps()
        taken: set[str] = set()
        for answer in _answers(input):
            result = self._result(input, answer, steps)
            if result is None:
                continue
            owned: list[int] = []
            for index, digest in enumerate(result.digests):
                # a step another of the request's results has is checked by it
                if digest in taken or digest in self.checked:
                    continue
                if digest in self.failed:
                    raise self.failed[digest]
                running = self.running.get(digest)
                if running is not None:
                    claimed.waiting.append(running)
                    continue
                taken.add(digest)
                owned.append(index)
            if owned:
                claimed.owned.append(_Claim(result, tuple(owned), anyio.Event()))
        for claim in claimed.owned:
            self._take(claim)
        return claimed

    def _take(self, claim: _Claim) -> None:
        for index in claim.owned:
            self.running.setdefault(claim.result.digests[index], claim.event)

    def _result(
        self,
        input: list[ChatMessage],
        answer: "_Answer",
        steps: "_Steps",
    ) -> _Result | None:
        """The checks an answer's result gets, with their steps' digests; None for an inherited result (`inherited`)."""
        message, found = answer.message, answer.found
        call_id = message.tool_call_id or ""
        handed = self.handed.get(call_id)
        if (
            handed is None
            and self.inherited
            and _unissued(message, found)[1] in self.inherited
        ):
            return None
        targets = (
            steps.handouts(call_id, handed).of(found, answer.nth)
            if handed is not None
            else None
        )
        # what the checks depend on besides the bridge's state, which a claim
        # doesn't change: the call answered, or the result's function without
        # one, and the handout the result is matched or paired with
        checks = steps.checks(
            (
                call_id,
                id(found),
                message.function if found is None else None,
                (targets.matched, targets.paired) if targets is not None else None,
            ),
            found,
            lambda: self._checks(call_id, handed, targets, found, message),
            input[found.position].id if found is not None else None,
        )
        result = steps.result(message)
        return _Result(
            message,
            checks.checks,
            tuple(_parts_digest(part, result) for part in checks.parts),
            checks.views,
            handed.execution_id
            if handed is not None and not handed.ambiguous
            else None,
        )

    def _checks(
        self,
        call_id: str,
        handed: _Handed | None,
        targets: "_HandoutTargets | None",
        found: _Call | None,
        message: ChatMessageTool,
    ) -> tuple[SentinelCheck, ...]:
        """The checks of a result under `call_id` answering `found` (`_Handouts`).

        For an id the bridge handed out, its record is the authority, not the
        call the request shows: the result is checked as `targets`
        (`_HandoutIndex.of`). A result whose call is one of the id's handouts
        has that handout's proposal's checks, or its recorded targets without
        context once the proposal is gone or the id is ambiguous. One whose
        call is none of them, or one several could be (the scaffold changed
        the call, or left it out of an id with several handouts), has
        recorded targets without context: every handout's, or one handout's
        where it is paired by position. Only a result under an id with no
        recorded target (one the bridge never handed out) is checked as the
        call the request shows.
        """
        if handed is not None and targets is not None:
            checks: list[SentinelCheck] = []
            proposal = (
                self.proposals.get((call_id, targets.matched))
                if targets.matched is not None
                else None
            )
            if proposal is not None:
                checks = [proposal, *proposal.alternatives]
                if handed.ambiguous:
                    checks = [_without_context(check) for check in checks]
            # a call handed out once has its proposal's targets; otherwise add
            # those of an evicted proposal or an earlier handout
            if proposal is None or handed.ambiguous:
                checks.extend(self._recorded(targets.recorded, checks))
            if checks:
                return tuple(checks)
        call = _unissued(message, found)[0]
        if found is None and handed is not None and handed.proposed is not None:
            call = ToolCall(id=call_id, function=handed.function, arguments={})
        return (SentinelCheck(call, None, "", _NO_MESSAGE_ID),)

    def _recorded(
        self, recorded: Sequence[_Target], checks: Sequence[SentinelCheck]
    ) -> list[SentinelCheck]:
        """Checks of a handout's `recorded` targets (`_Handed.targets`) that `checks` lack.

        Each with its bridged tool's viewer, if the bridge still serves one,
        and no context.
        """
        known = {(check.target, _shown_key(check.call)) for check in checks}
        rebuilt: list[SentinelCheck] = []
        for target in recorded:
            identity = (target.target, target.digest)
            if identity in known:
                continue
            known.add(identity)
            viewer = self.viewer(target.target) if target.target is not None else None
            rebuilt.append(
                SentinelCheck(
                    target.call, viewer, "", _NO_MESSAGE_ID, target=target.target
                )
            )
        return rebuilt

    async def check(self, bridge: AgentBridge, claim: _Claim) -> None:
        """Run the claim's checks, in order, recording each step as passed or failed."""
        result = claim.result
        for index in claim.owned:
            digest = result.digests[index]
            try:
                await _tool_result(
                    bridge,
                    result.checks[index],
                    result.message,
                    reject_on_viewer_error=len(result.checks) > 1,
                    view=result.views[index],
                    execution_id=result.execution_id,
                )
            except Exception as ex:
                self.failed.setdefault(digest, ex)
                raise
            self.checked.add(digest)

    def release(self, claim: _Claim) -> None:
        # a check that did not finish is claimed again by the next request
        # carrying its result
        for index in claim.owned:
            digest = claim.result.digests[index]
            if self.running.get(digest) is claim.event:
                del self.running[digest]
        claim.event.set()


def _without_context(check: SentinelCheck) -> SentinelCheck:
    """`check` with no proposal's context: no generation and no proposing message.

    The assistant message a request carries the call in is the scaffold's, so
    it stands in for neither. The check's targets and viewers are kept: they
    come from the handed call and the bridged tools, not from the generation.
    """
    return check._replace(message="", message_id=_NO_MESSAGE_ID, producer=None)


def _check_targets(check: SentinelCheck) -> list[HandedTarget]:
    """The targets a handed call's check covers: its own and its alternatives'."""
    return [
        HandedTarget(target.target, target.call)
        for target in (check, *check.alternatives)
    ]


class _Targets:
    """The target records of an id (`_Handed.targets`), added to in time linear in what is added."""

    def __init__(self, records: Iterable[_Target]) -> None:
        self.records = list(records)
        self._known = {
            (record.handout, record.target, record.digest) for record in self.records
        }

    def add(self, handout: str, resolved: Iterable[HandedTarget]) -> None:
        """Add the targets `handout` (`_exact_key`) resolved to that the id lacks.

        A target is another's only if its handout, its bridged tool and the
        call its checks show are the same exactly, so calls JSON carries
        alike (`0.0` and `-0.0`) each keep theirs.
        """
        for target in resolved:
            digest = _shown_key(target.call)
            identity = (handout, target.target, digest)
            if identity not in self._known:
                self._known.add(identity)
                self.records.append(
                    _Target(handout, target.target, _as_json(target.call), digest)
                )


class _HandoutTargets(NamedTuple):
    """The targets of an id's handouts a result is checked as (`_HandoutIndex.of`)."""

    matched: str | None
    """The handout (`_exact_key`) the result's call is, whose proposal's
    context applies; None for a result whose call is none, or could be
    several."""

    paired: str | None
    """The handout such a result is paired with by position, if any."""

    recorded: Sequence[_Target]
    """The recorded targets (`_Handed.targets`) of the handout, or of every
    handout of the id for a result neither matched nor paired."""


class _HandoutIndex:
    """An id's handouts and their targets (`_Handed`), indexed once per request, so results under an id handed out many times cost linear work."""

    def __init__(self, handed: _Handed) -> None:
        self._handed = handed.handed
        self._forms: dict[str, set[str]] = {}
        for form, key in handed.forms:
            self._forms.setdefault(form, set()).add(key)
        self._latest = [handed.handed[position] for position in handed.latest]
        self._all = handed.targets
        self._targets: dict[str, list[_Target]] = {}
        for target in handed.targets:
            self._targets.setdefault(target.handout, []).append(target)

    def of(self, found: _Call | None, nth: int) -> _HandoutTargets:
        """The targets a result answering `found` (the call in its request, if any) is checked as.

        Those of the handed call `found` is a form of (`_Handed.forms`): the
        call as JSON carries it, as handed or as its dialect reads it back;
        for a result with no call in its request, of the id's only handed
        call.

        Otherwise the scaffold changed the call or left it out, or several
        handouts match (calls JSON carries alike among them, which a
        request can't tell apart), and the result is checked as every
        handout's targets:
        handouts in separate responses may be of other bridged tools, and
        nothing tells which the result is of. That costs a check for each
        handout, so a result under an id several calls of one response
        shared (`_Handed.latest`) is instead paired by position, as `_answers`
        pairs results with a request's calls: the `nth` result (`_Answer.nth`)
        with the nth of those calls, and one past the last with the last.
        """
        if found is None:
            matches = set(self._handed) if len(self._handed) == 1 else set()
        else:
            matches = self._forms.get(found.key, set())
        if len(matches) == 1:
            [handout] = matches
            return _HandoutTargets(handout, None, self._targets.get(handout, ()))
        if self._latest:
            paired = self._latest[min(nth, len(self._latest) - 1)]
            return _HandoutTargets(None, paired, self._targets.get(paired, ()))
        return _HandoutTargets(None, None, self._all)


def _with_targets_of(check: SentinelCheck, earlier: SentinelCheck) -> SentinelCheck:
    """`check` with `earlier`'s targets it lacks as alternatives.

    For an ambiguous call's handout (`_Handed.ambiguous`): its result may be
    of either handout, each resolved against its own request's tools.
    """
    targets = [check, *check.alternatives]
    known = {(target.target, _shown_key(target.call)) for target in targets}
    for target in (earlier, *earlier.alternatives):
        identity = (target.target, _shown_key(target.call))
        if identity not in known:
            known.add(identity)
            targets.append(target)
    return targets[0]._replace(alternatives=tuple(targets[1:]))


class _Checks(NamedTuple):
    """A result's checks, and their steps as far as they don't depend on the result (`_Steps`)."""

    checks: tuple[SentinelCheck, ...]
    parts: tuple[str, ...]
    """Each check's step's digest, all but the result."""

    views: tuple[ToolCallView | None, ...]
    """Each check's call's view (`_Result.views`)."""


class _Steps:
    """The steps a claim's results are checked with, as digests (`_Handouts`).

    A step is the `AfterToolCall` a check sends the protocol. Its digest is a
    SHA-256 over each of `STEP_DIGEST_FIELDS` encoded in full, with no two
    values the protocol can tell apart encoded alike (`_serialized`), as the
    check builds them: the conversation, the assistant message's text and
    id, the call, its view (as its viewer renders it, rejecting a viewer
    error where the check does; the check is given that view), the
    generation's input, tools and tool choice (`Produced.digest`), and the
    result. The result is all of its fields but its `id`, which the bridge
    gives each parsed message afresh. The fields left out are those of
    `STEP_DIGEST_EXCLUDED`. A value that can't be encoded gives a digest no
    other step has. For a check with no proposal's context the digest covers
    one thing the step lacks: where the call sits in the request
    (`_check_part`).

    A check's part of the digest is computed once per set of results it
    answers in the request (`checks`), and each result's once, so repeated
    answers to one call cost work linear in the request.
    """

    def __init__(self) -> None:
        # the key's objects are kept alive with the entry, so ids stay theirs
        self._checks: dict[Hashable, tuple[object, _Checks]] = {}
        self._handouts: dict[str, _HandoutIndex] = {}

    def checks(
        self,
        key: Hashable,
        keep: object,
        resolve: Callable[[], tuple[SentinelCheck, ...]],
        place: str | None,
    ) -> _Checks:
        """The checks `resolve` gives for `key`, resolved once, with their steps but for the result.

        `place` is the id of the request's message that carries the call the
        results answer, if any (`_check_part`).
        """
        entry = self._checks.get(key)
        if entry is None:
            checks = resolve()
            reject = len(checks) > 1
            views = tuple(_view(check, reject) for check in checks)
            parts = tuple(
                _check_part(check, view, place) for check, view in zip(checks, views)
            )
            entry = (keep, _Checks(checks, parts, views))
            self._checks[key] = entry
        return entry[1]

    def handouts(self, call_id: str, handed: _Handed) -> _HandoutIndex:
        """`handed`, the record of `call_id`, indexed once."""
        index = self._handouts.get(call_id)
        if index is None:
            index = self._handouts[call_id] = _HandoutIndex(handed)
        return index

    @staticmethod
    def result(message: ChatMessageTool) -> bytes:
        """The result's part of its steps' digests."""
        return _serialized(message.model_copy(update={"id": None}))


def _view(check: SentinelCheck, reject_on_viewer_error: bool) -> ToolCallView | None:
    """The view a check's step has; None where its viewer fails and the check rejects that (the check fails)."""
    try:
        return resolve_tool_call_view(
            check.call, check.viewer, reject_on_error=reject_on_viewer_error
        )
    except ToolCallViewError:
        return None


def _check_part(
    check: SentinelCheck, view: ToolCallView | None, place: str | None
) -> str:
    """The digest of a check's step, all but its result (`_Steps`).

    A check with no proposal's context has no message to tell one occurrence
    of its call from another: the same call proposed again under its id, and
    run again with the same result, is the same step. So its digest also
    covers `place`, the id of the request's message carrying the call, and
    each occurrence's result is checked. The step itself doesn't show it. A
    result with no call in its request has no place, so results identical in
    every field, checked as one call, are one step.
    """
    with check.producer.scope() if check.producer is not None else nullcontext():
        conversation = current_conversation()
    return _parts_digest(
        conversation,
        check.message,
        check.message_id,
        _serialized(check.call),
        _serialized(view) if view is not None else _unmatched(),
        check.producer.digest if check.producer is not None else None,
        place if check.message_id == _NO_MESSAGE_ID else None,
    )


def _serialized(value: Any) -> bytes:
    """`value` encoded so that values the protocol can tell apart differ (`_encode`); for one that can't be encoded, a value nothing else is."""
    try:
        return _encoded(value)
    except Exception:
        return _unmatched()


def _unmatched() -> bytes:
    # no encoding starts as this does (`_encode`)
    return f"unmatched {uuid()}".encode()


# written as their class and `repr`, which no two values of one share
_REPR_TYPES = (datetime, date, time, timedelta, Decimal, UUID, PurePath)


def _encoded(value: Any) -> bytes:
    out: list[bytes] = []
    _encode(value, out)
    return b"".join(out)


def _encode(value: Any, out: list[bytes]) -> None:
    """Append to `out` an encoding of `value` that no other value has.

    Each value is written as its type, then its content, with a length or a
    count before anything of variable size. So None, NaN and each infinity
    differ, as do `0.0` and `-0.0`, 1 and 1.0, a string and bytes, a list and
    a tuple, and a dict in another key order. A model or dataclass is its
    class and its fields as they are. Pydantic's serializers aren't used: a
    model's writes NaN and the infinities as null whatever mode its caller
    asks for.

    Raises:
        TypeError: The value, or one inside it, has a type not handled here
            (a subclass of a built-in type among them).
    """
    kind = type(value)
    if value is None:
        out.append(b"n")
    elif kind is bool:
        out.append(b"t" if value else b"f")
    elif kind is int:
        # hexadecimal, which has no digit limit
        out.append(b"i%b;" % format(value, "x").encode())
    elif kind is float:
        out.append(b"d" + struct.pack(">d", value))
    elif kind is str or kind is bytes:
        data = value.encode("utf-8", "surrogatepass") if kind is str else value
        out.append(b"%b%d:" % (b"s" if kind is str else b"b", len(data)))
        out.append(data)
    elif kind is list or kind is tuple:
        out.append(b"%b%d:" % (b"l" if kind is list else b"u", len(value)))
        for item in value:
            _encode(item, out)
    elif kind is dict:
        out.append(b"m%d:" % len(value))
        for key, item in value.items():
            _encode(key, out)
            _encode(item, out)
    elif kind is set or kind is frozenset:
        # a set's order differs between processes
        items = sorted(_encoded(item) for item in value)
        out.append(b"%b%d:" % (b"e" if kind is set else b"z", len(items)))
        out.extend(items)
    elif isinstance(value, Enum):
        out.append(b"v")
        _encode(_class_name(kind), out)
        _encode(value.value, out)
    elif isinstance(value, BaseModel) or (
        is_dataclass(value) and not isinstance(value, type)
    ):
        fields = (
            [*kind.model_fields, *(value.model_extra or {})]
            if isinstance(value, BaseModel)
            else [field.name for field in dataclass_fields(value)]
        )
        out.append(b"o")
        _encode(_class_name(kind), out)
        out.append(b"%d:" % len(fields))
        for name in fields:
            _encode(name, out)
            _encode(getattr(value, name), out)
    elif isinstance(value, _REPR_TYPES):
        out.append(b"r")
        _encode(_class_name(kind), out)
        _encode(repr(value), out)
    else:
        raise TypeError(f"{_class_name(kind)} can't be encoded")


def _class_name(kind: type) -> str:
    return f"{kind.__module__}.{kind.__qualname__}"


def _parts_digest(*parts: str | bytes | None) -> str:
    """A SHA-256 digest of `parts`, each told apart by its type and length."""
    digest = hashlib.sha256()
    for part in parts:
        if part is None:
            digest.update(b"n")
            continue
        encoded = (
            part.encode("utf-8", "surrogatepass") if isinstance(part, str) else part
        )
        digest.update(b"s" if isinstance(part, str) else b"b")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _echoes(call: ToolCall) -> set[str]:
    """The other ids a Gemini CLI echo of `call`'s id can be read back as.

    Gemini CLI may send an id back prefixed with its call's wire name
    (`name__id`), which the Google dialect strips for a call handed over to
    that function (`_function_part_id`): the prefixed id, and the id with such
    a prefix stripped. Under each of the function's names (`wire_names`), not
    only the one its arguments give: approval or the sentinel may change
    them after the id is chosen.
    """
    names = wire_names(call.function)
    echoes = {f"{name}__{call.id}" for name in names}
    echoes |= {
        call.id.removeprefix(f"{name}__")
        for name in names
        if call.id.startswith(f"{name}__")
    }
    return echoes - {call.id, ""}


def _echoed(call_id: str) -> Iterator[str]:
    """The ids a Gemini CLI echo `call_id` may be of: each part after a `__`.

    The prefix may be any call's wire name (`wire_names`), so any is taken.
    """
    index = call_id.find("__")
    while index != -1:
        if index + 2 < len(call_id):
            yield call_id[index + 2 :]
        index = call_id.find("__", index + 1)


_COMPUTER_WIRE_NAMES = frozenset({"computer"}) | GEMINI_COMPUTER_ACTIONS


def wire_names(function: str) -> frozenset[str]:
    """The names a Gemini scaffold can send a call to `function` under.

    A `computer` call is sent as the Gemini action its arguments give, so
    any action's name: the arguments a call is handed over with are those
    approval and the sentinel leave it, which may be another action's. A
    `modify` can't change a call's function. Any other call is sent under its
    function's name as it is, and Gemini CLI may echo its id under that name
    or the name stripped, `generic_tool` for a blank one.
    """
    if function == "computer":
        return _COMPUTER_WIRE_NAMES
    return frozenset({function, function.strip() or "generic_tool"})


class _Answer(NamedTuple):
    """A result in a request (`_answers`)."""

    message: ChatMessageTool

    found: _Call | None
    """The call it answers in the request, if any."""

    nth: int
    """How many results under its id come before it, after the request's
    latest assistant message."""


def _answers(input: Sequence[ChatMessage]) -> Iterator[_Answer]:
    """Each result in a request, with the call it answers in the request, if any.

    Calls of an assistant message sharing an id are answered in order: the
    nth result under the id by the nth of them.
    """
    calls: dict[str, _Call] = {}
    # a deque per id, so pairing the nth result with the nth call is linear
    unanswered: dict[str, deque[_Call]] = {}
    answered: dict[str, int] = {}
    for index, message in enumerate(input):
        if isinstance(message, ChatMessageAssistant):
            unanswered = {}
            answered = {}
            # a message with several text parts joins them on each read
            text = message.text if message.tool_calls else ""
            for call in message.tool_calls or []:
                calls[call.id] = _Call(call, text, index)
                unanswered.setdefault(call.id, deque()).append(calls[call.id])
        elif isinstance(message, ChatMessageTool):
            result_id = message.tool_call_id or ""
            found = (
                unanswered[result_id].popleft()
                if unanswered.get(result_id)
                else calls.get(result_id)
            )
            nth = answered.get(result_id, 0)
            answered[result_id] = nth + 1
            yield _Answer(message, found, nth)


def _unissued(message: ChatMessageTool, found: _Call | None) -> tuple[ToolCall, str]:
    """A result under an id the bridge never handed out: the call it answers, and its conservative key."""
    call = (
        found.call
        if found is not None
        else ToolCall(
            id=message.tool_call_id or "",
            function=message.function or "",
            arguments={},
        )
    )
    call_key = (
        found.key if found is not None else _call_key(call, message.function or "")
    )
    return call, _digest(["call", call_key, _content_key(message)])


def _call_key(call: ToolCall, orphan: str | None = None) -> str:
    """A call's conservative identity: its function and arguments.

    Arguments are compared as JSON carries them (`_json_canonical`), so a call
    a scaffold sends back in another spelling is the same call: 5 and 5.0, an
    object's keys in another order. For a call a request shows only: the key
    tells which handouts it is a form of (`_Handed.forms`), and, with the
    result's content (`_content_key`), which results the bridge started with.
    The handouts themselves, and the targets a result is checked as, are kept
    exactly (`_exact_key`, `_shown_key`), and a step's digest covers the call
    the check shows exactly (`_Steps`).

    For a result answering no call in its request, `orphan` is the function the
    result names, and the arguments are unknown.
    """
    identity: Any = (
        ["orphan", orphan]
        if orphan is not None
        else [call.function, _json_canonical(call.arguments)]
    )
    return _digest(identity)


def _exact_key(call: ToolCall) -> str:
    """A call's exact identity: its function and arguments, no two values alike (`_serialized`).

    What the bridge's own records are kept by: which handout a handed call
    is, and whether a model's call is the one it proposed before. Calls JSON
    carries alike (`0.0` and `-0.0`, 1 and 1.0, an object's keys in another
    order) are different calls, and one that can't be encoded is no other
    call. Only a call a request shows is compared as JSON carries it
    (`_call_key`).
    """
    return _parts_digest(_serialized([call.function, call.arguments]))


def _shown_key(call: ToolCall) -> str:
    """The call a check shows, exactly: every field, no two values alike (`_serialized`)."""
    return _parts_digest(_serialized(call))


def same_value(a: Any, b: Any) -> bool:
    """Whether `a` and `b` are one value, as the step digest tells values apart (`_encode`).

    Unlike `json_equal`, 1 and 1.0, `0.0` and `-0.0`, and an object's keys in
    another order differ. A value that can't be encoded equals nothing.
    """
    try:
        return _encoded(a) == _encoded(b)
    except Exception:
        return False


def json_exact(arguments: dict[str, Any]) -> bool:
    """Whether `arguments`, written as JSON and read back, are the same value (`same_value`).

    So no tuple, bytes or set, and no subclass of a JSON type. NaN and the
    infinities, as JSON's constants, and lone surrogates are carried.
    """
    try:
        return same_value(json.loads(json.dumps(arguments)), arguments)
    except Exception:
        return False


def _as_json(call: ToolCall) -> ToolCall:
    """`call` with its arguments as JSON carries them, as a target's record keeps it.

    A call a provider parsed from JSON is unchanged, and so is one an
    approver or the sentinel modified (`json_exact`). A model's call that
    Python code built with other values is as a sandbox bridge's scaffold is
    handed it, in Pydantic's JSON form (a tuple or a set as a list).

    Raises:
        ValueError: The arguments can't be written as JSON (a circular structure).
    """
    try:
        arguments = json.loads(
            json.dumps(
                call.arguments, default=lambda v: to_jsonable_python(v, fallback=str)
            )
        )
    except Exception as ex:
        raise ValueError(
            f"The arguments of a bridged call to '{call.function}' can't be "
            f"written as JSON, so its result can't be checked: {ex}"
        ) from ex
    return replace(call, arguments=arguments)


def _json_canonical(value: Any) -> Any:
    # as `_json_equal`: 5 and 5.0 are the same argument, True and 1 are not
    value = to_jsonable_python(value, fallback=str)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _json_canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_canonical(item) for item in value]
    return value


def _content_key(result: ChatMessageTool) -> str:
    """A result as the model receives it: its function, its content, in order and exactly, and its error.

    Whitespace and the order of text and other parts are meaningful (in code,
    paths and instructions), so any difference is a different result, checked
    again; so is the function it is reported under, which a provider can send
    the model (Google's `FunctionResponse.name`); so is a text part's
    `internal`, which a provider can send in its text (Anthropic), in its key
    order. Other parts' `internal` is left out: a provider can replay one
    (Google's `ContentToolUse.internal["gemini_parts"]`), but no bridge
    dialect sets one from a scaffold's message. A string and a single text
    part are the same content. Everything else is encoded as a step's digest
    encodes it (`_serialized`): no two values are alike.
    """
    content = (
        [ContentText(text=result.content)]
        if isinstance(result.content, str)
        else result.content
    )
    parts = [
        part
        if isinstance(part, ContentText) or part.internal is None
        else part.model_copy(update={"internal": None})
        for part in content
    ]
    # a provider sends no function as an empty name
    return _parts_digest(_serialized([result.function or "", parts, result.error]))


def _digest(value: Any) -> str:
    # the agent controls its results, so a key standing for a checked result
    # must be collision-resistant
    encoded = json.dumps(value, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def inherited_result_keys(input: Sequence[ChatMessage]) -> frozenset[str]:
    """The keys of the results a bridge starts with, which it does not check.

    Taken when the bridge is first constructed, from the messages as they are
    then, and restored from its checkpoint on resume: a result later changed
    in place has a different key and is checked.
    """
    return frozenset(
        _unissued(answer.message, answer.found)[1] for answer in _answers(input)
    )


def history_ids(input: Sequence[ChatMessage]) -> frozenset[str]:
    """The call ids in a conversation: its calls' and its results'."""
    ids: set[str] = set()
    for message in input:
        if isinstance(message, ChatMessageAssistant):
            ids.update(call.id for call in message.tool_calls or [] if call.id)
        elif isinstance(message, ChatMessageTool) and message.tool_call_id:
            ids.add(message.tool_call_id)
    return frozenset(ids)


def handed_targets(
    bridge: AgentBridge, calls: Sequence[ToolCall], tools: Sequence[ToolInfo | Tool]
) -> list[list[HandedTarget]] | None:
    """The targets each of `calls`, as handed, resolves to against `tools`, as approval reviews it (`AgentBridge.reviewed_calls`).

    For a response handed over while the sample's sentinel is not active (in
    an approver's or a scorer's scope, say), which has no checks to take its
    targets from (`_Handouts.hand_over`). None when no sentinel is configured
    for the sample: none of its results is ever checked, so a bridged eval
    without a sentinel resolves nothing and keeps no call in its checkpoint.
    """
    if active_sentinel() is None:
        return None
    resolved: list[list[HandedTarget]] = []
    for call in calls:
        reviewed = bridge.reviewed_calls(call, tools)
        resolved.append(
            [
                HandedTarget(target, reviewed_call)
                for reviewed_call, target in zip(
                    reviewed.calls, reviewed.targets, strict=True
                )
            ]
        )
    return resolved


def checks_bridged_results() -> bool:
    """Whether the sentinel checks the result of a bridged call made here."""
    if not checks_tool_calls():
        return False
    from inspect_ai._sentinel._dispatch import watches_tool_results

    return watches_tool_results()


async def sentinel_tool_call(
    bridge: AgentBridge,
    message: str,
    message_id: str | None,
    call: ToolCall,
    viewer: ToolCallViewer | None,
    producer: Produced | None,
    execution_id: str | None = None,
) -> "Decision | None":
    """Run the `tool_call` stage for a bridged call, recording its steps under the call's handout (`execution_id`)."""
    from inspect_ai._sentinel._dispatch import sentinel_before_tool_call

    with producer.scope() if producer is not None else nullcontext():
        return await _guarded(
            bridge,
            partial(
                sentinel_before_tool_call,
                message,
                message_id,
                call,
                viewer,
                history=None,
                producer=producer.event if producer is not None else None,
                bridge=True,
                execution_id=execution_id,
            ),
        )


async def sentinel_tool_results(bridge: AgentBridge, input: list[ChatMessage]) -> None:
    if not checks_bridged_results():
        return
    result_checks = bridge._handouts
    while True:
        claimed = result_checks.claim(input)
        if claimed.owned:
            with ExitStack() as releases:
                for claim in claimed.owned:
                    releases.callback(result_checks.release, claim)
                await tg_collect(
                    [
                        partial(result_checks.check, bridge, claim)
                        for claim in claimed.owned
                    ]
                )
        if not claimed.waiting:
            return
        for running in claimed.waiting:
            await running.wait()


def _output(result: ChatMessageTool) -> ToolResult:
    # the scaffold's rendering of the result: its untruncated output never
    # reaches the bridge
    if isinstance(result.content, str):
        return result.content
    return [
        content
        for content in result.content
        if isinstance(
            content,
            ContentText | ContentImage | ContentAudio | ContentVideo | ContentDocument,
        )
    ]


async def _tool_result(
    bridge: AgentBridge,
    check: SentinelCheck,
    result: ChatMessageTool,
    reject_on_viewer_error: bool = False,
    view: ToolCallView | None = None,
    execution_id: str | None = None,
) -> None:
    from inspect_ai._sentinel._dispatch import sentinel_after_tool_call

    producer = check.producer
    with producer.scope() if producer is not None else nullcontext():
        try:
            await _guarded(
                bridge,
                partial(
                    sentinel_after_tool_call,
                    check.message,
                    check.message_id,
                    # a copy, so a monitor can't change the call the check keeps
                    deepcopy(check.call),
                    result,
                    _output(result),
                    # only the scaffold or a host tool's execution knows the cut
                    None,
                    check.viewer,
                    history=None,
                    producer=producer.event if producer is not None else None,
                    reject_on_viewer_error=reject_on_viewer_error,
                    bridge=True,
                    # a copy, as the call's
                    view=deepcopy(view),
                    execution_id=execution_id,
                ),
            )
        except ToolCallViewError as ex:
            bridge.request_fail(ex)
            raise


async def _guarded(bridge: AgentBridge, run: Callable[[], Awaitable[T]]) -> T:
    # outcomes that end the sample go through the bridge, since a sandbox
    # bridge's service task can't raise them to the sample runner
    limit: LimitExceededError | None = None
    try:
        return await run()
    except TerminateSampleError as ex:
        bridge.request_terminate(str(ex))
    except SentinelFailure as ex:
        inner = decisive_sentinel_exception(ex.error)
        if not isinstance(inner, LimitExceededError):
            if isinstance(inner, TerminateSampleError):
                bridge.request_terminate(str(inner))
            bridge.request_fail(ex)
            raise
        limit = inner
    # raised outside the handler: the failure's cause is the limit, so linking
    # the limit back to it (as a cause or context) would make a cycle
    if limit is not None:
        raise limit
