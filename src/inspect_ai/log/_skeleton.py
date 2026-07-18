"""Structural skeleton producer (design/large-samples.md, "Structural skeleton").

The skeleton is the span-proportional structural summary of a sample's event
sequence: one entry per structural span (plus capped notables), never one per
event. It is a pure, deterministic function of the event sequence — derived
data is rebuilt from events, never migrated.

Event identity is the sequence index; uuids are never persisted here.

Canonical JSON form is ``model_dump(mode="json", exclude_none=True)`` —
null-valued optional fields (root ``parent``, untyped ``type``, root-level
notable ``span``, non-checkpoint ``checkpoint_id``) are omitted.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, NamedTuple, Sequence

from pydantic import BaseModel, Field

from inspect_ai._util.dateutil import datetime_to_iso_format_safe
from inspect_ai.event._checkpoint import CheckpointEvent
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._step import StepEvent
from inspect_ai.event._tree import EventTreeNode, EventTreeSpan, event_tree

DEFAULT_NOTABLE_CAP = 1000
"""Default per-type cap on persisted notables."""

DEFAULT_ESCAPE_HATCH_EVENTS = 1000
"""Default descendant-event count at which a leaf tool span is kept anyway."""

NOTABLE_TYPES: frozenset[str] = frozenset({"score", "checkpoint"})
"""Event types persisted as notables (ratified, not a policy knob).

Deliberately not configurable: persisted notables become gap items, and a
model-event notable type would break the per-span accounting invariant
``sum(gap_models) + sum(child span models) == models``.
"""


@dataclass(frozen=True)
class SkeletonPolicy:
    """Writer-policy knobs for skeleton production.

    These are policy, not contract: the skeleton schema is unchanged by any
    knob, only which spans/notables are persisted.
    """

    notable_cap: int = DEFAULT_NOTABLE_CAP
    """Per-type first-N cap on persisted notables."""

    escape_hatch_events: int = DEFAULT_ESCAPE_HATCH_EVENTS
    """A leaf tool span with at least this many descendant events is included
    despite the leaf-tool exclusion (fetch elision + outline presence for
    monster tool spans)."""


_DEFAULT_POLICY = SkeletonPolicy()

_ExcludedFn = Callable[["_Node"], bool]
"""Exclusion predicate closed over aggregates and policy."""


class SkeletonCounts(BaseModel):
    """Sample totals over the full event sequence."""

    events: int
    models: int


class SkeletonSpan(BaseModel):
    """One structural span (span begin/end pair or legacy step pair)."""

    id: str
    """Span id (legacy steps: synthesized as ``step-<begin index>``)."""

    parent: int | None = None
    """Index of parent span in the spans array (None at root)."""

    name: str
    """Span name."""

    type: str | None = None
    """Span type (solver | agent | subtask | scorer | tool | ...)."""

    begin: int
    """Sequence index of the span begin event."""

    extent: tuple[int, int]
    """[first, last] descendant event index (parallel spans may overlap)."""

    t: tuple[str, str]
    """[start, end] ISO timestamps."""

    working: tuple[float, float]
    """[start, end] working time."""

    events: int
    """Descendant event count (incl. nested spans and begin/end markers)."""

    models: int
    """Descendant model-event count."""

    gap_models: list[int]
    """Model events strictly between consecutive items, where items are
    direct-child structural spans + persisted notables merged in sequence
    order (``len == items + 1``). Additive: suppressing an item row means
    summing its adjacent gaps."""

    children: dict[str, int]
    """Direct-child event-type counts, sparse. Includes events of excluded
    (dissolved) leaf tool spans; excludes structural markers (span/step
    begin/end of structural children)."""


class SkeletonNotable(BaseModel):
    """A persisted notable event."""

    i: int
    """Sequence index of the event."""

    span: int | None = None
    """Index of the directly containing span row (None at root level)."""

    type: str
    """Event type."""

    checkpoint_id: int | None = None
    """Checkpoint id (checkpoint events only)."""


class SampleSkeleton(BaseModel):
    """Span-proportional structural skeleton of a sample's event sequence."""

    version: int = 1
    counts: SkeletonCounts
    spans: list[SkeletonSpan]
    notables: list[SkeletonNotable]
    overflow: dict[str, int] = Field(default_factory=dict)
    """Per-type count of notables omitted past the cap, sparse."""


