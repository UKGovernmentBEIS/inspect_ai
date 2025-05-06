from dataclasses import dataclass, field
from logging import getLogger
from typing import Iterable, Sequence, TypeAlias

from ._transcript import Event, SpanBeginEvent, SpanEndEvent

logger = getLogger(__name__)

EventNode: TypeAlias = "SpanNode" | Event
"""Node in an event tree."""

EventTree: TypeAlias = list[EventNode]
"""Tree of events (has invividual events and event spans)."""


@dataclass
class SpanNode:
    """Event tree node representing a span of events."""

    id: str
    """Span id."""

    parent_id: str | None
    """Parent span id."""

    type: str | None
    """Optional 'type' field for span."""

    name: str
    """Span name."""

    begin: SpanBeginEvent
    """Span begin event."""

    end: SpanEndEvent | None = None
    """Span end event (if any)."""

    children: list[EventNode] = field(default_factory=list)
    """Children in the span."""


def event_tree(events: Sequence[Event]) -> EventTree:
    """Build a tree representation of a sequence of events.

    Organize events heirarchially into event spans.

    Args:
        events: Sequence of `Event`.

    Returns:
        Event tree.
    """
    # Convert one flat list of (possibly interleaved) events into  *forest*
    # (list of root-level items).

    # Pre-create one node per span so we can attach events no matter when they
    # arrive in the file. A single forward scan guarantees that the order of
    # `children` inside every span reflects the order in which things appeared
    # in the transcript.
    nodes: dict[str, SpanNode] = {
        ev.id: SpanNode(
            id=ev.id, parent_id=ev.parent_id, type=ev.type, name=ev.name, begin=ev
        )
        for ev in events
        if isinstance(ev, SpanBeginEvent)
    }

    roots: list[EventNode] = []

    # Where should an event with `span_id` go?
    def bucket(span_id: str | None) -> list[EventNode]:
        if span_id and span_id in nodes:
            return nodes[span_id].children
        return roots  # root level

    # Single pass in original order
    for ev in events:
        if isinstance(ev, SpanBeginEvent):  # span starts
            bucket(ev.parent_id).append(nodes[ev.id])

        elif isinstance(ev, SpanEndEvent):  # span ends
            if n := nodes.get(ev.id):
                n.end = ev
            else:
                logger.warning(f"Span end event (id: {ev.id} with no span begin)")

        else:  # ordinary event
            bucket(ev.span_id).append(ev)

    return roots


def event_sequence(tree: EventTree) -> Iterable[Event]:
    """Flatten a span forest back into a properly ordered seqeunce.

    Args:
        tree: Event tree

    Returns:
        Sequence of events.
    """
    for item in tree:
        if isinstance(item, SpanNode):
            yield item.begin
            yield from event_sequence(item.children)
            if item.end:
                yield item.end
        else:
            yield item


def _print_event_tree(tree: EventTree, indent: str = "") -> None:
    for item in tree:
        if isinstance(item, SpanNode):
            print(f"{indent}span ({item.type}): {item.name}")
            _print_event_tree(item.children, f"{indent}  ")
        else:
            print(f"{indent}{item.event}")
