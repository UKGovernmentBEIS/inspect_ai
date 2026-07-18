"""Per-chunk event stats sidecar producer (design/large-samples.md).

``events/stats.json`` summarizes the events sequence per chunk: sparse
event-type counts plus the first/last event's type and span_id.
Deliberately separate from the skeleton — stats are a function of
chunking policy (rechunking invalidates stats, not the skeleton).

Load-bearing consumers: filter pushdown (skip non-matching chunks
unread), run-extent scans, per-chunk row estimates, and O(1) chunk-edge
resolution — the first/last type+span_id is exactly sufficient for the
head-run-continuation rule (a run straddling a chunk edge belongs to the
chunk where it starts).

Canonical JSON form is ``model_dump(mode="json", exclude_none=True)`` —
null ``span_id`` on chunk edges is omitted.
"""

from collections import Counter
from typing import Sequence

from pydantic import BaseModel

from inspect_ai.event._event import Event

from .format import ChunkRange, boundary_ranges


class ChunkEdgeEvent(BaseModel):
    """Type and span identity of an event at a chunk edge."""

    type: str
    """Event type."""

    span_id: str | None = None
    """Span the event occurred within (None at root level)."""


class EventChunkStats(BaseModel):
    """Stats for one events chunk."""

    start: int
    """Sequence index of the chunk's first event (== the chunk entry name)."""

    type_counts: dict[str, int]
    """Event-type counts within the chunk, sparse."""

    first: ChunkEdgeEvent
    """First event in the chunk."""

    last: ChunkEdgeEvent
    """Last event in the chunk."""


class EventStats(BaseModel):
    """Per-chunk stats over a sample's events sequence."""

    version: int = 1
    chunks: list[EventChunkStats]


def event_stats(events: Sequence[Event], boundaries: list[int]) -> EventStats:
    """Produce per-chunk stats for an events sequence.

    Pure and deterministic in (events, boundaries). Chunks are non-empty
    by construction, so first/last always exist.

    Args:
        events: Complete event sequence for a sample.
        boundaries: Cumulative end-exclusive chunk boundaries (the shape
            the shell's ``sequences`` field carries).

    Returns:
        The stats sidecar (see module docstring for the canonical JSON form).
    """

    def chunk_stats(range: ChunkRange) -> EventChunkStats:
        chunk = events[range.start : range.end_exclusive]
        return EventChunkStats(
            start=range.start,
            type_counts=dict(Counter(ev.event for ev in chunk)),
            first=_edge(chunk[0]),
            last=_edge(chunk[-1]),
        )

    return EventStats(chunks=[chunk_stats(r) for r in boundary_ranges(boundaries)])


def _edge(event: Event) -> ChunkEdgeEvent:
    return ChunkEdgeEvent(type=event.event, span_id=event.span_id)