def sample_skeleton(
    events: Sequence[Event], policy: SkeletonPolicy = _DEFAULT_POLICY
) -> SampleSkeleton:
    """Produce the structural skeleton for an event sequence.

    Pure and deterministic: the same events (and policy) always yield the
    same skeleton, so distrusted skeletons can be rebuilt rather than
    migrated. Legacy step begin/end pairs map to span-table entries — one
    skeleton contract, no legacy carve-out.

    Args:
        events: Complete event sequence for a sample.
        policy: Writer-policy knobs (caps and thresholds).

    Returns:
        The skeleton (see module docstring for the canonical JSON form).
    """
    index_of = {id(ev): i for i, ev in enumerate(events)}
    forest = _fold_steps(event_tree(events), index_of)
    aggs: dict[int, _Agg] = {}
    for node in _walk_nodes(forest):
        _aggregate(node, index_of, aggs)

    notables = _persisted_notables(events, policy)
    persisted_set = set(notables.indexes)

    spans: list[SkeletonSpan] = []
    notable_span: dict[int, int] = {}

    def excluded(node: _Node) -> bool:
        return _is_excluded(node, aggs[id(node)], policy)

    def emit(items: list[_Node | Event], parent: int | None) -> None:
        for item in items:
            if not isinstance(item, _Node) or excluded(item):
                continue
            row = len(spans)
            spans.append(
                _span_row(item, aggs, parent, index_of, persisted_set, excluded)
            )
            for child in item.items:
                if not isinstance(child, _Node):
                    child_index = index_of[id(child)]
                    if child_index in persisted_set:
                        notable_span[child_index] = row
            emit(item.items, row)

    emit(forest, None)

    return SampleSkeleton(
        counts=SkeletonCounts(
            events=len(events),
            models=sum(1 for ev in events if isinstance(ev, ModelEvent)),
        ),
        spans=spans,
        notables=[
            _notable(events[i], i, notable_span.get(i)) for i in notables.indexes
        ],
        overflow=notables.overflow,
    )


@dataclass
class _Node:
    """A structural span candidate: a span or legacy step begin/end pair."""

    id: str
    name: str
    type: str | None
    begin: Event
    end: Event | None
    items: list[_Node | Event]
    """Direct children (structural nodes and plain events) in sequence order."""


class _Agg(NamedTuple):
    """Per-node descendant aggregates."""

    first: int
    last: int
    end_time: datetime
    end_working: float
    events: int
    models: int


def _fold_steps(
    items: list[EventTreeNode], index_of: dict[int, int]
) -> list[_Node | Event]:
    """Convert an event_tree bucket into _Nodes, folding legacy step pairs.

    Steps nest positionally within their bucket (legacy events carry no
    span_id, so a step and its events share a bucket). Pairing follows the
    frozen legacy oracle (the viewer's ``treeifyWithSteps``): pure stack
    discipline — a step-end closes the innermost open step, matching neither
    name nor type. A step-end with no open step is kept as a plain event;
    steps left open at the end of the bucket remain nodes without an end
    marker.
    """
    result: list[_Node | Event] = []
    stack: list[_Node] = []

    def sink() -> list[_Node | Event]:
        return stack[-1].items if stack else result

    for item in items:
        if isinstance(item, EventTreeSpan):
            sink().append(
                _Node(
                    id=item.id,
                    name=item.name,
                    type=item.type,
                    begin=item.begin,
                    end=item.end,
                    items=_fold_steps(item.children, index_of),
                )
            )
        elif isinstance(item, StepEvent) and item.action == "begin":
            node = _Node(
                id=f"step-{index_of[id(item)]}",
                name=item.name,
                type=item.type,
                begin=item,
                end=None,
                items=[],
            )
            sink().append(node)
            stack.append(node)
        elif isinstance(item, StepEvent) and item.action == "end":
            if stack:
                stack.pop().end = item
            else:
                sink().append(item)
        else:
            sink().append(item)

    return result


def _walk_nodes(items: list[_Node | Event]) -> list[_Node]:
    """All _Nodes in a forest, children before parents (post-order)."""
    nodes: list[_Node] = []
    for item in items:
        if isinstance(item, _Node):
            nodes.extend(_walk_nodes(item.items))
            nodes.append(item)
    return nodes


