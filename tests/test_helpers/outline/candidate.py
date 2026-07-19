"""Skeleton-fed outline rows — the candidate side of the parity harness.

Derives outline rows from a `SampleSkeleton` alone (span rows + `gap_models`
turn rows + notables), mirroring the prototype's skeleton-only outline
(`proto/eval2-render`, `src/ui/Outline.tsx`) plus the transform-equivalents
the legacy pipeline applies (`design/large-samples.md`, Appendix B):

- ``discard_solvers_span`` / ``discard_checkpoint_span`` / ``unwrap_main``:
  spans of those types dissolve into their parent — their items and gaps
  splice in additively (the `gap_models` additivity property).
- ``unwrap_agent_solver``: a solver span holding exactly one agent child
  span and nothing else but its state (+ optional store) event dissolves
  the agent child into the solver.
- ``collapse_same_name_spans``: an agent/solver child span with the same
  unqualified name as its agent/solver parent dissolves into the parent.
- ``noScorerChildren``: rows beneath a scorer span inside a scorers span
  are suppressed (the scorer row itself stays).
- ``filterEmpty``: spans with no events beyond their own markers (and no
  non-empty descendants) produce no row; ``fork_nav``/``empty_branch``
  spans are kept regardless.
- default collapse (``collapseFilters``): init/sample_init spans,
  solver-typed ``system_message`` spans, tool spans, and subtask spans are
  collapsed by default — the row shows, descendants don't.

Tool/subtask spans keep their structural span row (signed-off divergence
class 1: legacy elevates the tool/subtask event and absorbs tool rows into
turns; the skeleton's structural row wins). ``unwrap_handoff`` is
deliberately not mirrored (no handoff spans in the corpus; a future log
with them will surface in the parity diff for explicit sign-off).

Turn rows anchor at the gap's lower bound (signed-off divergence class 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from inspect_ai.log._skeleton import (
    SampleSkeleton,
    SkeletonNotable,
    SkeletonSpan,
)

from .oracle import SANDBOX_SIGNAL_NAME, CollapseState, OutlineRow


@dataclass
class _CandidateSpan:
    span: SkeletonSpan | None
    """None for the virtual root (which has no gaps: root-level loose model
    events are not counted anywhere in the skeleton)."""

    items: list["_CandidateSpan | SkeletonNotable"] = field(default_factory=list)
    gaps: list[int] = field(default_factory=list)


def _build_tree(skeleton: SampleSkeleton) -> _CandidateSpan:
    nodes = [
        _CandidateSpan(span=span, gaps=list(span.gap_models)) for span in skeleton.spans
    ]
    root = _CandidateSpan(span=None)

    def items_of(parent: int | None) -> list[_CandidateSpan | SkeletonNotable]:
        spans: list[_CandidateSpan | SkeletonNotable] = [
            node
            for node in nodes
            if node.span is not None and node.span.parent == parent
        ]
        notables: list[_CandidateSpan | SkeletonNotable] = [
            n for n in skeleton.notables if n.span == parent
        ]
        return sorted(spans + notables, key=_item_position)

    for index, node in enumerate(nodes):
        node.items = items_of(index)
    root.items = items_of(None)
    root.gaps = [0] * (len(root.items) + 1)
    return root


def _item_position(item: _CandidateSpan | SkeletonNotable) -> int:
    if isinstance(item, SkeletonNotable):
        return item.i
    assert item.span is not None
    return item.span.begin


def _dissolve_item(parent: _CandidateSpan, index: int) -> None:
    """Splice a child span's items and gaps into its parent additively."""
    child = parent.items[index]
    assert isinstance(child, _CandidateSpan) and child.span is not None
    gaps = parent.gaps
    merged = (
        gaps[:index]
        + [gaps[index] + child.gaps[0]]
        + child.gaps[1:-1]
        + ([child.gaps[-1] + gaps[index + 1]] if len(child.gaps) > 1 else [])
        + gaps[index + 2 :]
    )
    # a childless span has a single gap entry that merges into both sides
    if len(child.gaps) == 1:
        merged = (
            gaps[:index]
            + [gaps[index] + child.gaps[0] + gaps[index + 1]]
            + gaps[index + 2 :]
        )
    parent.items[index : index + 1] = child.items
    parent.gaps = merged


_DISSOLVED_TYPES = ("main", "solvers", "checkpoint")


def _unqualified(name: str | None) -> str | None:
    if name is None:
        return None
    _, _, tail = name.partition("/")
    return tail or name


def _is_agent_solver_wrapper(node: _CandidateSpan) -> bool:
    """`unwrap_agent_solver`: solver span == [agent span] + state (+ store)."""
    span = node.span
    if span is None or span.type != "solver":
        return False
    child_spans = [i for i in node.items if isinstance(i, _CandidateSpan)]
    if len(child_spans) != len(node.items) or len(child_spans) != 1:
        return False
    child = child_spans[0]
    return (
        child.span is not None
        and child.span.type == "agent"
        and span.children in ({"state": 1}, {"state": 1, "store": 1})
        and sum(node.gaps) == 0
    )


def _is_same_name_child(parent: _CandidateSpan, child: _CandidateSpan) -> bool:
    return (
        parent.span is not None
        and child.span is not None
        and parent.span.type in ("solver", "agent")
        and child.span.type in ("solver", "agent")
        and _unqualified(parent.span.name) == _unqualified(child.span.name)
    )


