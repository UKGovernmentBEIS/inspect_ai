"""ASCII repr rendering for Timeline objects.

Produces a swimlane diagram showing agent hierarchy, parallel agents,
branches, and inline markers (compaction, errors).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._timeline import (
        Timeline,
        TimelineBranch,
        TimelineSpan,
    )


# =============================================================================
# Data types
# =============================================================================


@dataclass
class _Row:
    """A single row in the ASCII output."""

    depth: int
    name: str
    segments: list[tuple[datetime, datetime]]
    tokens: int
    markers: list[tuple[datetime, str]] = field(default_factory=list)


# =============================================================================
# Formatting helpers
# =============================================================================


def _format_token_count(tokens: int) -> str:
    """Format a token count for display.

    Args:
        tokens: Raw token count.

    Returns:
        Formatted string: "0", "1.2k", "1.2M", etc.
    """
    if tokens == 0:
        return "0"
    if tokens < 1000:
        return str(tokens)
    if tokens < 1_000_000:
        value = tokens / 1000
        if value >= 100:
            return f"{value:.0f}k"
        if value >= 10:
            return f"{value:.1f}k"
        return f"{value:.1f}k"
    value = tokens / 1_000_000
    if value >= 100:
        return f"{value:.0f}M"
    if value >= 10:
        return f"{value:.1f}M"
    return f"{value:.1f}M"


_CIRCLED_DIGITS = "⓪①②③④⑤⑥⑦⑧⑨"


def _count_glyph(n: int) -> str:
    """Return a single-character glyph for a count (e.g. ② for 2)."""
    if 0 <= n <= 9:
        return _CIRCLED_DIGITS[n]
    return str(n)[-1]  # fallback: last digit


def _render_bar(
    segments: list[tuple[datetime, datetime]],
    view_start: datetime,
    view_end: datetime,
    width: int,
    markers: list[tuple[datetime, str]],
) -> str:
    """Render a proportional bar with filled segments and markers.

    Args:
        segments: List of (start, end) time ranges to fill.
        view_start: The start of the full time range.
        view_end: The end of the full time range.
        width: Number of characters for the bar.
        markers: List of (timestamp, glyph) pairs to overlay.

    Returns:
        A string of exactly `width` characters.
    """
    if width <= 0:
        return ""

    total_duration = (view_end - view_start).total_seconds()
    if total_duration <= 0:
        # Degenerate case: all at same time
        bar = ["█"] * width
        return "".join(bar)

    bar = [" "] * width

    for seg_start, seg_end in segments:
        start_frac = (seg_start - view_start).total_seconds() / total_duration
        end_frac = (seg_end - view_start).total_seconds() / total_duration
        start_pos = max(0, min(width - 1, int(start_frac * width)))
        end_pos = max(start_pos + 1, min(width, int(end_frac * width + 0.5)))
        # Ensure at least 1 char for visible segments
        if end_pos <= start_pos:
            end_pos = start_pos + 1
        for i in range(start_pos, min(end_pos, width)):
            bar[i] = "█"

    # Overlay markers on filled positions
    for ts, glyph in markers:
        frac = (ts - view_start).total_seconds() / total_duration
        pos = max(0, min(width - 1, int(frac * width)))
        if bar[pos] == "█":
            bar[pos] = glyph

    return "".join(bar)


# =============================================================================
# Row collection
# =============================================================================

# Overlap tolerance for detecting parallel agents
_OVERLAP_TOLERANCE = timedelta(milliseconds=100)


def _collect_markers(span: "TimelineSpan") -> list[tuple[datetime, str]]:
    """Collect markers from a span's direct content.

    Uses the event.event string to determine event type (duck typing)
    rather than isinstance, for testability with mock objects.

    Args:
        span: The span to scan.

    Returns:
        List of (timestamp, glyph) pairs.
    """
    from ._timeline import TimelineEvent

    markers: list[tuple[datetime, str]] = []
    for item in span.content:
        if not isinstance(item, TimelineEvent):
            continue
        event_type = item.event.event
        # Compaction marker
        if event_type == "compaction":
            markers.append((item.start_time, "┊"))
    return markers


def _spans_overlap(a: "TimelineSpan", b: "TimelineSpan") -> bool:
    """Check if two spans overlap (with tolerance).

    Args:
        a: First span.
        b: Second span.

    Returns:
        True if the spans overlap.
    """
    return (
        max(a.start_time, b.start_time)
        < min(a.end_time, b.end_time) + _OVERLAP_TOLERANCE
    )


def _cluster_spans(
    spans: list["TimelineSpan"],
) -> list[list["TimelineSpan"]]:
    """Group spans into clusters of overlapping spans.

    Spans that overlap (directly or transitively) are placed in the same
    cluster. Non-overlapping spans end up in separate clusters. Clusters
    are sorted by earliest start time.

    Args:
        spans: List of spans to cluster.

    Returns:
        List of clusters, each a list of overlapping spans.
    """
    if not spans:
        return []

    # Sort by start time
    sorted_spans = sorted(spans, key=lambda s: s.start_time)
    clusters: list[list["TimelineSpan"]] = [[sorted_spans[0]]]

    for span in sorted_spans[1:]:
        # Check if span overlaps with any span in the current cluster
        merged = False
        for existing in clusters[-1]:
            if _spans_overlap(existing, span):
                clusters[-1].append(span)
                merged = True
                break
        if not merged:
            clusters.append([span])

    return clusters


def _collect_rows(
    span: "TimelineSpan",
    depth: int,
    view_start: datetime,
    view_end: datetime,
) -> list[_Row]:
    """Recursively collect rows for rendering.

    Args:
        span: The span to process.
        depth: Current indentation depth.
        view_start: Global view start time.
        view_end: Global view end time.

    Returns:
        Flat list of _Row objects for rendering.
    """
    from ._timeline import TimelineSpan as TSpan

    rows: list[_Row] = []

    # Emit row for this span
    markers = _collect_markers(span)
    rows.append(
        _Row(
            depth=depth,
            name=span.name,
            segments=[(span.start_time, span.end_time)],
            tokens=span.total_tokens,
            markers=markers,
        )
    )

    # Collect child spans (skip events and utility spans)
    child_spans: list[TSpan] = []
    for item in span.content:
        if isinstance(item, TSpan) and not item.utility:
            child_spans.append(item)

    # Group children by name (case-insensitive), preserving first-occurrence order
    groups: dict[str, list[TSpan]] = {}
    group_order: list[str] = []
    for child in child_spans:
        key = child.name.lower()
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(child)

    # Sort groups by earliest start time
    group_order.sort(key=lambda k: min(s.start_time for s in groups[k]))

    for key in group_order:
        group = groups[key]
        display_name = group[0].name  # Use original casing from first occurrence

        if len(group) == 1:
            # Single span: one row, recurse into children
            s = group[0]
            group_markers = _collect_markers(s)
            rows.append(
                _Row(
                    depth=depth + 1,
                    name=display_name,
                    segments=[(s.start_time, s.end_time)],
                    tokens=s.total_tokens,
                    markers=group_markers,
                )
            )
            child_rows = _collect_rows(s, depth + 1, view_start, view_end)
            rows.extend(child_rows[1:])
        else:
            # Multiple same-name spans: one row with segments per cluster.
            # Overlapping clusters become envelope segments with a count
            # marker; singletons become individual segments.
            clusters = _cluster_spans(group)
            segments: list[tuple[datetime, datetime]] = []
            all_markers: list[tuple[datetime, str]] = []
            total_tokens = sum(s.total_tokens for s in group)

            for cluster in clusters:
                for s in cluster:
                    all_markers.extend(_collect_markers(s))
                if len(cluster) == 1:
                    s = cluster[0]
                    segments.append((s.start_time, s.end_time))
                else:
                    envelope_start = min(s.start_time for s in cluster)
                    envelope_end = max(s.end_time for s in cluster)
                    segments.append((envelope_start, envelope_end))
                    # Add count marker at envelope start
                    glyph = _count_glyph(len(cluster))
                    all_markers.append((envelope_start, glyph))

            rows.append(
                _Row(
                    depth=depth + 1,
                    name=display_name,
                    segments=segments,
                    tokens=total_tokens,
                    markers=all_markers,
                )
            )
            # Recurse into children of singleton clusters only
            for cluster in clusters:
                if len(cluster) == 1:
                    child_rows = _collect_rows(
                        cluster[0], depth + 1, view_start, view_end
                    )
                    rows.extend(child_rows[1:])

    # Emit branch rows
    for i, branch in enumerate(span.branches):
        _emit_branch_rows(branch, i, depth, view_start, view_end, rows)

    return rows


def _emit_branch_rows(
    branch: "TimelineBranch",
    index: int,
    depth: int,
    view_start: datetime,
    view_end: datetime,
    rows: list[_Row],
) -> None:
    """Emit rows for a branch and its children.

    Args:
        branch: The branch to process.
        index: Branch index (for labeling).
        depth: Current indentation depth.
        view_start: Global view start time.
        view_end: Global view end time.
        rows: List to append rows to (mutated).
    """
    from ._timeline import TimelineSpan as TSpan

    # Derive label
    child_spans = [item for item in branch.content if isinstance(item, TSpan)]
    if len(child_spans) == 1:
        label = f"\u21b3 {child_spans[0].name}"
    else:
        label = f"\u21b3 branch {index + 1}"

    # Collect markers from branch content
    from ._timeline import TimelineEvent

    markers: list[tuple[datetime, str]] = []
    for item in branch.content:
        if isinstance(item, TimelineEvent):
            event_type = item.event.event
            if event_type == "compaction":
                markers.append((item.start_time, "┊"))

    rows.append(
        _Row(
            depth=depth + 1,
            name=label,
            segments=[(branch.start_time, branch.end_time)],
            tokens=branch.total_tokens,
            markers=markers,
        )
    )

    # Recurse into child spans within the branch
    for child in child_spans:
        if not child.utility:
            child_rows = _collect_rows(child, depth + 1, view_start, view_end)
            # Skip the span's own row (already represented by the branch row)
            # unless the branch has multiple children
            if len(child_spans) == 1:
                rows.extend(child_rows[1:])
            else:
                rows.extend(child_rows)


# =============================================================================
# Main render function
# =============================================================================


_MAX_WIDTH = 200


def render_timeline(timeline: "Timeline", width: int | None = None) -> str:
    """Render an ASCII swimlane diagram of the timeline.

    Args:
        timeline: The Timeline to render.
        width: Total width of the output in characters. If None, auto-detects
            terminal width (capped at _MAX_WIDTH).

    Returns:
        Multi-line string with the ASCII diagram.
    """
    if width is None:
        width = 120

    root = timeline.root

    # Handle empty/degenerate timelines
    if not root.content:
        return f"{root.name} (empty)"

    view_start = root.start_time
    view_end = root.end_time

    rows = _collect_rows(root, 0, view_start, view_end)

    if not rows:
        return f"{root.name} (empty)"

    # Compute column widths
    token_width = 6  # e.g. " 48.5k"
    separator_chars = 4  # " │" + "│ "

    # Label column: indentation (2 chars per depth) + name
    # Minimum width ensures plain "main" timelines align with ones that
    # have subagent rows like "  Explore".
    min_label_width = 10  # len("  Explore") + 1
    label_widths = [r.depth * 2 + len(r.name) for r in rows]
    label_col_width = max(max(label_widths) + 1, min_label_width)

    bar_width = width - label_col_width - separator_chars - token_width
    if bar_width < 4:
        bar_width = 4

    # Render each row
    lines: list[str] = []
    for row in rows:
        indent = "  " * row.depth
        label = f"{indent}{row.name}"
        label_padded = label.ljust(label_col_width)

        bar = _render_bar(row.segments, view_start, view_end, bar_width, row.markers)
        tokens_str = _format_token_count(row.tokens).rjust(token_width)

        lines.append(f"{label_padded}│{bar}│{tokens_str}")

    return "\n".join(lines)