def _aggregate(node: _Node, index_of: dict[int, int], aggs: dict[int, _Agg]) -> _Agg:
    """Compute descendant aggregates for a node (children already in aggs)."""
    begin_index = index_of[id(node.begin)]
    first = begin_index
    last = begin_index
    end_time = node.begin.timestamp
    end_working = node.begin.working_start
    events = 1 + (1 if node.end is not None else 0)
    models = 0

    for item in node.items:
        if isinstance(item, _Node):
            agg = aggs[id(item)]
            first = min(first, agg.first)
            last = max(last, agg.last)
            end_time = max(end_time, agg.end_time)
            end_working = max(end_working, agg.end_working)
            events += agg.events
            models += agg.models
        else:
            index = index_of[id(item)]
            first = min(first, index)
            last = max(last, index)
            end_time = max(end_time, item.timestamp)
            end_working = max(end_working, item.working_start)
            events += 1
            if isinstance(item, ModelEvent):
                models += 1

    if node.end is not None:
        end_index = index_of[id(node.end)]
        first = min(first, end_index)
        last = max(last, end_index)
        # span/step end markers are authoritative for end time when present
        end_time = node.end.timestamp
        end_working = node.end.working_start

    agg = _Agg(
        first=first,
        last=last,
        end_time=end_time,
        end_working=end_working,
        events=events,
        models=models,
    )
    aggs[id(node)] = agg
    return agg


def _notable(event: Event, i: int, span: int | None) -> SkeletonNotable:
    """Build the notables entry for a persisted notable event."""
    return SkeletonNotable(
        i=i,
        span=span,
        type=event.event,
        checkpoint_id=event.checkpoint_id
        if isinstance(event, CheckpointEvent)
        else None,
    )


class _PersistedNotables(NamedTuple):
    """Notable selection result."""

    indexes: list[int]
    """Persisted notable event indexes in sequence order."""

    overflow: dict[str, int]
    """Sparse map of event type to count of notables omitted past the cap."""


def _persisted_notables(
    events: Sequence[Event], policy: SkeletonPolicy
) -> _PersistedNotables:
    """Select persisted notables (per-type first-N) and per-type overflow."""
    persisted: list[int] = []
    counts: Counter[str] = Counter()
    for i, ev in enumerate(events):
        if ev.event in NOTABLE_TYPES:
            counts[ev.event] += 1
            if counts[ev.event] <= policy.notable_cap:
                persisted.append(i)
    overflow = {
        type_: count - policy.notable_cap
        for type_, count in counts.items()
        if count > policy.notable_cap
    }
    return _PersistedNotables(indexes=persisted, overflow=overflow)


def _is_excluded(node: _Node, agg: _Agg, policy: SkeletonPolicy) -> bool:
    """Test a node for leaf-tool exclusion.

    A tool span with no child spans, no model events and no notable events is
    summarized in its parent's counters instead of getting a span row —
    unless it has enough descendant events to earn the size escape hatch.

    Exclusion tests raw notable presence (not the persisted cap): a notable
    must always be attributable to an existing span row.
    """
    return (
        node.type == "tool"
        and not any(isinstance(item, _Node) for item in node.items)
        and agg.models == 0
        and not any(
            not isinstance(item, _Node) and item.event in NOTABLE_TYPES
            for item in node.items
        )
        and agg.events < policy.escape_hatch_events
    )


def _span_row(
    node: _Node,
    aggs: dict[int, _Agg],
    parent: int | None,
    index_of: dict[int, int],
    persisted_set: set[int],
    excluded: "_ExcludedFn",
) -> SkeletonSpan:
    """Build the span-table row for a structural node."""
    agg = aggs[id(node)]

    children: Counter[str] = Counter()
    gap_models = [0]
    for item in node.items:
        if isinstance(item, _Node):
            if excluded(item):
                # dissolve: a leaf's items are all plain events
                children.update(child.event for child in _plain_items(item))
            else:
                gap_models.append(0)
        else:
            children[item.event] += 1
            if index_of[id(item)] in persisted_set:
                gap_models.append(0)
            elif isinstance(item, ModelEvent):
                gap_models[-1] += 1

    return SkeletonSpan(
        id=node.id,
        parent=parent,
        name=node.name,
        type=node.type,
        begin=index_of[id(node.begin)],
        extent=(agg.first, agg.last),
        t=(
            datetime_to_iso_format_safe(node.begin.timestamp),
            datetime_to_iso_format_safe(agg.end_time),
        ),
        working=(node.begin.working_start, agg.end_working),
        events=agg.events,
        models=agg.models,
        gap_models=gap_models,
        children=dict(children),
    )


def _plain_items(node: _Node) -> list[Event]:
    """The plain (non-node) direct items of a node."""
    return [item for item in node.items if not isinstance(item, _Node)]
