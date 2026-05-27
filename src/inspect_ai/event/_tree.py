from dataclasses import dataclass, field
from logging import getLogger
from typing import Callable, Iterable, Sequence, TypeAlias, TypeVar, Union, overload

from ._event import Event
from ._span import SpanBeginEvent, SpanEndEvent

logger = getLogger(__name__)

EventTreeNode: TypeAlias = Union["EventTreeSpan", Event]
"""Node in an event tree."""

EventTree: TypeAlias = list[EventTreeNode]
"""Tree of events (has invividual events and event spans)."""


@dataclass
class EventTreeSpan:
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

    children: list[EventTreeNode] = field(default_factory=list)
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
    nodes: dict[str, EventTreeSpan] = {
        ev.id: EventTreeSpan(
            id=ev.id, parent_id=ev.parent_id, type=ev.type, name=ev.name, begin=ev
        )
        for ev in events
        if isinstance(ev, SpanBeginEvent)
    }

    roots: list[EventTreeNode] = []

    # Where should an event with `span_id` go?
    def bucket(span_id: str | None) -> list[EventTreeNode]:
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


def event_sequence(tree: EventTree | EventTreeSpan) -> Iterable[Event]:
    """Flatten a span forest back into a properly ordered seqeunce.

    Args:
        tree: Event tree or EventTreeSpan.

    Returns:
        Sequence of events.
    """
    if isinstance(tree, EventTreeSpan):
        tree = [tree]
    for item in tree:
        if isinstance(item, EventTreeSpan):
            yield item.begin
            yield from event_sequence(item.children)
            if item.end:
                yield item.end
        else:
            yield item


T = TypeVar("T")


def _walk_all(tree: EventTree) -> Iterable[EventTreeNode]:
    """Recursively yield every node in an event tree."""
    for item in tree:
        yield item
        if isinstance(item, EventTreeSpan):
            yield from _walk_all(item.children)


@overload
def event_tree_walk(tree: EventTree) -> Iterable[EventTreeNode]: ...


@overload
def event_tree_walk(tree: EventTree, filter: type[T]) -> Iterable[T]: ...  # type: ignore[overload-overlap]


@overload
def event_tree_walk(tree: EventTree, filter: tuple[type[T], ...]) -> Iterable[T]: ...


@overload
def event_tree_walk(
    tree: EventTree, filter: Callable[[EventTreeNode], bool]
) -> Iterable[EventTreeNode]: ...


def event_tree_walk(
    tree: EventTree,
    filter: type[T]
    | tuple[type[T], ...]
    | Callable[[EventTreeNode], bool]
    | None = None,
) -> Iterable[T] | Iterable[EventTreeNode]:
    """Walk an event tree yielding nodes matching a filter.

    Args:
        tree: Event tree to walk.
        filter: A type, tuple of types (passed to `isinstance`), a
            predicate function, or None to yield all nodes.

    Yields:
        Matching nodes (or all nodes if no filter), in tree order.
    """
    all_nodes = _walk_all(tree)
    if filter is None:
        return all_nodes
    elif callable(filter) and not isinstance(filter, type):
        return (item for item in all_nodes if filter(item))
    else:
        return (item for item in all_nodes if isinstance(item, filter))


def walk_node_spans(tree: EventTree) -> Iterable[EventTreeSpan]:
    return event_tree_walk(tree, EventTreeSpan)


def _print_event_tree(tree: EventTree, indent: str = "") -> None:
    for item in tree:
        if isinstance(item, EventTreeSpan):
            print(f"{indent}span ({item.type}): {item.name}")
            _print_event_tree(item.children, f"{indent}  ")
        else:
            print(f"{indent}{item.event}")