def _transform(node: _CandidateSpan) -> None:
    for item in node.items:
        if isinstance(item, _CandidateSpan):
            _transform(item)

    if _is_agent_solver_wrapper(node):
        _dissolve_item(
            node,
            next(
                i
                for i, item in enumerate(node.items)
                if isinstance(item, _CandidateSpan)
            ),
        )

    index = 0
    while index < len(node.items):
        item = node.items[index]
        if (
            isinstance(item, _CandidateSpan)
            and item.span is not None
            and (item.span.type in _DISSOLVED_TYPES or _is_same_name_child(node, item))
        ):
            _dissolve_item(node, index)
        else:
            index += 1


def _is_empty(node: _CandidateSpan) -> bool:
    span = node.span
    assert span is not None
    if span.type in ("fork_nav", "empty_branch"):
        return False
    return (
        not span.children
        and not any(isinstance(item, SkeletonNotable) for item in node.items)
        and all(
            _is_empty(item) for item in node.items if isinstance(item, _CandidateSpan)
        )
    )


def _needs_sample_init_row(skeleton: SampleSkeleton) -> bool:
    """Mirror the legacy ``collapseSampleInit`` fixup from skeleton facts.

    Legacy synthesizes a ``sample_init`` step around the sample_init event
    on step-only logs with no ``init`` step. Skeleton equivalents: every
    span is a folded step pair (``step-<n>`` ids), none is named ``init``,
    no span holds the sample_init event, and event 0 is loose (no span
    begins there) — a sample's first event is invariably its sample_init.
    """
    spans = skeleton.spans
    return (
        skeleton.counts.events > 0
        and all(span.id.startswith("step-") for span in spans)
        and not any(span.name == "init" for span in spans)
        and not any(span.children.get("sample_init") for span in spans)
        and not any(span.begin == 0 for span in spans)
    )


def _default_collapsed(span: SkeletonSpan) -> bool:
    if span.type == "solver" and span.name == "system_message":
        return True
    if span.name in (SANDBOX_SIGNAL_NAME, "init", "sample_init"):
        return True
    # legacy default-collapses the *elevated* tool/subtask event, which
    # exists only when the span holds a direct tool/subtask event child; a
    # tool span without one keeps its (never default-collapsed) span node
    return span.type in ("tool", "subtask") and bool(span.children.get(span.type))


def candidate_outline_rows(
    skeleton: SampleSkeleton, collapse: CollapseState = "default"
) -> list[OutlineRow]:
    """Outline rows derived from the skeleton alone.

    Args:
        skeleton: The sample's structural skeleton.
        collapse: Same harness-level collapse state as the oracle side
            (span identities are span ids / ``step-<begin index>``).
    """
    root = _build_tree(skeleton)
    _transform(root)

    def is_collapsed(span: SkeletonSpan) -> bool:
        if collapse == "default":
            return _default_collapsed(span)
        if collapse == "expanded":
            return False
        if collapse == "collapsed":
            return True
        return span.id in collapse

    rows: list[OutlineRow] = []

    def emit_sample_init_wrapper() -> None:
        rows.append(OutlineRow("span", 0, "sample_init", None, 0, None))
        # the legacy synthetic step has no uuid and no event index, so it has
        # no span identity — only the default-collapse policy (name match)
        # ever collapses it
        if collapse != "default":
            rows.append(OutlineRow("event", 1, None, "sample_init", 0, None))

    def emit_gap(node: _CandidateSpan, k: int, anchor: int, depth: int) -> None:
        count = node.gaps[k] if k < len(node.gaps) else 0
        if count > 0:
            rows.append(OutlineRow("turns", depth, None, None, anchor, count))

    def emit_items(node: _CandidateSpan, depth: int, in_scorers: bool) -> None:
        anchor = node.span.begin + 1 if node.span is not None else 0
        emit_gap(node, 0, anchor, depth)
        scores: list[SkeletonNotable] = []

        def flush_scores() -> None:
            if scores:
                rows.append(
                    OutlineRow("scoring", depth, None, None, scores[0].i, len(scores))
                )
                scores.clear()

        for k, item in enumerate(node.items):
            if isinstance(item, SkeletonNotable):
                if item.type == "score":
                    scores.append(item)
                else:
                    flush_scores()
                    rows.append(
                        OutlineRow("event", depth, None, item.type, item.i, None)
                    )
                after = item.i + 1
            else:
                flush_scores()
                emit_span(item, depth, in_scorers)
                assert item.span is not None
                after = item.span.extent[1] + 1
            # a nonzero gap emits a turns row, which breaks a run of
            # adjacent score rows — flush before it (a zero gap emits
            # nothing, so buffered scores keep merging across it)
            if node.gaps[k + 1] if k + 1 < len(node.gaps) else 0:
                flush_scores()
            emit_gap(node, k + 1, after, depth)
        flush_scores()

    def emit_span(node: _CandidateSpan, depth: int, in_scorers: bool) -> None:
        span = node.span
        assert span is not None
        if _is_empty(node):
            return
        rows.append(OutlineRow("span", depth, span.name, span.type, span.begin, None))
        if is_collapsed(span):
            return
        if in_scorers and span.type == "scorer":
            return
        # the sample_init event gets a legacy outline row of its own; it is
        # by construction the first event inside its span, so the skeleton's
        # children counter locates it at begin+1
        if span.children.get("sample_init"):
            rows.append(
                OutlineRow(
                    "event", depth + 1, None, "sample_init", span.begin + 1, None
                )
            )
        emit_items(node, depth + 1, in_scorers or span.type == "scorers")

    if _needs_sample_init_row(skeleton):
        emit_sample_init_wrapper()
    emit_items(root, 0, in_scorers=False)
    return rows
